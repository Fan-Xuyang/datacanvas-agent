import json
from pathlib import Path
from fastapi import HTTPException, File, UploadFile, Query, Request
from pydantic import BaseModel, Field
from shared.api import base_app, mount_frontend
from .data import ingest
from .agent import DataAgent
from .data_quality import profile_dataset
from .mcp_client import call_readonly_tool, configured_servers, list_readonly_tools
from .evaluation import aggregate_retrieval_metrics, retrieval_case_metrics

PROJECT = Path(__file__).resolve().parents[1]


class RAGEvaluationCase(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    relevant_chunk_ids: list[str] = Field(min_length=1, max_length=100)


class RAGEvaluationRequest(BaseModel):
    cases: list[RAGEvaluationCase] = Field(min_length=1, max_length=20)
    k: int = Field(default=5, ge=1, le=20)


def prepare(request, store, tenant_id="local"):
    with store.connect() as c:
        row = c.execute(
            "SELECT * FROM datasets WHERE id=? AND tenant_id=?",
            (request.dataset_id, tenant_id),
        ).fetchone()
    if not row:
        raise HTTPException(400, "请选择已导入的数据集。")
    dataset = dict(row)
    dataset["schema"] = json.loads(dataset["schema"])
    if len(request.metrics) > 20 or any(
        len(k) > 80 or len(v) > 300 for k, v in request.metrics.items()
    ):
        raise HTTPException(422, "指标词典过长。")
    return {"dataset": dataset, "metrics": request.metrics}


app, store, root = base_app(PROJECT, "data", DataAgent, prepare)
knowledge = app.state.agent.knowledge
sample = PROJECT / "examples/uci_online_retail_sample.csv"
with store.connect() as c:
    sample_exists = c.execute(
        "SELECT 1 FROM datasets WHERE name=? LIMIT 1", (sample.name,)
    ).fetchone()
if sample.exists() and not sample_exists:
    ingest(root, store, sample.name, sample.read_bytes())


@app.get("/api/datasets")
async def datasets(request: Request):
    with store.connect() as c:
        return [
            {**dict(r), "schema": json.loads(r["schema"])}
            for r in c.execute(
                "SELECT id,name,schema,rows FROM datasets WHERE tenant_id=?",
                (request.state.tenant_id,),
            )
        ]


@app.post("/api/datasets")
async def upload(request: Request, file: UploadFile = File(...)):
    import asyncio

    raw = await file.read(5 * 1024 * 1024 + 1)
    try:
        return await asyncio.to_thread(
            ingest, root, store, file.filename or "", raw, request.state.tenant_id
        )
    except Exception as exc:
        raise HTTPException(
            422,
            str(exc)[:300]
            if isinstance(exc, ValueError)
            else "文件解析失败，请检查内容。",
        )


@app.get("/api/datasets/{dataset_id}/profile")
async def profile_data(dataset_id: str, request: Request):
    with store.connect() as c:
        row = c.execute(
            "SELECT schema FROM datasets WHERE id=? AND tenant_id=?",
            (dataset_id, request.state.tenant_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "数据集不存在。")
    try:
        return profile_dataset(root / f"{dataset_id}.duckdb", json.loads(row["schema"]))
    except Exception:
        raise HTTPException(422, "数据集质量分析失败。")


@app.get("/api/datasets/{dataset_id}/lineage")
async def dataset_lineage(dataset_id: str, request: Request):
    with store.connect() as c:
        row = c.execute(
            "SELECT source_name,source_sha256,ingested_at,row_count,column_count "
            "FROM dataset_lineage WHERE dataset_id=? AND tenant_id=?",
            (dataset_id, request.state.tenant_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "数据集血缘不存在。")
    return dict(row)


@app.get("/api/knowledge")
async def knowledge_documents(request: Request):
    return knowledge.documents(request.state.tenant_id)


@app.post("/api/knowledge", status_code=201)
async def add_knowledge(request: Request, file: UploadFile = File(...)):
    raw = await file.read(5 * 1024 * 1024 + 1)
    try:
        return await knowledge.add_document(
            file.filename or "", raw, request.state.tenant_id
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)[:300])
    except Exception:
        raise HTTPException(422, "文档解析失败，请检查文件内容。")


@app.get("/api/knowledge/search")
async def search_knowledge(
    request: Request, q: str = Query(min_length=1, max_length=2_000)
):
    return {"results": await knowledge.search(q, tenant_id=request.state.tenant_id)}


@app.get("/api/knowledge/answer")
async def answer_knowledge(
    request: Request, q: str = Query(min_length=1, max_length=2_000)
):
    return await knowledge.answer(q, tenant_id=request.state.tenant_id)


@app.delete("/api/knowledge/{document_id}")
async def delete_knowledge(document_id: str, request: Request):
    if not knowledge.delete_document(document_id, request.state.tenant_id):
        raise HTTPException(404, "知识文档不存在。")
    return {"deleted": True}


@app.get("/api/skills")
async def skills():
    return app.state.agent.skills.list()


@app.post("/api/evaluations/rag")
async def evaluate_rag(request: Request, body: RAGEvaluationRequest):
    results = []
    for case in body.cases:
        hits = await knowledge.search(
            case.query, tenant_id=request.state.tenant_id, limit=body.k
        )
        metrics = retrieval_case_metrics(
            [hit["id"] for hit in hits], case.relevant_chunk_ids, body.k
        )
        results.append(
            {
                "query": case.query,
                "relevant_chunk_ids": case.relevant_chunk_ids,
                "retrieved_chunk_ids": [hit["id"] for hit in hits],
                **metrics,
            }
        )
    return {
        **aggregate_retrieval_metrics(results),
        "k": body.k,
        "results": results,
    }


@app.get("/api/mcp/servers")
async def mcp_servers(request: Request):
    try:
        return [
            {"name": name}
            for name, config in configured_servers().items()
            if request.state.tenant_id in config["tenant_ids"]
        ]
    except ValueError as exc:
        raise HTTPException(503, str(exc))


@app.get("/api/mcp/servers/{server_name}/tools")
async def mcp_tools(server_name: str, request: Request):
    try:
        tools = await list_readonly_tools(server_name, request.state.tenant_id)
        return {"tools": tools}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(502, "MCP 工具服务暂时不可用。")


@app.post("/api/mcp/servers/{server_name}/tools/{tool_name}")
async def call_mcp_tool(
    server_name: str, tool_name: str, arguments: dict, request: Request
):
    try:
        return await call_readonly_tool(
            server_name, tool_name, arguments, request.state.tenant_id
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(502, "MCP 工具调用失败。")


mount_frontend(app, PROJECT)
