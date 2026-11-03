import asyncio

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.skills import SkillRegistry
from app.tools import ToolRegistry


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int = Field(ge=1, le=10)


def test_tool_registry_validates_arguments_and_permissions():
    tools = ToolRegistry()
    tools.register("double", "Double a number", Args, lambda value: value * 2)
    assert asyncio.run(tools.call("double", {"value": 4})) == 8
    with pytest.raises(ValueError):
        asyncio.run(tools.call("double", {"value": 99}))
    with pytest.raises(PermissionError):
        asyncio.run(tools.call("double", {"value": 4}, role="viewer"))


def test_material_skill_matches_domain_query():
    registry = SkillRegistry("skills")
    skills = registry.select("分析金属复合材料的批次良率和交付")
    assert skills
    assert skills[0].name == "materials-operations"
    assert "unit" in skills[0].instructions
