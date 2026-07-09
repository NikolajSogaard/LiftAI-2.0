from agent_system.agents import critic as critic_mod
from agent_system.agents.critic import Critic


def test_aspect_maps_to_subject(monkeypatch):
    captured = {}

    def fake_model(prompt):
        captured["prompt"] = prompt
        return "None"

    monkeypatch.setattr(critic_mod, "get_subject_context",
                        lambda subjects: f"[KB:{','.join(subjects)}]")

    c = Critic(model=fake_model, role={"content": "ROLE"},
               tasks={"rir": "Critique {} for user {}"})
    c.run_single_critique("rir", {"draft": {"weekly_program": {}}, "user-input": "x"})

    assert "[KB:effort]" in captured["prompt"]     # rir dimension pulls the effort note
