"""LLM backend for the agent system — Anthropic Claude via the Claude Agent SDK.

Every agent reaches the model through the ``generate_response(prompt) -> str | dict``
closure returned by :func:`setup_llm`. The Agent SDK authenticates with the local
``claude`` CLI login, so model usage draws on the Claude subscription — no API key.

Design notes
------------
* **One shared event loop.** ``query()`` is async and the SDK starts a CLI
  subprocess per call. Rather than ``asyncio.run`` per call — which cold-starts a
  fresh loop (and, under the Week-1 critic's ``ThreadPoolExecutor``, several at
  once) — all queries run on a single lazily-started background loop and block the
  caller via ``run_coroutine_threadsafe(...).result(timeout=LLM_CALL_TIMEOUT)``.
  ``generate_response`` stays synchronous, so the str-vs-dict contract is unchanged.
* **Structured output.** When ``respond_as_json`` we prefer the SDK's real
  ``ResultMessage.structured_output`` field; otherwise we parse the text (tolerating
  ```json fences``). On a parse failure we retry once at low effort with a terse
  "JSON only" nudge, then fall back to a defensive blank program tagged
  ``_llm_error=True`` (so the editor carries the flag through and app.py emits an
  ``error`` SSE step instead of shipping a silent blank Day-1 program as ``done``).
* **Knobs.** Opus 4.8 / Sonnet 4.6 are adaptive-thinking-only — ``temperature`` /
  ``top_p`` / ``budget_tokens`` are removed on those models and would 400 on a raw
  API call, which is why this backend never sends them. Depth is controlled by
  adaptive thinking + ``effort``. Neither is supported on Haiku, so both are gated
  to non-Haiku models.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import threading

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from config import LLM_CALL_TIMEOUT

logger = logging.getLogger(__name__)

# System prompt for JSON-mode generation. Claude has no response_mime_type, so we
# instruct strict JSON and parse defensively (preferring structured_output when set).
_JSON_SYSTEM_PROMPT = (
    "You are a JSON generation engine. Respond with exactly one valid JSON value "
    "that satisfies the user's instructions and schema. Output only the JSON: no "
    "markdown code fences, no commentary, no text before or after it."
)

_RETRY_NUDGE = (
    "\n\nReturn ONLY one valid JSON value — no prose, no explanation, no markdown "
    "code fences."
)


# ── Shared background event loop ─────────────────────────────────────────────
_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return the shared background event loop, starting it on first use.

    One loop runs forever in a daemon thread; every query is submitted to it.
    This replaces per-call ``asyncio.run`` (which cold-started a loop — and an SDK
    subprocess — for each of the five parallel critics). Lock-guarded so concurrent
    first-callers don't start two loops; never closed per call.
    """
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            threading.Thread(
                target=_loop.run_forever, daemon=True, name="llm-event-loop"
            ).start()
        return _loop


def _submit(coro):
    """Run *coro* on the shared loop from a sync caller and block for the result."""
    future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return future.result(timeout=LLM_CALL_TIMEOUT)


@dataclasses.dataclass
class _QueryResult:
    text: str
    structured_output: object | None
    stop_reason: str | None


async def _run_query(prompt: str, options: ClaudeAgentOptions) -> _QueryResult:
    """Run one single-shot Agent SDK query and collect its final text + metadata.

    Consumes the stream to completion so the underlying async generator closes
    cleanly (avoids the ``aclose(): generator already running`` teardown warning).
    """
    result_text: str | None = None
    text_parts: list[str] = []
    structured = None
    stop_reason = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
        elif isinstance(message, ResultMessage):
            if message.is_error:
                logger.warning("Agent SDK reported an error result: %s", message.result)
            result_text = message.result
            structured = message.structured_output
            stop_reason = message.stop_reason
    # ResultMessage.result is the canonical final text; fall back to concatenated
    # assistant text blocks if it's absent.
    text = result_text if result_text is not None else "".join(text_parts)
    return _QueryResult(text=text or "", structured_output=structured, stop_reason=stop_reason)


