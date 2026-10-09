import json
from pathlib import Path
from fastapi import HTTPException, File, UploadFile
from shared.api import base_app, mount_frontend
from .data import ingest
from .agent import DataAgent

PROJECT = Path(__file__).resolve().parents[1]


def prepare(request, store):
    with store.connect() as c:
        row = c.execute(
            "SELECT * FROM datasets WHERE id=?", (request.dataset_id,)
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
with store.connect() as c:
    count = c.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
if not count:
    sample = PROJECT / "examples/sales.csv"
    if sample.exists():
        ingest(root, store, sample.name, sample.read_bytes())


@app.get("/api/datasets")
async def datasets():
    with store.connect() as c:
        return [
            {**dict(r), "schema": json.loads(r["schema"])}
            for r in c.execute("SELECT * FROM datasets")
        ]


@app.post("/api/datasets")
async def upload(file: UploadFile = File(...)):
    import asyncio

    raw = await file.read(5 * 1024 * 1024 + 1)
    try:
        return await asyncio.to_thread(ingest, root, store, file.filename or "", raw)
    except Exception as exc:
        raise HTTPException(
            422,
            str(exc)[:300]
            if isinstance(exc, ValueError)
            else "文件解析失败，请检查内容。",
        )


mount_frontend(app, PROJECT)
