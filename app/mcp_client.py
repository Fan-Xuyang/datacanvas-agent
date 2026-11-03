"""Configured MCP client for trusted, explicitly read-only external tools."""

from contextlib import asynccontextmanager
import json
import os
import re
from urllib.parse import urlparse

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


def configured_servers():
    raw = os.getenv("MCP_SERVERS", "[]")
    try:
        configs = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("MCP_SERVERS 配置必须为 JSON 数组。") from exc
    if not isinstance(configs, list) or len(configs) > 20:
        raise ValueError("MCP_SERVERS 最多配置 20 个服务。")
    result = {}
    for config in configs:
        if not isinstance(config, dict):
            raise ValueError("MCP 服务配置格式无效。")
        name = config.get("name", "")
        url = config.get("url", "")
        tenants = config.get("tenant_ids", ["local"])
        if not isinstance(name, str) or not isinstance(url, str):
            raise ValueError("MCP 服务名称或 URL 无效。")
        parsed = urlparse(url)
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name)
            or parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("MCP 服务名称或 URL 无效。")
        if (
            not isinstance(tenants, list)
            or not tenants
            or any(
                not isinstance(tenant, str)
                or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", tenant)
                for tenant in tenants
            )
        ):
            raise ValueError("MCP 服务必须显式配置有效的 tenant_ids。")
        if (
            os.getenv("DATACANVAS_AUTH_REQUIRED", "false").lower() == "true"
            and "tenant_ids" not in config
        ):
            raise ValueError("共享部署的 MCP 服务必须显式限制 tenant_ids。")
        if parsed.scheme == "http" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("远程 MCP 服务必须使用 HTTPS。")
        if name in result:
            raise ValueError("MCP 服务名称不能重复。")
        result[name] = {"url": url, "tenant_ids": tenants}
    return result


def _token_env(name):
    return "MCP_SERVER_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper() + "_TOKEN"


@asynccontextmanager
async def connect(server_name, tenant_id="local"):
    servers = configured_servers()
    if server_name not in servers:
        raise ValueError("MCP 服务未配置。")
    if tenant_id not in servers[server_name]["tenant_ids"]:
        raise PermissionError("当前租户无权访问该 MCP 服务。")
    headers = (
        {"Authorization": "Bearer " + os.getenv(_token_env(server_name))}
        if os.getenv(_token_env(server_name))
        else {}
    )
    async with httpx2.AsyncClient(
        headers=headers,
        timeout=httpx2.Timeout(30.0, connect=5.0),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        async with streamable_http_client(
            servers[server_name]["url"], http_client=http_client
        ) as transport:
            async with Client(transport, read_timeout_seconds=30) as client:
                yield client


async def list_readonly_tools(server_name, tenant_id="local"):
    async with connect(server_name, tenant_id) as client:
        result = await client.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "read_only": bool(
                    tool.annotations and tool.annotations.read_only_hint is True
                ),
            }
            for tool in result.tools
        ]


async def call_readonly_tool(server_name, tool_name, arguments, tenant_id="local"):
    if len(json.dumps(arguments, ensure_ascii=False)) > 16_000:
        raise ValueError("MCP 工具参数不能超过 16 KB。")
    async with connect(server_name, tenant_id) as client:
        listing = await client.list_tools()
        tool = next((item for item in listing.tools if item.name == tool_name), None)
        if tool is None:
            raise ValueError("MCP 工具不存在。")
        if not tool.annotations or tool.annotations.read_only_hint is not True:
            raise PermissionError("仅允许调用明确标记为只读的 MCP 工具。")
        result = await client.call_tool(tool_name, arguments)
        payload = {
            "is_error": result.is_error,
            "structured_content": result.structured_content,
            "content": [item.model_dump(mode="json") for item in result.content[:20]],
        }
        if len(json.dumps(payload, ensure_ascii=False, default=str)) > 100_000:
            raise ValueError("MCP 返回内容超过 100 KB。")
        return payload
