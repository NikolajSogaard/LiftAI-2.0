"""Tests for the deterministic volume verifier (agent_system.verifier)."""
from agent_system.verifier import verify_program


def _ex(name, sets, patterns):
    return {"name": name, "sets": sets, "reps": "8-12", "patterns": patterns}


def test_empty_program_flagged():
    assert verify_program({"weekly_program": {}}) == ["program has no training days"]
    assert verify_program({}) == ["program has no training days"]


def test_empty_day_flagged():
    problems = verify_program({"weekly_program": {"Day 1": []}})
    assert any("Day 1 has no exercises" in p for p in problems)


def test_missing_required_field_flagged():
    prog = {"weekly_program": {"Day 1": [{"name": "Bench", "patterns": ["Upper_horizontal_push"]}]}}
    problems = verify_program(prog, level="intermediate")
    assert any("missing" in p for p in problems)


def test_over_volume_flagged():
    prog = {"weekly_program": {"Day 1": [_ex("Bench", 40, ["Upper_horizontal_push"])]}}
    problems = verify_program(prog, level="intermediate")
    assert any("Upper_horizontal_push" in p and "above max" in p for p in problems)


def test_passes_when_volume_in_range():
    weekly = {
        "Day 1": [
            _ex("Bench", 12, ["Upper_horizontal_push"]),
            _ex("Row", 12, ["Upper_horizontal_pull"]),
            _ex("OHP", 10, ["Upper_vertical_push"]),
            _ex("Pulldown", 12, ["Upper_vertical_pull"]),
            _ex("Squat", 12, ["Lower_anterior_chain"]),
            _ex("RDL", 12, ["Lower_posterior_chain"]),
        ]
    }
    assert verify_program({"weekly_program": weekly, "level": "intermediate"}) == []


def test_level_read_from_program_field():
    prog = {"level": "intermediate",
            "weekly_program": {"Day 1": [_ex("Bench", 3, ["Upper_horizontal_push"])]}}
    problems = verify_program(prog)
    assert any("Upper_horizontal_push" in p and "below min" in p for p in problems)  # 3 < 10
