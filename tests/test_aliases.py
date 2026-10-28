from actforge.util.config import resolve_goal_object_id


def test_resolve_goal_from_chinese_alias():
    aliases = {"can_cola": ["易拉罐", "可乐罐", "can"], "cup_white": ["杯子", "cup"]}
    assert resolve_goal_object_id("把桌上的易拉罐拿起来", aliases, "can_cola") == "can_cola"
    assert resolve_goal_object_id("请拿起白杯子", aliases, "can_cola") == "cup_white"
    assert resolve_goal_object_id("随便做点什么", aliases, "can_cola") == "can_cola"