def _coerce_json(text: str):
    """Parse a JSON value from model output, tolerating ```json fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    return json.loads(stripped)


def _error_program(text: str) -> dict:
    """Defensive shape returned only after a JSON parse failure + one retry.

    Tagged ``_llm_error`` so the editor carries the flag onto ``formatted`` and
    app.py emits the ``error`` SSE step rather than shipping this blank program as a
    green ``done``.
    """
    return {"weekly_program": {"Day 1": []}, "message": text, "_llm_error": True}


def _is_thinking_model(model: str) -> bool:
    """Opus 4.8 / Sonnet 4.6 support adaptive thinking + ``effort``; Haiku 4.5
    supports neither and would error."""
    return not model.startswith("claude-haiku")


def setup_llm(
    model: str,
    respond_as_json: bool = False,
    response_schema: dict | None = None,
    effort: str | None = None,
    fallback_model: str | None = None,
):
    """Build and return a Claude generation closure ``(prompt) -> str | dict``.

    Parameters
    ----------
    model:
        Claude model id (e.g. ``claude-opus-4-8``).
    respond_as_json:
        When True the closure returns a parsed ``dict``; otherwise a ``str``.
    response_schema:
        Optional JSON schema. When provided it is passed to
        ``ClaudeAgentOptions.output_format`` and the SDK's validated
        ``ResultMessage.structured_output`` is preferred over text parsing. No caller
        passes one today; the seam is plumbed for a future structured-output path.
    effort:
        ``low``/``medium``/``high``/``xhigh``/``max`` — controls thinking depth and
        token spend. Gated off for Haiku (which does not support it).
    fallback_model:
        Model the SDK falls back to on a transient error (e.g. Sonnet for the Opus
        writer) — a graceful degrade rather than an empty program.

    Notes
    -----
    Opus 4.8 / Sonnet 4.6 are adaptive-thinking-only; ``temperature`` / ``top_p`` /
    ``budget_tokens`` are removed on those models and are deliberately never sent.
    """
    options_kwargs: dict = dict(
        model=model,
        max_turns=1,          # single-shot generation, never an agentic tool loop
        allowed_tools=[],     # no tools — pure text/JSON completion
    )
    if _is_thinking_model(model):
        # Literal dict — a bare ThinkingConfigAdaptive() is a silent no-op {}.
        options_kwargs["thinking"] = {"type": "adaptive"}
        if effort:
            options_kwargs["effort"] = effort
    if fallback_model:
        options_kwargs["fallback_model"] = fallback_model
    if respond_as_json:
        options_kwargs["system_prompt"] = _JSON_SYSTEM_PROMPT
        if response_schema:
            options_kwargs["output_format"] = response_schema

    options = ClaudeAgentOptions(**options_kwargs)

    def _low_effort(opts: ClaudeAgentOptions) -> ClaudeAgentOptions:
        """A copy of *opts* dialed to low effort — bounds latency on the retry."""
        if getattr(opts, "effort", None):
            return dataclasses.replace(opts, effort="low")
        return opts

    def generate_response(prompt):
        result = _submit(_run_query(prompt, options))
        text = result.text.strip()

        if not respond_as_json:
            # Critic / non-JSON branch: a refusal must not poison the Writer's
            # revise pass — treat it (like an empty reply) as "no feedback".
            if result.stop_reason == "refusal":
                logger.warning("Non-JSON response refused (stop_reason=refusal); treating as no feedback")
                return ""
            return text

        # JSON branch — prefer the SDK's validated structured output.
        if result.structured_output is not None:
            return result.structured_output
        try:
            return _coerce_json(text)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("JSON decode failed: %s | Raw: %.200s — retrying once at low effort", e, text)
            retry = _submit(_run_query(prompt + _RETRY_NUDGE, _low_effort(options)))
            if retry.structured_output is not None:
                return retry.structured_output
            retry_text = retry.text.strip()
            try:
                return _coerce_json(retry_text)
            except (json.JSONDecodeError, TypeError):
                logger.error("JSON decode failed after retry — surfacing as a generation error")
                return _error_program(retry_text or text)

    return generate_response
