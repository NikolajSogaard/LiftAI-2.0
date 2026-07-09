"""Integration test for the per-muscle volume panel via the index route."""
from app import app


def _seed(client):
    program = {
        "Day 1": [
            {"name": "Back Squat", "sets": 4, "reps": "6-8", "target_rir": "2", "rest": "3m",
             "cues": "", "patterns": ["Lower_anterior_chain", "Lower_posterior_chain"], "group": None},
        ]
    }
    with client.session_transaction() as sess:
        sess["program"] = program
        sess["raw_program"] = {"formatted": {"weekly_program": program, "level": "intermediate"}}
        sess["current_week"] = 1
        sess["all_programs"] = [{"week": 1, "mesocycle": 1, "program": program, "feedback": {}}]
        sess["set_log"] = {}


def test_index_renders_muscle_volume():
    client = app.test_client()
    _seed(client)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Quads" in body            # Lower_anterior_chain description
    assert "Volume by movement pattern" in body
