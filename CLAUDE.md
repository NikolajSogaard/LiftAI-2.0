# CLAUDE.md

Operating guidelines for working in **LiftAI** — combine with the codebase reference
below. They reduce common missteps; they bias toward caution over speed, so for
trivial tasks use judgment.

## What this is

LiftAI is an agent-based system that generates personalized strength-training
programs. A Flask web app drives a multi-agent pipeline (Writer → Critic → Editor,
plus an Analyst for week-2+ progression). The LLM backend is **Anthropic Claude via
the Claude Agent SDK** (`claude-agent-sdk`), running on the owner's **Claude
subscription** — the local `claude` CLI login, **no API key, no `cre.env`**. The
Gemini→Claude migration has shipped and the generation pipeline has been
re-architected; the notes below reflect the current state, not the migration plan.
Domain knowledge comes from a hand-curated, authorless markdown **knowledge base**
(`Data/brain/`), read by the agents as plain prompt text — this replaced the old
FAISS/RAG layer, which is now deleted.

## 1. Think Before Acting

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly; if uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- For anything touching the Claude SDK, model IDs, or request shapes, **consult the
  `claude-api` skill** rather than relying on memory.

## 2. Simplicity First

**Do the minimum that solves the problem. Nothing speculative.**

- No deliverables, structure, or configurability beyond what was asked.
- No handling for scenarios that can't occur.
- The two experimental flags (`CRITIC_SINGLE_CALL`, `VOLUME_VERIFIER_ENABLED`) are
  **off by default**: they need live A/B validation before flipping. Don't enable
  them as part of unrelated work.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- Match the existing style. Don't rework things that aren't broken.
- Preserve the **hard contracts** (see Codebase below) — SSE step names, the
  str-vs-dict return shape, the approval gate. Breaking one silently breaks the UI
  or the pipeline.
- If you notice unrelated obsolete content, mention it — don't delete it unless
  removing it is the task.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

- "Fix the bug" → reproduce first, then confirm the fix.
- After any change to the LLM/agent layer: `python -m pytest tests/ -v` must stay
  green, `python -c "import app"` must succeed, and — because the offline tests mock
  the model — a manual `python app.py` run (`/generate`, `/next_week`, a forced
  deload) is the real verification. State plainly what you verified and what you
  didn't.

---

## Run / test / build

All commands run from the repo root (`Data/` and relative paths only resolve there).
Use a Python **3.10+** venv (`int | None` / `list[float]` syntax). Auth once with
`claude setup-token`.

```bash
python app.py                                  # Flask dev server → 127.0.0.1:5000 (debug=True, reloader OFF)
python -m pytest tests/ -v                     # full suite (all offline, no subscription needed)
python -m pytest tests/test_analytics.py -v    # pure-Python autoregulation
python -m pytest tests/test_knowledge.py tests/test_brain.py -v  # brain reader + authorless lint
```

The knowledge base in `Data/brain/` is committed markdown — there is **no build
step**. `scripts/brain_extract.py` dumps a PDF page-range to text for ingestion.

`app.run(debug=True, use_reloader=False)` — reloader is off **on purpose** (background
threads + reloader double-spawn). Don't turn it back on.

### Tests
`test_analytics.py` (autoregulation), `test_log_set.py` (`/log_set` route),
`test_llm.py` (LLM-backend characterization: str/dict contract, structured-output
preference, validate-retry → flagged fallback, refusal guard, shared-loop
concurrency — `_run_query` is mocked, fully offline), `test_verifier.py`,
`test_error_flag.py` (the `_llm_error` carry-through). No pytest config; run from the
repo root.

## Architecture

