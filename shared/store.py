import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, kind TEXT, query TEXT, mode TEXT, status TEXT, state TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, type TEXT, payload TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY, name TEXT, schema TEXT, rows INTEGER);
                CREATE TABLE IF NOT EXISTS dataset_lineage(
                    dataset_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    ingested_at REAL NOT NULL,
                    row_count INTEGER NOT NULL,
                    column_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS receipts(task_id TEXT PRIMARY KEY, payload TEXT, receipt TEXT);
                CREATE TABLE IF NOT EXISTS audit_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    role TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    created REAL NOT NULL
                );
            """)
            self._ensure_column(
                c, "tasks", "tenant_id", "TEXT NOT NULL DEFAULT 'local'"
            )
            self._ensure_column(
                c, "datasets", "tenant_id", "TEXT NOT NULL DEFAULT 'local'"
            )

    @staticmethod
    def _ensure_column(connection, table, column, definition):
        names = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in names:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            with c:
                yield c
        finally:
            c.close()

    def create(self, kind, query, mode, state, tenant_id="local"):
        tid = uuid.uuid4().hex
        with self.connect() as c:
            c.execute(
                "INSERT INTO tasks(id,kind,query,mode,status,state,created,tenant_id) VALUES(?,?,?,?,?,?,?,?)",
                (
                    tid,
                    kind,
                    query,
                    mode,
                    "queued",
                    json.dumps(state, ensure_ascii=False),
                    time.time(),
                    tenant_id,
                ),
            )
        self.event(tid, "queued", {"message": "任务已入队"})
        return tid

    def get(self, tid, tenant_id=None):
        with self.connect() as c:
            if tenant_id is None:
                row = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            else:
                row = c.execute(
                    "SELECT * FROM tasks WHERE id=? AND tenant_id=?", (tid, tenant_id)
                ).fetchone()
        if not row:
            raise KeyError(tid)
        result = dict(row)
        result["state"] = json.loads(result["state"])
        return result

    def tasks(self, kind, tenant_id="local"):
        with self.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id,query,mode,status,created FROM tasks WHERE kind=? AND tenant_id=? ORDER BY created DESC LIMIT 100",
                    (kind, tenant_id),
                )
            ]

    def checkpoint(self, tid, status, state, event_type, payload):
        # State and its event commit together; SSE readers cannot see a half-checkpoint.
        with self.connect() as c:
            c.execute(
                "UPDATE tasks SET status=?,state=? WHERE id=?",
                (status, json.dumps(state, ensure_ascii=False), tid),
            )
            c.execute(
                "INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)",
                (tid, event_type, json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def event(self, tid, kind, payload):
        with self.connect() as c:
            c.execute(
                "INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)",
                (tid, kind, json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def audit(self, tenant_id, actor, role, method, path, status, duration_ms):
        with self.connect() as c:
            c.execute(
                "INSERT INTO audit_events(tenant_id,actor,role,method,path,status,duration_ms,created) VALUES(?,?,?,?,?,?,?,?)",
                (
                    tenant_id,
                    actor,
                    role,
                    method,
                    path,
                    status,
                    duration_ms,
                    time.time(),
                ),
            )

    def audit_events(self, tenant_id, limit=100):
        with self.connect() as c:
            return [
                dict(row)
                for row in c.execute(
                    "SELECT * FROM audit_events WHERE tenant_id=? ORDER BY seq DESC LIMIT ?",
                    (tenant_id, min(max(limit, 1), 500)),
                )
            ]

    def metrics(self, kind, tenant_id):
        with self.connect() as c:
            statuses = {
                row[0]: row[1]
                for row in c.execute(
                    "SELECT status,COUNT(*) FROM tasks WHERE kind=? AND tenant_id=? GROUP BY status",
                    (kind, tenant_id),
                )
            }
            rows = c.execute(
                "SELECT mode,state FROM tasks WHERE kind=? AND tenant_id=? ORDER BY created DESC LIMIT 1000",
                (kind, tenant_id),
            ).fetchall()
            datasets = c.execute(
                "SELECT COUNT(*) FROM datasets WHERE tenant_id=?", (tenant_id,)
            ).fetchone()[0]
            documents = c.execute(
                "SELECT COUNT(*) FROM knowledge_docs WHERE tenant_id=?", (tenant_id,)
            ).fetchone()[0]
        usage = [
            item
            for row in rows
            if row["mode"] == "live"
            for item in json.loads(row["state"]).get("usage", [])
        ]
        return {
            "tasks_by_status": statuses,
            "datasets": datasets,
            "knowledge_documents": documents,
            "model_calls": len(usage),
            "input_tokens": sum(item.get("input_tokens") or 0 for item in usage),
            "output_tokens": sum(item.get("output_tokens") or 0 for item in usage),
            "model_latency_ms": sum(item.get("latency_ms") or 0 for item in usage),
        }

    def events(self, tid, after=0):
        with self.connect() as c:
            return [
                {**dict(r), "payload": json.loads(r["payload"])}
                for r in c.execute(
                    "SELECT * FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 500",
                    (tid, after),
                )
            ]

    def recover(self, kind):
        with self.connect() as c:
            c.execute(
                "UPDATE tasks SET status='interrupted' WHERE kind=? AND status IN ('queued','running')",
                (kind,),
            )

    def claim(self, tid, statuses):
        with self.connect() as c:
            placeholders = ",".join("?" for _ in statuses)
            return (
                c.execute(
                    f"UPDATE tasks SET status='running' WHERE id=? AND status IN ({placeholders})",
                    (tid, *statuses),
                ).rowcount
                == 1
            )
