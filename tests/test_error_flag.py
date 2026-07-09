"""Phase-3: a JSON parse failure surfaces as an `error`, never a silent blank program.

The LLM backend tags an unrecoverable parse failure with ``_llm_error``; the Editor
must carry that flag onto the fresh ``formatted`` dict, and app.py must recognise it.
"""
from agent_system.agents.editor import Editor
from app import _formatted_has_error


def test_editor_carries_llm_error_onto_formatted():
    draft = {"weekly_program": {"Day 1": []}, "message": "garbage", "_llm_error": True}
    formatted = Editor().format_program({"draft": draft})
    assert formatted.get("_llm_error") is True


def test_editor_no_flag_on_clean_draft():
    draft = {"level": "intermediate",
             "weekly_program": {"Day 1": [{"name": "Bench", "sets": 3, "reps": "8-12"}]}}
    formatted = Editor().format_program({"draft": draft})
    assert "_llm_error" not in formatted


def test_formatted_has_error_helper():
    assert _formatted_has_error({"_llm_error": True}) is True
    assert _formatted_has_error({"weekly_program": {}}) is False
    assert _formatted_has_error(None) is False
    assert _formatted_has_error("not a dict") is False