```
Browser (templates/index.html, generate.html)
  │  POST /generate, /next_week, /log_set, /chat ; EventSource SSE
  ▼
app.py  ── Flask routes, server-side sessions, SSE streaming, threaded jobs
  │   builds per-agent LLM callables via setup_llm(); wires the orchestrators
  ▼
agent_system/
  generator.py
    ProgramGenerator            ── Week 1: LINEAR Writer → Critic → Editor,
                                   plain sequential calls (reflexion + LangGraph removed)
    ProgressionProgramGenerator ── Week 2+: hand-coded pipeline (same plain-call style)
                                   Analytics → [Analyst] → approval gate → Writer → [Critic] → Editor
  agents/  writer.py critic.py editor.py analyst.py    ── each calls self.model(prompt)
  chatbot.py  ProgramChatbot    ── live program editor, Agent SDK tool-use (separate path)
  tool_schemas.py               ── shared edit-tool JSON Schemas (used by chatbot.py)
  analytics.py                  ── pure-Python autoregulation (no LLM)
  verifier.py                   ── deterministic volume check (gated; reuses VOLUME_GUIDELINES)
  knowledge.py                  ── reads Data/brain/ markdown into prompts (no embeddings, no LLM)
  llm.py                        ── THE Claude chokepoint: setup_llm()
Data/brain/                     ── the knowledge base: subjects/ (17 principle notes) + programs/ (22 example templates)
config.py                       ── model IDs, knobs, thresholds, flags, the volume table
prompts/                        ── all prompt text
```

