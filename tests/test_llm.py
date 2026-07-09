"""Characterization tests for the Claude LLM backend (agent_system.llm).

These pin the contracts a provider/knob change could silently break — the existing
suite never touches the LLM layer. ``_run_query`` is replaced with a fake so they run
fully offline (no subprocess, no subscription): the str-vs-dict return contract,
preferring the SDK's ``structured_output``, the validate-and-retry → flagged-fallback
path (never a silent blank program), the refusal guard, model-gated knobs, and that
concurrent callers share one event loop.
"""
import threading

import pytest

import agent_system.llm as llm
from agent_system.llm import setup_llm, _QueryResult


@pytest.fixture(autouse=True)
def restore_run_query():
    original = llm._run_query
    yield
    llm._run_query = original


def _qr(text="", structured=None, stop_reason="end_turn"):
    return _QueryResult(text=text, structured_output=structured, stop_reason=stop_reason)


def _patch_sequence(results):
    """Make llm._run_query return each _QueryResult in sequence (last one sticks)."""
    seq = list(results)
    calls = {"n": 0}

    async def fake(prompt, options):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    llm._run_query = fake
    return calls


def _capture_options(result):
    """Patch _run_query to record the options it was called with."""
    captured = {}

    async def fake(prompt, options):
        captured["options"] = options
        captured["prompt"] = prompt
        return result

    llm._run_query = fake
    return captured


def test_non_json_returns_str():
    _patch_sequence([_qr(text="some critique feedback")])
    gen = setup_llm(model="claude-sonnet-4-6", respond_as_json=False, effort="medium")
    out = gen("prompt")
    assert isinstance(out, str) and out == "some critique feedback"


def test_json_returns_dict():
    _patch_sequence([_qr(text='{"weekly_program": {"Day 1": []}}')])
    gen = setup_llm(model="claude-opus-4-8", respond_as_json=True, effort="high")
    out = gen("prompt")
    assert isinstance(out, dict) and "weekly_program" in out


def test_json_prefers_structured_output():
    # text is garbage but structured_output is valid → use the SDK's validated object
    _patch_sequence([_qr(text="not json", structured={"weekly_program": {"Day 1": []}})])
    gen = setup_llm(model="claude-opus-4-8", respond_as_json=True)
    assert gen("prompt") == {"weekly_program": {"Day 1": []}}


def test_json_tolerates_code_fences():
    _patch_sequence([_qr(text='```json\n{"weekly_program": {"Day 1": []}}\n```')])
    gen = setup_llm(model="claude-opus-4-8", respond_as_json=True)
    assert gen("p")["weekly_program"] == {"Day 1": []}


def test_malformed_retry_then_flagged_fallback():
    calls = _patch_sequence([_qr(text="not json at all"), _qr(text="still not json")])
    gen = setup_llm(model="claude-opus-4-8", respond_as_json=True, effort="high")
    out = gen("prompt")
    assert out.get("_llm_error") is True            # never a silent blank program
    assert out["weekly_program"] == {"Day 1": []}
    assert calls["n"] == 2                           # one original + exactly one retry


def test_malformed_then_retry_succeeds():
    _patch_sequence([_qr(text="bad"), _qr(text='{"weekly_program": {"Day 2": []}}')])
    gen = setup_llm(model="claude-opus-4-8", respond_as_json=True, effort="high")
    out = gen("prompt")
    assert out == {"weekly_program": {"Day 2": []}} and "_llm_error" not in out


def test_refusal_returns_no_feedback():
    _patch_sequence([_qr(text="I can't help with that", stop_reason="refusal")])
    gen = setup_llm(model="claude-sonnet-4-6", respond_as_json=False)
    assert gen("prompt") == ""                       # not poison into the revise pass


def test_thinking_model_sets_adaptive_effort_and_fallback():
    captured = _capture_options(_qr(text="ok"))
    gen = setup_llm(model="claude-opus-4-8", respond_as_json=False,
                    effort="high", fallback_model="claude-sonnet-4-6")
    gen("p")
    opts = captured["options"]
    assert opts.thinking == {"type": "adaptive"}     # literal dict, not the no-op TypedDict()
    assert opts.effort == "high"
    assert opts.fallback_model == "claude-sonnet-4-6"


def test_haiku_omits_thinking_and_effort():
    captured = _capture_options(_qr(text="ok"))
    gen = setup_llm(model="claude-haiku-4-5", respond_as_json=False, effort="high")
    gen("p")
    opts = captured["options"]
    assert getattr(opts, "thinking", None) is None   # Haiku supports neither knob
    assert getattr(opts, "effort", None) is None


def test_concurrent_calls_share_loop():
    _patch_sequence([_qr(text='{"weekly_program": {"Day 1": []}}')])
    gen = setup_llm(model="claude-opus-4-8", respond_as_json=True)
    results, errors = [], []

    def worker():
        try:
            results.append(gen("prompt"))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors
    assert len(results) == 5
    assert all(r.get("weekly_program") == {"Day 1": []} for r in results)
