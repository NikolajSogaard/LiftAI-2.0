from __future__ import annotations
import logging
from typing import Any
from config import VOLUME_VERIFIER_ENABLED

logger = logging.getLogger(__name__)

from .analytics import analyze_training_history
from . import reasoning
from .verifier import verify_program
from .agents import (
    Writer,
    Critic,
    Editor,
    Analyst,
)


class ProgramGenerator:
    """Week 1 workflow: a linear Writer → Critic → Editor pipeline.

    The Critic's feedback is consumed by the Editor's final revise pass. (A
    reflexion loop once lived here but never executed with real data — adaptive
    thinking is the in-model replacement — so it was removed.) With the loop gone
    the pipeline is a straight line, so it's plain sequential calls rather than a
    graph engine — matching ProgressionProgramGenerator below.
    """

    def __init__(
            self,
            writer: Writer,
            critic: Critic,
            editor: Editor,
            ):
        self.writer = writer
        self.critic = critic

        if not hasattr(editor, 'writer') or editor.writer is None:
            editor.writer = writer
        self.editor = editor
        self.on_status = None

    def _emit(self, step, milestone=None, reason=None):
        if not self.on_status:
            return
        payload = {"step": step}
        if milestone:
            payload["milestone"] = milestone
        if reason:
            payload["reason"] = reason
        self.on_status(payload)

    def _emit_design(self, state, collapse_to=None):
        draft = state.get('draft')
        draft = draft if isinstance(draft, dict) else {}
        for item in reasoning.design_lines(draft, collapse_to=collapse_to):
            self._emit('writer', milestone=item['milestone'], reason=item['reason'])

    def _invoke_once(self, user_input: str) -> dict[str, Any]:
        """Run the Writer → Critic → Editor pipeline once from a fresh state."""
        state = {
            'user-input': user_input,
            'draft': None,
            'feedback': None,
            'formatted': None,
        }
        self._emit('writer', milestone='goals')
        for line in reasoning.goals_lines(user_input):
            self._emit('writer', milestone='goals', reason=line)
        state = self.writer(state)
        self._emit_design(state)
        state = self.critic(state)
        state = self.editor(state)
        return state

    def create_program(self, user_input: str) -> dict[str, Any]:
        """Run the full Writer → Critic → Editor workflow.

        Parameters
        ----------
        user_input:
            The raw user prompt (may include persona info prepended by app.py).

        Returns
        -------
        dict
            Final state dict. The formatted program is at
            ``result['formatted']['weekly_program']``.
        """
        # Propagate status callback to agents
        if self.on_status:
            self.writer.on_status = self.on_status
            self.critic.on_status = self.on_status
            self.editor.on_status = self.on_status

        result = self._invoke_once(user_input)

        # Deterministic volume check (experimental, off by default): if the
        # prescribed per-muscle volume falls outside the level's guidelines, take
        # one fresh re-generation pass. Steady state stays a single generation.
        if VOLUME_VERIFIER_ENABLED:
            formatted = result.get('formatted') or {}
            problems = verify_program(formatted)
            if problems:
                logger.warning("Volume verifier flagged %d issue(s); regenerating once: %s",
                               len(problems), problems)
                if self.on_status:
                    self.on_status({"step": "writer", "message": "Refining program to meet volume targets..."})
                result = self._invoke_once(user_input)

        return result


class ProgressionProgramGenerator:
    """Week 2+ workflow: Analytics → [Analyst] → Writer → [Critic] → Editor.

    Handles three review types:
    - normal: skip Analyst, run progression Writer + progression Critic
    - deload: run Analyst, run deload Writer, skip Critic
    - mesocycle_review: run Analyst, pause for user approval, run new_block Writer + full Critic
    """

    def __init__(
        self,
        writer: "Writer",
        critic: "Critic",
        editor: "Editor",
        analyst: "Analyst",
        mesocycle_length: int = 4,
    ):
        self.writer = writer
        self.critic = critic
        self.editor = editor
        self.analyst = analyst
        self.mesocycle_length = mesocycle_length
        self.on_status = None

        if not hasattr(editor, 'writer') or editor.writer is None:
            editor.writer = writer

    def _propagate_status(self) -> None:
        """Push the on_status callback to all agents."""
        if self.on_status:
            self.writer.on_status = self.on_status
            self.critic.on_status = self.on_status
            self.editor.on_status = self.on_status
            self.analyst.on_status = self.on_status

    def _emit(self, step, milestone=None, reason=None):
        if not self.on_status:
            return
        payload = {"step": step}
        if milestone:
            payload["milestone"] = milestone
        if reason:
            payload["reason"] = reason
        self.on_status(payload)

    def _emit_design(self, state, collapse_to=None):
        draft = state.get('draft')
        draft = draft if isinstance(draft, dict) else {}
        for item in reasoning.design_lines(draft, collapse_to=collapse_to):
            self._emit('writer', milestone=item['milestone'], reason=item['reason'])

    def create_program(
        self,
        user_input: str,
        current_mesocycle_history: list[dict],
        week_in_mesocycle: int,
        previous_block_summaries: list[dict] | None = None,
        feedback: dict | None = None,
        previous_draft: dict | None = None,
    ) -> dict:
        """Run the full progression workflow.

        Returns
        -------
        dict
            Final state dict. If review_type is 'deload' or 'mesocycle_review',
            state['analyst_decision'] contains the decision document and
            state['needs_approval'] is True — the caller must pause for user
            approval before calling continue_after_approval().
            If review_type is 'normal', the full pipeline runs and
            state['formatted'] contains the final program.
        """
        self._propagate_status()

        state = {
            "user-input": user_input,
            "draft": previous_draft,
            "feedback": feedback,
            "formatted": None,
            "current_mesocycle_history": current_mesocycle_history,
            "week_in_mesocycle": week_in_mesocycle,
            "previous_block_summaries": previous_block_summaries or [],
        }

        # Phase 1: Analytics
        analytics = analyze_training_history(
            weeks=current_mesocycle_history,
            week_in_mesocycle=week_in_mesocycle,
            mesocycle_length=self.mesocycle_length,
        )
        state["analytics"] = analytics
        state["exercise_flags"] = analytics.get("exercise_flags", {})

        review_type = analytics["review_type"]
        self._emit('analytics', milestone='analyze')
        for item in reasoning.analyze_lines(analytics):
            self._emit('analytics', milestone='analyze', reason=item['reason'])
        logger.info("Analytics result: review_type=%s, triggers=%s", review_type, analytics["triggers"])

        if review_type == "normal":
            for item in reasoning.adjust_lines(analytics):
                self._emit('writer', milestone='adjust', reason=item['reason'])
            state = self.writer(state)
            state = self.critic(state)
            state = self.editor(state)
            return state

        # Phase 2: Analyst (for deload or mesocycle_review)
        state = self.analyst(state)
        state["needs_approval"] = True
        return state

    def continue_after_approval(self, state: dict) -> dict:
        """Resume the workflow after the user approves the analyst decision."""
        self._propagate_status()
        state.pop("needs_approval", None)

        review_type = state["analytics"]["review_type"]

        state = self.writer(state)

        if review_type == "deload":
            self._emit_design(state, collapse_to="rebuild")
        else:
            self._emit_design(state)
            state = self.critic(state)

        state = self.editor(state)
        return state
