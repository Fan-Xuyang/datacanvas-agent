import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from dotenv import load_dotenv
from .model import api_key, configured
from .store import Store

log = logging.getLogger(__name__)


class TaskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["demo", "live"] = "demo"
    dataset_id: str | None = None
    metrics: dict[str, str] = Field(default_factory=dict)


class Approval(BaseModel):
    digest: str = Field(min_length=64, max_length=64)
    approve: bool


def base_app(project_dir, kind, agent_factory, prepare):
    project_dir = Path(project_dir)
    load_dotenv(project_dir / ".env", override=False)
    root = Path(os.getenv("APP_DATA_DIR", str(project_dir / "data")))
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root / "state.sqlite3")
    agent = agent_factory(store, root)
    active = {}

    async def work(tid):
        try:
            await agent.run(tid)
        except asyncio.CancelledError:
            task = store.get(tid)
            if task["status"] == "running":
                store.checkpoint(
                    tid,
                    "interrupted",
                    task["state"],
                    "interrupted",
                    {"message": "任务已中断，可从已保存阶段恢复"},
                )
            raise
        except Exception as exc:
            log.exception("Task failed: %s", tid)
            task = store.get(tid)
            # Provider errors can expose credentials; only return safe validation
            # errors to clients.
            message = (
                str(exc)[:500]
                if isinstance(exc, ValueError)
                else "执行失败，请检查本地服务日志或模型配置。"
            )
            store.checkpoint(
                tid, "failed", task["state"], "failed", {"message": message}
            )
        finally:
            active.pop(tid, None)

    def launch(tid):
        active[tid] = asyncio.create_task(work(tid))

    @asynccontextmanager
    async def lifespan(app):
        store.recover(kind)
        yield
        jobs = list(active.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

    app = FastAPI(
        title="DataCanvas" if kind == "data" else "FlowPilot", lifespan=lifespan
    )
    app.state.store = store
    app.state.root = root
    app.state.agent = agent

    @app.middleware("http")
    async def identity_and_audit(request, call_next):
        path = request.url.path
        request.state.tenant_id = "local"
        request.state.actor = "local-user"
        request.state.role = "admin"
        if path.startswith("/api/") and path != "/api/health":
            raw_tokens = os.getenv("DATACANVAS_TOKENS", "")
            try:
                tokens = json.loads(raw_tokens) if raw_tokens else {}
            except json.JSONDecodeError:
                store.audit(
                    "local", "auth-config", "system", request.method, path, 503, 0
                )
                return Response("身份配置无效。", status_code=503)
            if not isinstance(tokens, dict) or any(
                not isinstance(token, str) or not isinstance(identity, dict)
                for token, identity in tokens.items()
            ):
                store.audit(
                    "local", "auth-config", "system", request.method, path, 503, 0
                )
                return Response("身份配置无效。", status_code=503)
            required = os.getenv("DATACANVAS_AUTH_REQUIRED", "false").lower() == "true"
            if required and not tokens:
                store.audit(
                    "local", "auth-config", "system", request.method, path, 503, 0
                )
                return Response("身份验证尚未配置。", status_code=503)
            auth = request.headers.get("authorization", "")
            supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            identity = next(
                (
                    value
                    for token, value in tokens.items()
                    if supplied and secrets.compare_digest(supplied, token)
                ),
                None,
            )
            if required and identity is None:
                store.audit(
                    "local", "anonymous", "anonymous", request.method, path, 401, 0
                )
                return Response("需要有效的 Bearer Token。", status_code=401)
            if identity is not None:
                role = identity.get("role", "")
                tenant_id = identity.get("tenant_id", "")
                if (
                    role not in {"admin", "analyst", "viewer"}
                    or not isinstance(tenant_id, str)
                    or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", tenant_id)
                    or not isinstance(identity.get("sub", "token-user"), str)
                ):
                    store.audit(
                        "local", "auth-config", "system", request.method, path, 503, 0
                    )
                    return Response("身份授权配置无效。", status_code=503)
                request.state.actor = identity.get("sub", "token-user")[:100]
                request.state.role = role
                request.state.tenant_id = tenant_id[:80]
                if (
                    request.method in {"POST", "PUT", "PATCH", "DELETE"}
                    and role == "viewer"
                ):
                    store.audit(
                        tenant_id,
                        identity.get("sub", "token-user")[:100],
                        role,
                        request.method,
                        path,
                        403,
                        0,
                    )
                    return Response("当前角色为只读。", status_code=403)
                if path == "/api/audit" and role != "admin":
                    store.audit(
                        tenant_id,
                        identity.get("sub", "token-user")[:100],
                        role,
                        request.method,
                        path,
                        403,
                        0,
                    )
                    return Response("只有管理员可以查看审计记录。", status_code=403)
        started = time.monotonic()
        response = await call_next(request)
        if path.startswith("/api/") and path != "/api/health":
            store.audit(
                request.state.tenant_id,
                request.state.actor,
                request.state.role,
                request.method,
                path,
                response.status_code,
                round((time.monotonic() - started) * 1000),
            )
        return response

    def get(tid, tenant_id):
        try:
            task = store.get(tid, tenant_id)
        except KeyError:
            raise HTTPException(404, "任务不存在。")
        if task["kind"] != kind:
            raise HTTPException(404, "任务不存在。")
        return task

    @app.get("/api/health")
    async def health():
        return {
            "kind": kind,
            "live_configured": configured(),
            "provider": os.getenv("AI_PROVIDER", "openai-compatible"),
            "model": os.getenv("AI_MODEL", "deepseek-chat"),
            "auth_required": os.getenv("DATACANVAS_AUTH_REQUIRED", "false").lower()
            == "true",
            "embedding_configured": bool(
                (os.getenv("AI_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY"))
                and os.getenv("AI_EMBEDDING_MODEL")
            ),
            "status": "ok",
        }

    @app.get("/api/tasks")
    async def tasks(request: Request):
        return store.tasks(kind, request.state.tenant_id)

    @app.get("/api/metrics")
    async def metrics(request: Request):
        return store.metrics(kind, request.state.tenant_id)

    @app.post("/api/tasks", status_code=202)
    async def create(body: TaskRequest, request: Request):
        if not body.query.strip():
            raise HTTPException(422, "请输入具体问题。")
        if body.mode == "live" and not api_key():
            raise HTTPException(400, "请在本地 .env 配置模型接口。")
        if sum(1 for t in active.values() if not t.done()) >= 2:
            raise HTTPException(429, "最多同时执行两个任务。")
        state = prepare(body, store, request.state.tenant_id)
        tid = store.create(
            kind, body.query.strip(), body.mode, state, request.state.tenant_id
        )
        if not store.claim(tid, ["queued"]):
            raise HTTPException(409, "任务状态冲突。")
        launch(tid)
        return {"id": tid}

    @app.get("/api/tasks/{tid}")
    async def detail(tid: str, request: Request):
        return {**get(tid, request.state.tenant_id), "events": store.events(tid)}

    @app.get("/api/tasks/{tid}/events")
    async def events(tid: str, request: Request, after: int = 0):
        get(tid, request.state.tenant_id)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "事件游标无效。")

        async def stream():
            nonlocal cursor
            idle = 0
            while not await request.is_disconnected():
                batch = store.events(tid, cursor)
                for event in batch:
                    cursor = event["seq"]
                    yield (
                        "id: "
                        + str(cursor)
                        + "\nevent: trace\ndata: "
                        + json.dumps(event, ensure_ascii=False)
                        + "\n\n"
                    )
                if (
                    get(tid, request.state.tenant_id)["status"]
                    not in {"running", "queued"}
                    and not batch
                ):
                    yield "event: settled\ndata: {}\n\n"
                    break
                idle += 1
                if idle % 20 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/tasks/{tid}/resume")
    async def resume(tid: str, request: Request):
        get(tid, request.state.tenant_id)
        if not store.claim(tid, ["interrupted"]):
            raise HTTPException(409, "只有中断任务可以恢复。")
        store.event(tid, "resume", {"message": "从持久化状态继续执行"})
        launch(tid)
        return {"id": tid}

    @app.post("/api/tasks/{tid}/cancel")
    async def cancel(tid: str, request: Request):
        task = get(tid, request.state.tenant_id)
        if task["status"] not in {
            "queued",
            "running",
            "awaiting_approval",
            "interrupted",
        }:
            raise HTTPException(409, "当前任务不能取消。")
        store.checkpoint(
            tid, "cancelled", task["state"], "cancelled", {"message": "任务已取消"}
        )
        job = active.get(tid)
        if job:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        return {"status": "cancelled"}

    @app.post("/api/tasks/{tid}/approve")
    async def approve(tid: str, approval: Approval, request: Request):
        task = get(tid, request.state.tenant_id)
        if kind != "browser" or task["status"] != "awaiting_approval":
            raise HTTPException(409, "任务没有待确认操作。")
        state = task["state"]
        if approval.digest != state.get("digest"):
            raise HTTPException(409, "确认内容与待执行内容不一致。")
        if not store.claim(tid, ["awaiting_approval"]):
            raise HTTPException(409, "任务已被其他请求处理。")
        if not approval.approve:
            store.checkpoint(
                tid, "cancelled", state, "cancelled", {"message": "用户拒绝提交"}
            )
            return {"status": "cancelled"}
        state["approved"] = True
        store.checkpoint(
            tid,
            "running",
            state,
            "approved",
            {"message": "用户已确认当前内容", "digest": request.digest},
        )
        launch(tid)
        return {"status": "running"}

    @app.get("/api/tasks/{tid}/report")
    async def report(tid: str, request: Request):
        task = get(tid, request.state.tenant_id)
        text = task["state"].get("report")
        if not text:
            raise HTTPException(409, "报告尚未生成。")
        return Response(
            text,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{kind}-{tid[:8]}.md"'
            },
        )

    @app.get("/api/audit")
    async def audit(request: Request, limit: int = 100):
        if request.state.role != "admin":
            raise HTTPException(403, "只有管理员可以查看审计记录。")
        return store.audit_events(request.state.tenant_id, limit)

    return app, store, root


def mount_frontend(app, project_dir):
    dist = Path(project_dir) / "frontend/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
