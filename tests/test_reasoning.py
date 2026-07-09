from agent_system import reasoning


def test_week1_plan_shape():
    keys = [m["key"] for m in reasoning.WEEK1_PLAN]
    assert keys == ["goals", "split", "exercises", "intensity", "audit", "finalize"]
    assert all("label" in m and m["label"] for m in reasoning.WEEK1_PLAN)


def test_progression_and_continuation_plans():
    assert [m["key"] for m in reasoning.progression_plan("normal")] == [
        "analyze", "adjust", "audit", "finalize"]
    assert [m["key"] for m in reasoning.continuation_plan("deload")] == ["rebuild", "finalize"]
    assert [m["key"] for m in reasoning.continuation_plan("mesocycle_review")] == [
        "split", "exercises", "intensity", "audit", "finalize"]


def test_goals_lines_echoes_profile():
    lines = reasoning.goals_lines("Experience Level: Intermediate\nPrimary Goal: Hypertrophy")
    assert lines == ["Experience Level: Intermediate", "Primary Goal: Hypertrophy"]


def test_goals_lines_persona_fallback():
    assert reasoning.goals_lines(
        "Generate a strength training program for the selected persona.") == [
        "Reading your training profile"]


DRAFT = {
    "level": "Intermediate",
    "weekly_program": {
        "Upper A": [
            {"name": "Bench Press", "sets": 4, "reps": "6-8"},
            {"name": "Barbell Row", "sets": 4, "reps": "8-10"},
        ],
        "Lower A": [
            {"name": "Squat", "sets": 4, "reps": "5-8"},
            {"name": "Romanian Deadlift", "sets": 3, "reps": "8-12"},
        ],
    },
}


def test_design_lines_structure_and_keys():
    out = reasoning.design_lines(DRAFT)
    assert out and all(set(item) == {"milestone", "reason"} for item in out)
    assert {i["milestone"] for i in out} <= {"split", "exercises", "intensity"}


def test_design_lines_content():
    reasons = [i["reason"] for i in reasoning.design_lines(DRAFT)]
    assert any("2 training days per week" in r for r in reasons)
    assert any("Bench Press" in r for r in reasons)
    assert any("5–12 reps" in r for r in reasons)
    assert any("Chest/pressing: 4 sets/wk" in r for r in reasons)


def test_design_lines_collapse_to_rebuild():
    out = reasoning.design_lines(DRAFT, collapse_to="rebuild")
    assert out and all(i["milestone"] == "rebuild" for i in out)


def test_design_lines_empty_draft():
    assert reasoning.design_lines({}) == []


def test_audit_line_ok_and_flag():
    assert "✓" in reasoning.audit_line("set_volume", has_feedback=False)
    flagged = reasoning.audit_line("set_volume", has_feedback=True)
    assert "✓" not in flagged and "volume" in flagged.lower()


def test_analyze_lines_from_flags():
    analytics = {
        "global_metrics": {"avg_rir_trend": "falling"},
        "exercise_flags": {
            "Bench Press": {"flag": "progressing", "rir_trend": "stable"},
            "Squat": {"flag": "stalled", "rir_trend": "falling"},
        },
    }
    reasons = [i["reason"] for i in reasoning.analyze_lines(analytics)]
    assert all(i["milestone"] == "analyze" for i in reasoning.analyze_lines(analytics))
    assert any("1 lifts progressing" in r for r in reasons)
    assert any("stalled" in r for r in reasons)


def test_adjust_lines_fallback():
    out = reasoning.adjust_lines({"exercise_flags": {}})
    assert out and out[0]["milestone"] == "adjust"
