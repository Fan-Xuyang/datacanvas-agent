import pytest

from app.mcp_client import configured_servers


def test_mcp_config_accepts_local_http_and_secure_remote(monkeypatch):
    monkeypatch.setenv(
        "MCP_SERVERS",
        '[{"name":"local","url":"http://127.0.0.1:8202/mcp"},'
        '{"name":"research","url":"https://mcp.example.org/mcp"}]',
    )
    assert configured_servers() == {
        "local": {
            "url": "http://127.0.0.1:8202/mcp",
            "tenant_ids": ["local"],
        },
        "research": {
            "url": "https://mcp.example.org/mcp",
            "tenant_ids": ["local"],
        },
    }


@pytest.mark.parametrize(
    "value",
    [
        '{"name":"wrong-shape"}',
        '[{"name":"remote","url":"http://10.0.0.4/mcp"}]',
        '[{"name":"remote","url":"https://user:pass@example.org/mcp"}]',
        '[{"name":"bad name","url":"https://mcp.example.org"}]',
    ],
)
def test_mcp_config_rejects_unsafe_or_invalid_entries(monkeypatch, value):
    monkeypatch.setenv("MCP_SERVERS", value)
    with pytest.raises(ValueError):
        configured_servers()


def test_shared_mcp_config_requires_tenant_allowlist(monkeypatch):
    monkeypatch.setenv("DATACANVAS_AUTH_REQUIRED", "true")
    monkeypatch.setenv(
        "MCP_SERVERS", '[{"name":"remote","url":"https://mcp.example.org"}]'
    )
    with pytest.raises(ValueError, match="tenant_ids"):
        configured_servers()
