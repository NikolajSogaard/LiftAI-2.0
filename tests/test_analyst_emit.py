from agent_system.agents.analyst import Analyst


def test_analyst_emit_supports_milestone():
    captured = []
    a = Analyst(model=lambda p: "{}")
    a.on_status = captured.append
    a._emit(milestone="analyze", reason="Reviewing your logged sets")
    assert captured == [{"step": "analyst", "milestone": "analyze",
                         "reason": "Reviewing your logged sets"}]
