import asyncio

import httpx

from app.agent import DataAgent
from shared.api import base_app


def test_bearer_auth_scopes_tasks_and_audit_by_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv("DATACANVAS_AUTH_REQUIRED", "true")
    monkeypatch.setenv(
        "DATACANVAS_TOKENS",
        '{"alpha-secret":{"tenant_id":"alpha","role":"admin","sub":"alice"},'
        '"beta-secret":{"tenant_id":"beta","role":"viewer","sub":"bob"}}',
    )
    app, store, _ = base_app(
        tmp_path,
        "data",
        DataAgent,
        lambda request, db, tenant: {"tenant_id": tenant},
    )
    alpha_task = store.create("data", "alpha question", "demo", {}, "alpha")
    beta_task = store.create("data", "beta question", "demo", {}, "beta")

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            denied = await client.get("/api/tasks")
            alpha = await client.get(
                "/api/tasks", headers={"Authorization": "Bearer alpha-secret"}
            )
            hidden = await client.get(
                f"/api/tasks/{beta_task}",
                headers={"Authorization": "Bearer alpha-secret"},
            )
            viewer_write = await client.delete(
                "/api/knowledge/missing",
                headers={"Authorization": "Bearer beta-secret"},
            )
            alpha_audit = await client.get(
                "/api/audit", headers={"Authorization": "Bearer alpha-secret"}
            )
            return denied, alpha, hidden, viewer_write, alpha_audit

    denied, alpha, hidden, viewer_write, alpha_audit = asyncio.run(exercise())
    assert denied.status_code == 401
    assert [task["id"] for task in alpha.json()] == [alpha_task]
    assert hidden.status_code == 404
    assert viewer_write.status_code == 403
    assert alpha_audit.status_code == 200
    assert all(row["tenant_id"] == "alpha" for row in alpha_audit.json())
