"""Tests for agent_system.analytics — pure-Python training metrics."""
import pytest
from agent_system.analytics import compute_exercise_metrics


def _make_week(week, exercises_by_day):
    """Helper: build a weekly record with feedback data."""
    feedback = {}
    program = {}
    for day, exercises in exercises_by_day.items():
        feedback[day] = []
        program[day] = []
        for ex in exercises:
            program[day].append({
                "name": ex["name"],
                "sets": len(ex["sets_data"]),
                "reps": ex.get("reps", "8-12"),
                "target_rir": ex.get("target_rir", "2-3"),
            })
            feedback[day].append({
                "name": ex["name"],
                "sets_data": ex["sets_data"],
                "overall_feedback": "",
            })
    return {"week": week, "program": program, "feedback": feedback}


class TestComputeExerciseMetrics:
    def test_progressing_exercise(self):
        """Weight increases each week → stagnation_weeks=0, flag='progressing'."""
        weeks = [
            _make_week(1, {"Day 1": [{"name": "Bench Press", "sets_data": [
                {"weight": "70", "reps": "8", "actual_rir": "3"}
            ]}]}),
            _make_week(2, {"Day 1": [{"name": "Bench Press", "sets_data": [
                {"weight": "72.5", "reps": "8", "actual_rir": "3"}
            ]}]}),
            _make_week(3, {"Day 1": [{"name": "Bench Press", "sets_data": [
                {"weight": "75", "reps": "8", "actual_rir": "3"}
            ]}]}),
        ]
        metrics = compute_exercise_metrics(weeks)
        bench = metrics["Bench Press"]
        assert bench["stagnation_weeks"] == 0
        assert bench["flag"] == "progressing"

    def test_stalled_exercise(self):
        """Same weight and reps for 3 weeks → stagnation_weeks=2, flag='stalled'."""
        weeks = [
            _make_week(1, {"Day 1": [{"name": "RDL", "sets_data": [
                {"weight": "80", "reps": "10", "actual_rir": "2"}
            ]}]}),
            _make_week(2, {"Day 1": [{"name": "RDL", "sets_data": [
                {"weight": "80", "reps": "10", "actual_rir": "2"}
            ]}]}),
            _make_week(3, {"Day 1": [{"name": "RDL", "sets_data": [
                {"weight": "80", "reps": "10", "actual_rir": "1"}
            ]}]}),
        ]
        metrics = compute_exercise_metrics(weeks)
        rdl = metrics["RDL"]
        assert rdl["stagnation_weeks"] == 2
        assert rdl["flag"] == "stalled"

    def test_rep_increase_counts_as_progress(self):
        """Same weight but more reps → not stalled."""
        weeks = [
            _make_week(1, {"Day 1": [{"name": "Squat", "sets_data": [
                {"weight": "100", "reps": "5", "actual_rir": "2"}
            ]}]}),
            _make_week(2, {"Day 1": [{"name": "Squat", "sets_data": [
                {"weight": "100", "reps": "6", "actual_rir": "2"}
            ]}]}),
        ]
        metrics = compute_exercise_metrics(weeks)
        assert metrics["Squat"]["stagnation_weeks"] == 0
        assert metrics["Squat"]["flag"] == "progressing"

    def test_missing_feedback_skipped(self):
        """Weeks without feedback data are gracefully skipped."""
        weeks = [
            _make_week(1, {"Day 1": [{"name": "Bench Press", "sets_data": [
                {"weight": "70", "reps": "8", "actual_rir": "3"}
            ]}]}),
            {"week": 2, "program": {}, "feedback": {}},  # no data
        ]
        metrics = compute_exercise_metrics(weeks)
        assert metrics["Bench Press"]["stagnation_weeks"] == 0


from agent_system.analytics import compute_global_metrics, decide_review_type


