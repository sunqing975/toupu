"""工具定义必须是合法 JSON Schema，不能把内部 required 布尔标记发给模型。"""

from jsonschema import Draft202012Validator

from app.agent.skills import SKILLS


def test_all_tool_parameters_are_valid_json_schema():
    for tool in SKILLS.values():
        schema = tool.tool_schema()["function"]["parameters"]
        Draft202012Validator.check_schema(schema)
        for prop in schema["properties"].values():
            assert "required" not in prop


def test_proposal_required_fields_remain_at_object_level():
    schema = SKILLS["create_draft_proposal"].tool_schema()["function"]["parameters"]
    assert schema["required"] == ["payload"]
    assert "required" not in schema["properties"]["payload"]
