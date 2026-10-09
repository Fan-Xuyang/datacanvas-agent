import asyncio
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
from shared.store import Store
from app.data import ingest, validate_sql, execute
from app.agent import DataAgent, ChartSpec, demo_plan


@pytest.fixture
def data(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    dataset = ingest(
        tmp_path, store, "sales.csv", (ROOT / "examples/sales.csv").read_bytes()
    )
    return tmp_path, store, dataset


def test_real_query_and_evidence(data):
    root, store, dataset = data
    tid = store.create("data", "按区域比较销售额", "demo", {"dataset": dataset})
    assert store.claim(tid, ["queued"])
    asyncio.run(DataAgent(store, root).run(tid))
    task = store.get(tid)
    assert task["status"] == "completed"
    result = task["state"]["result"]
    assert result["columns"] == ["category", "value"]
    assert dict(result["rows"]) == {
        "华东": 626000.0,
        "华北": 470000.0,
        "西北": 333000.0,
    }
    assert len(result["checksum"]) == 64
    assert result["checksum"] in task["state"]["report"]
    assert "626000" in task["state"]["report"]


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE data",
        "SELECT * FROM data; DELETE FROM data",
        "SELECT * FROM read_csv_auto('C:/Windows/win.ini')",
        "SELECT read_blob('secret') FROM data",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM data d JOIN data x ON true",
        "WITH x AS (SELECT * FROM data) SELECT * FROM x",
        "SELECT * FROM (SELECT * FROM data)",
        "COPY data TO 'x.csv'",
        "SELECT * FROM other",
    ],
)
def test_sql_boundary(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_chart_schema_rejects_generated_script():
    with pytest.raises(ValueError):
        ChartSpec(kind="javascript", x="region", y="sales", title="unsafe")
    with pytest.raises(ValueError):
        ChartSpec(
            kind="bar", x="region", y="sales", title="unsafe", formatter="alert(1)"
        )


def test_live_plan_repair_without_provider(data, monkeypatch):
    root, store, dataset = data
    import app.agent as module

    calls = []

    async def fake(system, payload, schema):
        calls.append(payload)
        plan = demo_plan("区域", dataset["schema"])
        if len(calls) == 1:
            plan.sql = "SELECT unknown_column FROM data"
        return plan, {"input_tokens": 10, "output_tokens": 20, "latency_ms": 1}

    monkeypatch.setattr(module, "structured", fake)
    tid = store.create("data", "比较区域", "live", {"dataset": dataset})
    asyncio.run(DataAgent(store, root).run(tid))
    task = store.get(tid)
    assert task["status"] == "completed"
    assert task["state"]["attempt"] == 1
    assert len(calls) == 2
    assert any(e["type"] == "repair" for e in store.events(tid))


def test_repair_budget_stops(data, monkeypatch):
    root, store, dataset = data
    import app.agent as module

    async def fake(*args):
        plan = demo_plan("区域", dataset["schema"])
        plan.sql = "SELECT missing FROM data"
        return plan, {"input_tokens": 1, "output_tokens": 1, "latency_ms": 1}

    monkeypatch.setattr(module, "structured", fake)
    tid = store.create("data", "比较区域", "live", {"dataset": dataset})
    with pytest.raises(ValueError):
        asyncio.run(DataAgent(store, root).run(tid))
    assert store.get(tid)["state"]["attempt"] == 2


def test_recovery_event_cursor_and_claim(data):
    root, store, dataset = data
    tid = store.create("data", "趋势", "demo", {"dataset": dataset})
    assert store.claim(tid, ["queued"])
    assert not store.claim(tid, ["queued"])
    store.recover("data")
    assert store.get(tid)["status"] == "interrupted"
    assert store.claim(tid, ["interrupted"])
    asyncio.run(DataAgent(store, root).run(tid))
    saved = Store(root / "state.sqlite3")
    events = saved.events(tid)
    assert saved.get(tid)["status"] == "completed"
    assert saved.events(tid, events[-2]["seq"]) == events[-1:]


def test_upload_shape_types_and_empty(data):
    root, store, _ = data
    for name, raw in [("x.exe", b"hi"), ("x.csv", b"a,b\n1\n"), ("x.csv", b"a,b\n")]:
        with pytest.raises(ValueError):
            ingest(root, store, name, raw)
    dataset = ingest(root, store, "dup.csv", b"name,name,value\nx,x,2\n")
    assert [s["name"] for s in dataset["schema"]] == ["name", "name_2", "value"]


def test_xlsx_ingestion(data):
    import io
    from openpyxl import Workbook

    root, store, _ = data
    book = Workbook()
    book.active.append(["region", "sales"])
    book.active.append(["north", 12])
    buffer = io.BytesIO()
    book.save(buffer)
    dataset = ingest(root, store, "table.xlsx", buffer.getvalue())
    assert dataset["rows"] == 1
    result = asyncio.run(
        execute(root / f"{dataset['id']}.duckdb", "SELECT SUM(sales) FROM data")
    )
    assert result["rows"] == [[12.0]]
