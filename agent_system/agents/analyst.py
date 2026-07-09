"""Analyst agent — interprets analytics metrics into a structured decision document."""
from __future__ import annotations

import json
import logging
from typing import Any

from prompts.analyst_prompts import (
    ANALYST_ROLE,
    ANALYST_DECISION_STRUCTURE,
    ANALYST_DELOAD_STRUCTURE,
    TASK_MESOCYCLE_REVIEW,
    TASK_DELOAD,
)
from agent_system.knowledge import get_subject_context
from agent_system.utils import compact_json

logger = logging.getLogger(__name__)


class Analyst:
    """Produces a decision document (exercise swaps, deload plan, volume changes)
    based on computed analytics and training history."""

    def __init__(
        self,
        model,
    ):
        self.model = model
        self.role = ANALYST_ROLE
        self.on_status = None

    def _emit(self, message: str | None = None, detail: bool = False,
              milestone: str | None = None, reason: str | None = None) -> None:
        if not self.on_status:
            return
        payload: dict = {"step": "analyst"}
        if message is not None:
            payload["message"] = message
        if detail:
            payload["detail"] = True
        if milestone:
            payload["milestone"] = milestone
        if reason:
            payload["reason"] = reason
        self.on_status(payload)

    def _get_knowledge_context(self, review_type: str, exercise_flags: dict) -> str:
        """Pull the relevant subject notes for this review type."""
        if review_type == "deload":
            subjects = ["deload-and-fatigue", "periodization"]
        else:
            subjects = ["periodization", "progressive-overload", "exercise-selection"]
        self._emit("Consulting the strength-training knowledge base...")
        return get_subject_context(subjects)

    def analyze(self, state: dict[str, Any]) -> dict[str, Any]:
        """Produce a decision document from analytics and training history.

        Parameters
        ----------
        state:
            Must contain: analytics, current_mesocycle_history, user-input.
            Optional: previous_block_summaries.

        Returns
        -------
        dict
            The state dict with 'analyst_decision' populated.
        """
        analytics = state.get("analytics", {})
        review_type = analytics.get("review_type", "normal")

        if review_type == "normal":
            logger.info("Analyst skipped — normal progression week")
            return state

        self._emit(f"Analyzing training data for {review_type.replace('_', ' ')}...")

        exercise_flags = analytics.get("exercise_flags", {})
        knowledge_context = self._get_knowledge_context(review_type, exercise_flags)

        analytics_str = compact_json(analytics)
        history_str = compact_json(state.get("current_mesocycle_history", []))
        user_input = state.get("user-input", "")

        if review_type == "deload":
            task = TASK_DELOAD.format(
                analytics_str, history_str, user_input, ANALYST_DELOAD_STRUCTURE
            )
        else:
            summaries_str = compact_json(state.get("previous_block_summaries", []))
            task = TASK_MESOCYCLE_REVIEW.format(
                analytics_str, history_str, summaries_str, user_input,
                ANALYST_DECISION_STRUCTURE
            )

        if knowledge_context:
            task += f"\n\nRelevant strength-training knowledge:\n{knowledge_context}\n"

        prompt = f"{self.role['content']}\n\n{task}"

        self._emit(f"Generating {review_type.replace('_', ' ')} recommendations...")
        try:
            response = self.model(prompt)
            if isinstance(response, str):
                try:
                    decision = json.loads(response)
                except json.JSONDecodeError:
                    decision = {"review_type": review_type, "reasoning": response, "recommendations": []}
            elif isinstance(response, dict):
                decision = response
            else:
                decision = {"review_type": review_type, "reasoning": str(response), "recommendations": []}
        except Exception as e:
            logger.exception("Analyst LLM call failed")
            decision = {
                "review_type": review_type,
                "reasoning": f"Analysis failed: {e}",
                "recommendations": [],
            }

        state["analyst_decision"] = decision
        self._emit(f"Analysis complete: {decision.get('reasoning', '')[:200]}", detail=True)
        logger.info("Analyst decision: %s", json.dumps(decision, indent=2)[:500])
        return state

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.analyze(state)