class TestComputeGlobalMetrics:
    def test_falling_rir_trend(self):
        """Falling RIR across weeks = fatigue signal."""
        exercise_metrics = {
            "Bench Press": {"stagnation_weeks": 0, "rir_trend": "falling", "flag": "progressing"},
            "Squat": {"stagnation_weeks": 0, "rir_trend": "falling", "flag": "progressing"},
        }
        weeks = [
            _make_week(1, {"Day 1": [
                {"name": "Bench Press", "sets_data": [{"weight": "70", "reps": "8", "actual_rir": "4"}]},
                {"name": "Squat", "sets_data": [{"weight": "100", "reps": "5", "actual_rir": "4"}]},
            ]}),
            _make_week(2, {"Day 1": [
                {"name": "Bench Press", "sets_data": [{"weight": "72.5", "reps": "8", "actual_rir": "2"}]},
                {"name": "Squat", "sets_data": [{"weight": "102.5", "reps": "5", "actual_rir": "1"}]},
            ]}),
        ]
        gm = compute_global_metrics(exercise_metrics, weeks)
        assert gm["avg_rir_trend"] == "falling"
        assert 0.0 <= gm["fatigue_score"] <= 1.0

    def test_no_stalls_low_fatigue(self):
        exercise_metrics = {
            "Bench Press": {"stagnation_weeks": 0, "rir_trend": "stable", "flag": "progressing"},
        }
        weeks = [
            _make_week(1, {"Day 1": [
                {"name": "Bench Press", "sets_data": [{"weight": "70", "reps": "8", "actual_rir": "3"}]},
            ]}),
        ]
        gm = compute_global_metrics(exercise_metrics, weeks)
        assert gm["fatigue_score"] < 0.7
        assert gm["stalled_exercise_ratio"] == 0.0


class TestDecideReviewType:
    def test_normal_week(self):
        global_metrics = {
            "avg_rir_trend": "stable",
            "fatigue_score": 0.2,
            "stalled_exercise_ratio": 0.0,
            "mesocycle_position": 0.5,
        }
        result = decide_review_type(global_metrics, week_in_mesocycle=2, mesocycle_length=4)
        assert result["review_type"] == "normal"
        assert result["triggers"] == []

    def test_end_of_mesocycle(self):
        global_metrics = {
            "avg_rir_trend": "stable",
            "fatigue_score": 0.3,
            "stalled_exercise_ratio": 0.1,
            "mesocycle_position": 1.0,
        }
        result = decide_review_type(global_metrics, week_in_mesocycle=4, mesocycle_length=4)
        assert result["review_type"] == "mesocycle_review"
        assert any("end of mesocycle" in t.lower() for t in result["triggers"])

    def test_high_fatigue_triggers_deload(self):
        global_metrics = {
            "avg_rir_trend": "falling",
            "fatigue_score": 0.8,
            "stalled_exercise_ratio": 0.2,
            "mesocycle_position": 0.5,
        }
        result = decide_review_type(global_metrics, week_in_mesocycle=2, mesocycle_length=4)
        assert result["review_type"] == "deload"

    def test_high_stall_ratio_triggers_review(self):
        global_metrics = {
            "avg_rir_trend": "stable",
            "fatigue_score": 0.3,
            "stalled_exercise_ratio": 0.6,
            "mesocycle_position": 0.75,
        }
        result = decide_review_type(global_metrics, week_in_mesocycle=3, mesocycle_length=4)
        assert result["review_type"] == "mesocycle_review"

    def test_deload_takes_priority_over_review(self):
        """When both fatigue and stall thresholds are exceeded, deload wins."""
        global_metrics = {
            "avg_rir_trend": "falling",
            "fatigue_score": 0.85,
            "stalled_exercise_ratio": 0.6,
            "mesocycle_position": 1.0,
        }
        result = decide_review_type(global_metrics, week_in_mesocycle=4, mesocycle_length=4)
        assert result["review_type"] == "deload"


from agent_system.analytics import analyze_training_history


class TestAnalyzeTrainingHistory:
    def test_full_pipeline_normal(self):
        """3 weeks of progressing data, mid-mesocycle → normal."""
        weeks = [
            _make_week(w, {"Day 1": [{"name": "Bench Press", "sets_data": [
                {"weight": str(70 + w * 2.5), "reps": "8", "actual_rir": "3"}
            ]}]})
            for w in range(1, 4)
        ]
        result = analyze_training_history(weeks, week_in_mesocycle=3, mesocycle_length=4)
        assert result["review_type"] == "normal"
        assert "Bench Press" in result["exercise_flags"]
        assert result["exercise_flags"]["Bench Press"]["flag"] == "progressing"
        assert "global_metrics" in result

    def test_full_pipeline_end_of_mesocycle(self):
        """4 weeks, at end of mesocycle → mesocycle_review."""
        weeks = [
            _make_week(w, {"Day 1": [{"name": "Bench Press", "sets_data": [
                {"weight": str(70 + w * 2.5), "reps": "8", "actual_rir": "3"}
            ]}]})
            for w in range(1, 5)
        ]
        result = analyze_training_history(weeks, week_in_mesocycle=4, mesocycle_length=4)
        assert result["review_type"] == "mesocycle_review"


