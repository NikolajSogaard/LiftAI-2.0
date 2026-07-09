from agent_system.generator import ProgramGenerator


class _StubAgent:
    """Writer/Critic/Editor stub: sets a draft, leaves state otherwise intact."""
    def __init__(self, draft=None):
        self.on_status = None
        self._draft = draft
    def __call__(self, state):
        if self._draft is not None:
            state["draft"] = self._draft
        return state


def test_week1_emits_goals_and_design():
    draft = {"level": "intermediate",
             "weekly_program": {"Upper": [{"name": "Bench Press", "sets": 4, "reps": "6-8"}],
                                "Lower": [{"name": "Squat", "sets": 4, "reps": "5-8"}]}}
    gen = ProgramGenerator(writer=_StubAgent(draft), critic=_StubAgent(), editor=_StubAgent())
    captured = []
    gen.on_status = captured.append
    gen.create_program("Experience Level: Intermediate\nPrimary Goal: Hypertrophy")
    ms = [m.get("milestone") for m in captured if m.get("milestone")]
    assert "goals" in ms and "split" in ms and "exercises" in ms and "intensity" in ms
    reasons = [m["reason"] for m in captured if m.get("reason")]
    assert any("Experience Level: Intermediate" in r for r in reasons)
    assert any("Bench Press" in r for r in reasons)
