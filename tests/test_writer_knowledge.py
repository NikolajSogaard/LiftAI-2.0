from agent_system.agents import writer as writer_mod
from agent_system.agents.writer import Writer


def test_initial_write_injects_subject_knowledge(monkeypatch):
    captured = {}

    def fake_model(prompt):
        captured["prompt"] = prompt
        return {"weekly_program": {"Day 1": []}}

    monkeypatch.setattr(writer_mod, "get_subject_context",
                        lambda subjects: f"[KB:{','.join(subjects)}]")

    w = Writer(model=fake_model, role={"role": "system", "content": "ROLE"},
               structure="STRUCT", task="Make a program for {} using {}",
               writer_type="initial")
    w.write({"user-input": "beginner, 3 days, hypertrophy"})

    assert "[KB:" in captured["prompt"]            # brain text reached the prompt
    assert "effort" in captured["prompt"]          # effort subject was requested


def test_initial_write_injects_example_program(monkeypatch):
    captured = {}

    def fake_model(prompt):
        captured["prompt"] = prompt
        return {"weekly_program": {"Day 1": []}}

    monkeypatch.setattr(writer_mod, "get_subject_context",
                        lambda subjects: "")
    monkeypatch.setattr(writer_mod, "get_example_programs",
                        lambda user_input: "[EXAMPLE_PROGRAM]")

    w = Writer(model=fake_model, role={"role": "system", "content": "ROLE"},
               structure="STRUCT", task="Make a program for {} using {}",
               writer_type="initial")
    w.write({"user-input": "beginner, 3 days, hypertrophy"})

    assert "[EXAMPLE_PROGRAM]" in captured["prompt"]