### The LLM chokepoint — `agent_system/llm.py`
Renamed from `setup_api.py` (there is no external API; it's the subscription).
`setup_llm(model, max_tokens=None, respond_as_json=False, response_schema=None,
effort=None, fallback_model=None)` returns a synchronous
`generate_response(prompt) -> str | dict`. Rewriting this one body migrates ~90% of
call sites. Key behaviors:

- **One shared background event loop.** Queries run on a single lazily-started daemon
  loop via `run_coroutine_threadsafe(...).result(timeout=LLM_CALL_TIMEOUT)` instead of
  `asyncio.run` per call. `generate_response` stays synchronous (the str/dict contract
  is unchanged). `chatbot.py` keeps its own `asyncio.run` and is left alone.
- **Knobs that are real now.** Adaptive thinking (`{"type": "adaptive"}` — the literal
  dict; a bare `ThinkingConfigAdaptive()` is a silent no-op `{}`) + `effort`, both
  **gated off for Haiku** (it supports neither). `fallback_model` for graceful degrade.
  `temperature`/`top_p`/`budget_tokens` are **gone** — they'd 400 on Opus 4.8/Sonnet 4.6.
- **Structured output.** When `respond_as_json`, prefer `ResultMessage.structured_output`;
  else parse the text (tolerating ```json fences); on failure **retry once at low
  effort**, then return a defensive blank program tagged `_llm_error=True`.
  `response_schema` → `output_format` is plumbed but no caller passes one.
- **Refusal guard.** A non-JSON (Critic) response with `stop_reason == "refusal"`
  returns `""` (treated as "no feedback") rather than poisoning the revise pass.

### Two orchestration paths (important)
- **Week 1** (`ProgramGenerator`) is a straight Writer → Critic → Editor — plain
  sequential calls (`state = agent(state)`), no graph engine. The reflexion loop
  (`_reflect`, reflector node, `lessons`, `max_iterations`) was **deleted** — it never
  executed with real data; adaptive thinking is the in-model replacement. With the loop
  gone the pipeline was a straight line, so LangGraph was removed too (2026-06-14).
- **Week 2+** (`ProgressionProgramGenerator`) uses the **same** plain sequential
  function calls — both paths now share one mental model.
- Human-in-the-loop approval (deload / mesocycle review) lives **outside** any engine:
  the full `state` is stashed in a process-global dict and the app re-invokes
  `continue_after_approval(state)` on a later `/approve_review` request.

### Request/streaming model
- Generation runs in `threading.Thread` daemons wrapped in
  `@copy_current_request_context`. Workers stash results in process-global dicts
  (`_generation_results`) and only commit to the session on a later `/.../complete/<job_id>`
  GET. **Single-process only** — multiple workers break SSE handoff. Not production WSGI.
- **SSE step names are a hard contract.** Backend emits
  `writer`/`critic`/`editor`/`analytics`/`analyst`/`review`/`done`/`error`/`timeout`;
  the templates switch on these exact strings. A flagged `_llm_error` program now
  emits the existing `error` step (via `_formatted_has_error`) instead of shipping a
  blank program as a green `done`.

## Conventions & gotchas

- **Pipeline state is an untyped `dict`** with the hyphenated key `'user-input'` (not
  `user_input`). A `feedback_applied` flag set by Writer is consumed by Critic/Editor
  to avoid a double revise pass.
- **`self.model(prompt)` returns heterogeneous types.** Writer/Analyst run
  `respond_as_json=True` → parsed `dict`; Critic runs `respond_as_json=False` → `str`.
  Any backend shim must preserve this.
- **Prompts are one flattened string** (`role['content'] + task`), not a system/user
  split. Templates use positional `{}` `str.format` placeholders — order matters.
- **Config is the source of truth for tunables.** `DEFAULT_WRITER_EFFORT='high'`,
  `DEFAULT_CRITIC_EFFORT='medium'`, `DEFAULT_FALLBACK_MODEL`, `LLM_CALL_TIMEOUT=600`
  (per-call cap on the shared loop — distinct from `QUEUE_TIMEOUT=120`, the SSE
  inter-message idle budget that resets on every status message). Model IDs now live
  only in `config.py` (the old `rag_retrieval.py`/`build_db.py` copies went with the RAG layer).
- **Two experimental flags, both OFF:** `CRITIC_SINGLE_CALL` (Week-1: one multi-aspect
  Critic call instead of the 5-thread fan-out) and `VOLUME_VERIFIER_ENABLED` (Week-1:
  one re-generation if the deterministic volume check fails). A/B them live before
  flipping.
- **Volume table (`config.py`).** Single source of truth for the Critic's `set_volume`
  task and the `compute_muscle_volume` panel/verifier. The `advanced` tier is now
  distinct from `intermediate`; the Critic is fed only the user's level row (read from
  the draft's `level`), so the panel and the LLM critic agree.
- **Knowledge base — "the brain" (`Data/brain/`).** Authorless markdown, read into
  prompts by `agent_system/knowledge.py` (deterministic — no embeddings, no LLM, no
  latency). `subjects/` holds 17 principle notes (incl. `program-structure` = how to
  assemble a program); `programs/` holds 22 example templates. Built from the Muscle
  Ladder, with powerlifting/strength depth folded into each note's
  `## Strength / powerlifting nuance` section from the other books — **Phases 1 & 2
  both shipped & live-verified.** `get_subject_context(subjects)` feeds the Writer
  (per mode via `mode_subjects`), the Critic (per dimension, 1:1 via `aspect_subjects`),
  and the Analyst; `get_example_programs(user_input)` grounds the Writer's initial
  draft with a request-matched template. Missing notes degrade to `""` (the old RAG
  empty-context contract). It's Obsidian-native — open `Data/brain` as a vault for the
  wikilink graph. The FAISS/RAG stack (`rag_retrieval.py`, `build_db.py`,
  `setup_embeddings`) is **deleted**. **Invariant:** the Writer formats its task
  template *before* appending brain/example text, so a note may safely contain literal
  `{`/`}` — don't revert to append-then-`.format()`. (Not ingested, deliberately: the
  JN program-template PDFs — Essentials/Pure Bodybuilding/etc. — redundant with the 20 ML programs.)
- Set logging has **two parallel persistence paths**: fast `POST /log_set` into
  `session['set_log']`, and hidden form fields on the `/next_week` form (the latter
  feeds progression).

> **Plans:** `docs/superpowers/plans/2026-06-14-gemini-to-claude-migration.md`
> (migration, shipped), `…-generation-pipeline-rearchitecture.md` (that rework), and
> `2026-06-20-knowledge-brain.md` (the brain that replaced RAG — Phase 1 shipped;
> spec: `docs/superpowers/specs/2026-06-20-strength-training-brain-design.md`).
> `CLAUDE.md` is gitignored — it stays local, not committed.
