from agent_system.agents import analyst as analyst_mod
from agent_system.agents.analyst import Analyst


def test_deload_pulls_deload_subjects(monkeypatch):
    monkeypatch.setattr(analyst_mod, "get_subject_context",
                        lambda subjects: f"[KB:{','.join(subjects)}]")
    a = Analyst(model=lambda p: "{}")
    out = a._get_knowledge_context("deload", {})
    assert "deload-and-fatigue" in out
