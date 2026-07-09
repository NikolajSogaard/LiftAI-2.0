from agent_system.agents.critic import Critic


def _critic():
    return Critic(model=lambda p: "None", role={"content": ""},
                  tasks={"progression": "{}\n{}\n{}"})


def test_process_emits_audit_ok():
    captured = []
    c = _critic()
    c.on_status = captured.append
    c._process_task_result("set_volume", None)
    audit = [m for m in captured if m.get("milestone") == "audit"]
    assert audit and "✓" in audit[0]["reason"]
    assert all("message" not in m for m in audit)


def test_process_emits_audit_flag():
    captured = []
    c = _critic()
    c.on_status = captured.append
    c._process_task_result("set_volume", "Chest is under-volumed, add 4 sets to hit the range.")
    audit = [m for m in captured if m.get("milestone") == "audit"]
    assert audit and "✓" not in audit[0]["reason"]
