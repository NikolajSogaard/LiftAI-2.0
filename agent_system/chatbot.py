"""Chatbot for live program editing on the program viewer page.

Backed by the Claude Agent SDK (migrated from Gemini function-calling, 2026-06-14).
The three editor actions are exposed as in-process SDK MCP tools; Claude calls
them through its tool loop and they mutate the program dict directly. Auth is the
local `claude` login (the Claude subscription) — no API key.
"""

import asyncio
import logging

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    tool,
    create_sdk_mcp_server,
)

from config import MAX_CHAT_MESSAGE_CHARS, MAX_CHAT_HISTORY_TURNS
from agent_system.tool_schemas import TOOL_SCHEMAS
from agent_system.utils import compact_json

logger = logging.getLogger(__name__)

_MCP_SERVER_NAME = "editor"

_SYSTEM_PROMPT = """You are LiftAI Coach, an expert strength training assistant embedded in the LiftAI program viewer.

The user has a generated training program in front of them. You help them:
1. Live-edit the program (change exercises, sets, reps, RIR, cues) using tools
2. Answer training questions about why certain choices were made
3. Explain the structure of the program and the science behind it
4. Suggest improvements and apply them immediately if the user agrees

When the user asks you to change something, use the appropriate tool to make the edit, then confirm what you changed.
If something is unclear, ask a clarifying question before making an edit.
Keep replies concise. You are a coach, not a textbook.

Current program:
{program_json}
"""


def _extract_history_text(turn) -> str:
    """Pull plain text from a history turn (Gemini 'parts' or Claude 'content')."""
    if isinstance(turn, str):
        return turn
    if not isinstance(turn, dict):
        return ""
    parts = turn.get("parts")
    if isinstance(parts, list):
        return " ".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    content = turn.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict)).strip()
    return ""


def _build_prompt(history, message: str) -> str:
    """Fold prior turns into a single prompt (role 'model'/'assistant' -> Coach)."""
    lines = []
    for turn in history or []:
        text = _extract_history_text(turn)
        if not text:
            continue
        role = turn.get("role") if isinstance(turn, dict) else "user"
        speaker = "User" if role == "user" else "Coach"
        lines.append(f"{speaker}: {text}")
    if lines:
        return "Conversation so far:\n" + "\n".join(lines) + f"\n\nUser: {message}"
    return message


class ProgramChatbot:
    def __init__(self, model_name: str, client=None):
        self.model_name = model_name
        self.client = client  # unused (Agent SDK auths via the claude login)

    def _apply_function_call(self, fn_name: str, args: dict, program: dict) -> tuple[dict, str]:
        """Apply a tool function call to the program state. Backend-agnostic.

        Returns the updated ``weekly_program`` dict and a human-readable
        description of the change.
        """
        program = {day: list(exs) for day, exs in program.items()}  # shallow copy

        if fn_name == "edit_exercise":
            day = args.get("day")
            idx = args.get("exercise_index", 0)
            if day not in program or idx >= len(program[day]):
                return program, f"Error: day '{day}' or exercise index {idx} not found."
            ex = dict(program[day][idx])
            for field in ("name", "sets", "reps", "target_rir", "cues", "rest", "technique"):
                if field in args and args[field] is not None:
                    ex[field] = args[field]
            program[day][idx] = ex
            return program, f"Updated '{ex['name']}' on {day}."

        if fn_name == "add_exercise":
            day = args.get("day")
            if day not in program:
                return program, f"Error: day '{day}' not found."
            new_ex = {
                "name": args.get("name", "New Exercise"),
                "sets": args.get("sets", 3),
                "reps": args.get("reps", "8-12"),
                "target_rir": args.get("target_rir", "1-2"),
                "cues": args.get("cues", ""),
                "rest": args.get("rest", "90 seconds"),
                "technique": args.get("technique"),
            }
            program[day].append(new_ex)
            return program, f"Added '{new_ex['name']}' to {day}."

        if fn_name == "remove_exercise":
            day = args.get("day")
            idx = args.get("exercise_index", 0)
            if day not in program or idx >= len(program[day]):
                return program, f"Error: day '{day}' or exercise index {idx} not found."
            removed = program[day].pop(idx)
            return program, f"Removed '{removed['name']}' from {day}."

        return program, f"Unknown function: {fn_name}"

    def _build_tools(self, state: dict):
        """Build the three editor tools, closing over mutable ``state``."""
        def make(fn_name):
            async def handler(args):
                new_prog, desc = self._apply_function_call(fn_name, args, state["program"])
                state["program"] = new_prog
                state["results"].append(desc)
                return {"content": [{"type": "text", "text": desc}]}
            return handler

        return [
            tool(s["name"], s["description"], s["input_schema"])(make(s["name"]))
            for s in TOOL_SCHEMAS
        ]

    async def _run(self, prompt: str, options: ClaudeAgentOptions) -> str:
        result_text = None
        text_parts: list[str] = []
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                result_text = message.result
        return (result_text if result_text is not None else "".join(text_parts)) or ""

    def chat(self, message: str, program: dict, history: list = None) -> dict:
        """Send a message; returns reply + optional updated program + edit descriptions."""
        if len(message) > MAX_CHAT_MESSAGE_CHARS:
            message = message[:MAX_CHAT_MESSAGE_CHARS]
            logger.warning("chat() message truncated to %d chars", MAX_CHAT_MESSAGE_CHARS)
        if history and len(history) > MAX_CHAT_HISTORY_TURNS:
            history = history[-MAX_CHAT_HISTORY_TURNS:]
            logger.warning("chat() history trimmed to last %d turns", MAX_CHAT_HISTORY_TURNS)

        state = {"program": {day: list(exs) for day, exs in program.items()}, "results": []}

        server = create_sdk_mcp_server(name=_MCP_SERVER_NAME, tools=self._build_tools(state))
        allowed = [f"mcp__{_MCP_SERVER_NAME}__{s['name']}" for s in TOOL_SCHEMAS]
        options = ClaudeAgentOptions(
            model=self.model_name,
            system_prompt=_SYSTEM_PROMPT.format(program_json=compact_json(program)),
            mcp_servers={_MCP_SERVER_NAME: server},
            allowed_tools=allowed,
            max_turns=6,
        )

        try:
            reply = asyncio.run(self._run(_build_prompt(history, message), options)).strip()
        except Exception:
            logger.exception("Chatbot Claude call failed")
            return {"reply": "Sorry, I encountered an error. Please try again.",
                    "updated_program": None, "function_results": []}

        updated_program = state["program"] if state["results"] else None
        if not reply:
            reply = " ".join(state["results"]) if state["results"] else "I'm not sure how to help with that."

        return {
            "reply": reply,
            "updated_program": updated_program,
            "function_results": state["results"],
        }
