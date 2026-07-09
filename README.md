# LiftAI: Agent-Based Strength-Training Program Generator

LiftAI turns a short intake form (or a test persona) into a complete, individualized
strength-training program — and then progresses it week over week. A team of AI agents
drafts, critiques, and edits each program, grounded in a hand-curated knowledge base of
strength-training principles and example templates.

![LiftAI generating a program for a test persona](assets/liftai_demo.gif)

## Demo

The clip above runs the built-in **"Busy Beginner"** persona end to end:

1. **Pick a persona** (or fill in the intake form yourself).
2. **Generate** — the Writer → Critic → Editor pipeline streams its progress live.
3. **Review the program** — a structured, day-by-day training plan.

### Program generation
![Generate page](assets/generate_screenshot.png)

### Program view
![Program view](assets/index_screenshot.png)

## How it works

LiftAI is a Flask web app driving a multi-agent pipeline. The LLM backend is
**Anthropic Claude via the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk)**,
running on a local `claude` CLI login — **no API key and no `.env` file required**.

### The agents

| Agent | Role |
| ----- | ---- |
| **Writer** | Drafts the initial program (and applies revisions), grounded in the knowledge base. |
| **Critic** | Evaluates the draft against volume, frequency, intensity, and exercise-selection targets, returning feedback. |
| **Editor** | Normalizes the final program to a strict JSON schema the frontend can render. |
| **Analyst** | (Week 2+) Reads logged performance and decides the week's progression / autoregulation. |

Two orchestration paths, both plain sequential calls (no graph engine):

- **Week 1** — `ProgramGenerator`: Writer → Critic → Editor.
- **Week 2+** — `ProgressionProgramGenerator`: Analytics → *Analyst* → human approval gate
  (deload / mesocycle review) → Writer → *Critic* → Editor.

### The knowledge base — "the brain"

Domain knowledge lives in `Data/brain/` as **authorless Markdown**, read directly into
the agents' prompts by `agent_system/knowledge.py` — no embeddings, no vector store, no
retrieval latency:

- `subjects/` — 17 principle notes (volume, frequency, progression, program structure, …).
- `programs/` — 22 example program templates that ground the Writer's first draft.

It's Obsidian-native — open `Data/brain/` as a vault to browse the wikilink graph. *(This
replaced an earlier FAISS/RAG stack, which has been removed.)*

## Setup

Requires **Python 3.10+** and a Claude subscription (the `claude` CLI login).

```bash
# 1. Create a virtualenv and install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Authenticate the Claude CLI once (uses your Claude subscription — no API key)
claude setup-token

# 3. Run the app
python app.py                 # → http://127.0.0.1:5000
```

Open the app, pick a test persona (or fill in the form), and generate a program.

## Testing

```bash
python -m pytest tests/ -v    # full suite — fully offline, mocks the model
```

The tests mock the LLM, so they need no subscription. For real end-to-end verification,
run `python app.py` and exercise `/generate`, `/next_week`, and a forced deload.

## Project layout

```
app.py                          Flask routes, sessions, SSE streaming, threaded jobs
config.py                       Model IDs, thresholds, feature flags, the volume table
agent_system/
  llm.py                        The Claude chokepoint — setup_llm()
  generator.py                  Week-1 and Week-2+ orchestrators
  agents/                       writer / critic / editor / analyst
  chatbot.py                    Live program editor (Agent SDK tool-use)
  analytics.py                  Pure-Python autoregulation (no LLM)
  knowledge.py                  Reads Data/brain/ Markdown into prompts
prompts/                        All prompt text
templates/                      index.html, generate.html
Data/brain/                     The knowledge base (subjects/ + programs/)
```