# ── Volume / progress / superset feature tests (2026-06-14) ──────────────────

def test_volume_guidelines_centralized():
    from config import VOLUME_GUIDELINES, MOVEMENT_PATTERNS
    assert set(MOVEMENT_PATTERNS) == {
        "Upper_horizontal_push", "Upper_horizontal_pull", "Upper_vertical_push",
        "Upper_vertical_pull", "Lower_anterior_chain", "Lower_posterior_chain",
    }
    for level in ("beginner", "intermediate", "advanced"):
        assert set(VOLUME_GUIDELINES[level]) == set(MOVEMENT_PATTERNS)
        for v in VOLUME_GUIDELINES[level].values():
            assert v["min"] <= v["max"] and v["description"]


def test_compute_muscle_volume_tagged_and_status():
    from agent_system.analytics import compute_muscle_volume
    program = {
        "Day 1": [
            {"name": "Back Squat", "sets": 4, "patterns": ["Lower_anterior_chain", "Lower_posterior_chain"]},
            {"name": "Bench Press", "sets": 3, "patterns": ["Upper_horizontal_push"]},
        ],
    }
    out = {row["key"]: row for row in compute_muscle_volume(program, "intermediate")}
    assert len(out) == 6                                  # always all six patterns
    assert out["Lower_anterior_chain"]["sets"] == 4       # compound credits both
    assert out["Lower_posterior_chain"]["sets"] == 4
    assert out["Upper_horizontal_push"]["sets"] == 3
    assert out["Upper_horizontal_push"]["status"] == "under"   # 3 < min 10
    assert out["Upper_vertical_pull"]["status"] == "under"     # 0 sets
    assert out["Upper_horizontal_push"]["description"] == "Chest/pressing"


def test_compute_muscle_volume_keyword_fallback_when_untagged():
    from agent_system.analytics import compute_muscle_volume
    program = {"Day 1": [{"name": "Romanian Deadlift", "sets": 12}]}  # no patterns
    out = {row["key"]: row for row in compute_muscle_volume(program, "intermediate")}
    assert out["Lower_posterior_chain"]["sets"] == 12     # guessed from "deadlift"/"romanian"
    assert out["Lower_posterior_chain"]["status"] == "in_range"


def test_epley_e1rm():
    from agent_system.analytics import _epley_e1rm
    assert _epley_e1rm(100, 0) == 100.0
    assert _epley_e1rm(100, 10) == round(100 * (1 + 10 / 30), 1)


def test_compute_exercise_series():
    from agent_system.analytics import compute_exercise_series
    def sd(w, r): return {"weight": w, "reps": r, "actual_rir": "2"}
    programs = [
        {"week": 1, "feedback": {"Day 1": [{"name": "Back Squat", "sets_data": [sd("100", "8"), sd("100", "8")]}]}},
        {"week": 2, "feedback": {"Day 1": [{"name": "Back Squat", "sets_data": [sd("105", "7")]}]}},
        {"week": 3, "feedback": {"Day 1": [{"name": "Back Squat", "sets_data": []}]}},  # nothing logged
    ]
    out = compute_exercise_series(programs)
    rows = out["Back Squat"]["rows"]
    assert [r["week"] for r in rows] == [1, 2]            # week 3 skipped (no logged set)
    assert rows[0]["weight"] == 100.0 and rows[0]["reps"] == 8.0
    assert rows[1]["e1rm"] == round(105 * (1 + 7 / 30), 1)
    assert out["Back Squat"]["delta"] == 5.0              # 105 - 100


