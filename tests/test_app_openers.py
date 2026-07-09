import app as app_module
from agent_system import reasoning


def test_reasoning_plans_importable_from_app():
    assert reasoning.WEEK1_PLAN[0]["key"] == "goals"
    assert reasoning.progression_plan("normal")[0]["key"] == "analyze"
    assert reasoning.continuation_plan("deload")[0]["key"] == "rebuild"
    assert hasattr(app_module, "reasoning")
