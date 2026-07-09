from agent_system.agents.editor import Editor


def test_editor_emits_finalize_milestone():
    captured = []
    ed = Editor()
    ed.on_status = captured.append
    program = {"draft": {"weekly_program": {"Day 1": [{"name": "Squat", "sets": 3, "reps": "5"}]}}}
    ed(program)
    assert any(m.get("milestone") == "finalize" for m in captured)
