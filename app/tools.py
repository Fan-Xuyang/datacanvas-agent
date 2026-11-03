"""Typed, bounded runtime for tools available to the data Agent."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[..., Any]
    roles: frozenset[str]
    timeout_seconds: float


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name,
        description,
        args_model,
        handler,
        roles=("analyst", "admin"),
        timeout_seconds=20,
    ):
        if name in self._tools:
            raise ValueError(f"Tool 已注册：{name}")
        self._tools[name] = Tool(
            name, description, args_model, handler, frozenset(roles), timeout_seconds
        )

    def describe(self, role="analyst"):
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.args_model.model_json_schema(),
            }
            for tool in self._tools.values()
            if role in tool.roles
        ]

    async def call(self, name: str, arguments: dict, role="analyst"):
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError("未知工具。")
        if role not in tool.roles:
            raise PermissionError("当前角色无权调用该工具。")
        args = tool.args_model.model_validate(arguments)
        result = tool.handler(**args.model_dump())
        if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
            result = await asyncio.wait_for(result, timeout=tool.timeout_seconds)
        return result


class AnalysisQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str
    sql: str


def build_registry(root):
    from .data import execute

    registry = ToolRegistry()

    async def run_query(dataset_id, sql):
        if not re.fullmatch(r"[a-f0-9]{32}", dataset_id):
            raise ValueError("数据集标识无效。")
        return await execute(Path(root) / f"{dataset_id}.duckdb", sql)

    registry.register(
        "execute_readonly_sql",
        "Run a validated, bounded read-only query on the selected dataset.",
        AnalysisQuery,
        run_query,
        timeout_seconds=15,
    )
    return registry