def test_editor_preserves_new_fields():
    from agent_system.agents.editor import Editor
    draft = {
        "level": "advanced",
        "weekly_program": {
            "Day 1": [
                {"name": "Bench Press", "sets": 3, "reps": "6-8",
                 "patterns": ["Upper_horizontal_push"], "group": "A"},
            ]
        },
    }
    formatted = Editor().format_program({"draft": draft})
    ex = formatted["weekly_program"]["Day 1"][0]
    assert ex["patterns"] == ["Upper_horizontal_push"]
    assert ex["group"] == "A"
    assert formatted["level"] == "advanced"


from agent_system.analytics import compute_weekly_volume, compute_last_time


class TestComputeWeeklyVolume:
    def test_counts_prescribed_and_logged_sets(self):
        weeks = [
            _make_week(1, {"Day 1": [
                {"name": "Bench Press", "sets_data": [
                    {"weight": "70", "reps": "8", "actual_rir": "2"},
                    {"weight": "70", "reps": "8", "actual_rir": "1"},
                ]},
                {"name": "Row", "sets_data": [
                    {"weight": "", "reps": "", "actual_rir": ""},  # not logged
                ]},
            ]}),
        ]
        vol = compute_weekly_volume(weeks)
        assert len(vol) == 1
        assert vol[0]["week"] == 1
        assert vol[0]["prescribed_sets"] == 3   # 2 bench + 1 row
        assert vol[0]["logged_sets"] == 2       # only the 2 bench sets have weight

    def test_week_without_feedback_has_zero_logged(self):
        weeks = [{"week": 1, "program": {"Day 1": [{"name": "Squat", "sets": 4}]}, "feedback": {}}]
        vol = compute_weekly_volume(weeks)
        assert vol[0]["prescribed_sets"] == 4
        assert vol[0]["logged_sets"] == 0

    def test_sorted_by_week(self):
        weeks = [
            _make_week(2, {"Day 1": [{"name": "Squat", "sets_data": [{"weight": "100", "reps": "5", "actual_rir": "2"}]}]}),
            _make_week(1, {"Day 1": [{"name": "Squat", "sets_data": [{"weight": "95", "reps": "5", "actual_rir": "2"}]}]}),
        ]
        vol = compute_weekly_volume(weeks)
        assert [v["week"] for v in vol] == [1, 2]


class TestComputeLastTime:
    def test_returns_prior_weeks_top_set(self):
        weeks = [
            _make_week(1, {"Day 1": [{"name": "Bench Press", "sets_data": [
                {"weight": "70", "reps": "8", "actual_rir": "2"},
                {"weight": "80", "reps": "6", "actual_rir": "1"},  # top set
            ]}]}),
            _make_week(2, {"Day 1": [{"name": "Bench Press", "sets_data": [
                {"weight": "82.5", "reps": "6", "actual_rir": "1"},
            ]}]}),
        ]
        lt = compute_last_time(weeks)
        assert lt["2|Bench Press"] == {"week": 1, "weight": "80", "reps": "6", "actual_rir": "1"}
        assert "1|Bench Press" not in lt   # no prior data for week 1

    def test_uses_most_recent_prior_week(self):
        weeks = [
            _make_week(1, {"Day 1": [{"name": "Squat", "sets_data": [{"weight": "100", "reps": "5", "actual_rir": "2"}]}]}),
            _make_week(2, {"Day 1": [{"name": "Squat", "sets_data": [{"weight": "105", "reps": "5", "actual_rir": "2"}]}]}),
            _make_week(3, {"Day 1": [{"name": "Squat", "sets_data": [{"weight": "110", "reps": "5", "actual_rir": "2"}]}]}),
        ]
        lt = compute_last_time(weeks)
        assert lt["3|Squat"]["week"] == 2
        assert lt["3|Squat"]["weight"] == "105"

    def test_skips_exercise_with_no_logged_weight(self):
        weeks = [
            _make_week(1, {"Day 1": [{"name": "Curl", "sets_data": [{"weight": "", "reps": "", "actual_rir": ""}]}]}),
            _make_week(2, {"Day 1": [{"name": "Curl", "sets_data": [{"weight": "15", "reps": "12", "actual_rir": "1"}]}]}),
        ]
        lt = compute_last_time(weeks)
        assert "2|Curl" not in lt   # week 1 had no usable data
