import asyncio
import csv
import hashlib
import io
import json
import re
import sys
import uuid
from pathlib import Path
import duckdb
import openpyxl
import sqlglot
from sqlglot import exp


def normalize_column(value, index, used):
    name = re.sub(r"[^\w]", "_", str(value or "").strip())[:50] or f"column_{index + 1}"
    if name[0].isdigit():
        name = "c_" + name
    base = name
    suffix = 2
    while name.lower() in used:
        name = f"{base}_{suffix}"
        suffix += 1
    used.add(name.lower())
    return name


def ingest(root, store, name, raw):
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("文件最多 5 MB。")
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
        reader = csv.reader(io.StringIO(text))
    elif suffix == ".xlsx":
        book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        reader = book.active.iter_rows(values_only=True)
    else:
        raise ValueError("仅支持 CSV 或 XLSX。")
    try:
        header = next(reader)
        if not 1 <= len(header) <= 50:
            raise ValueError("需包含 1–50 列及表头。")
        used = set()
        columns = [normalize_column(v, i, used) for i, v in enumerate(header)]
        rows = []
        for row in reader:
            if len(rows) >= 20000:
                raise ValueError("数据行数最多 20,000。")
            if len(row) != len(columns):
                raise ValueError("数据行与表头列数不一致。")
            if any(len(str(v)) > 10000 for v in row if v is not None):
                raise ValueError("单元格内容过长。")
            rows.append(
                [None if v is None or str(v).strip() == "" else str(v) for v in row]
            )
    finally:
        if suffix == ".xlsx":
            book.close()
    if not rows:
        raise ValueError("文件需要至少一行数据。")
    numeric = []
    for i in range(len(columns)):
        values = [r[i] for r in rows if r[i] is not None]
        try:
            parsed = [float(v) for v in values]
            import math

            numeric.append(bool(values) and all(math.isfinite(v) for v in parsed))
        except ValueError:
            numeric.append(False)
    converted = [
        [float(v) if v is not None and numeric[i] else v for i, v in enumerate(row)]
        for row in rows
    ]
    did = uuid.uuid4().hex
    path = Path(root) / f"{did}.duckdb"
    schema = [
        {"name": n, "type": "DOUBLE" if numeric[i] else "VARCHAR"}
        for i, n in enumerate(columns)
    ]
    c = duckdb.connect(str(path))
    try:
        defs = ",".join('"' + x["name"] + '" ' + x["type"] for x in schema)
        c.execute("CREATE TABLE data (" + defs + ")")
        c.executemany(
            "INSERT INTO data VALUES(" + ",".join("?" for _ in columns) + ")", converted
        )
    finally:
        c.close()
    with store.connect() as db:
        db.execute(
            "INSERT INTO datasets VALUES(?,?,?,?)",
            (
                did,
                Path(name).name[:100],
                json.dumps(schema, ensure_ascii=False),
                len(rows),
            ),
        )
    return {"id": did, "name": Path(name).name, "schema": schema, "rows": len(rows)}


def validate_sql(sql):
    if len(sql) > 6000:
        raise ValueError("SQL 过长。")
    statements = sqlglot.parse(sql, read="duckdb")
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError("仅允许单条 SELECT 查询。")
    tree = statements[0]
    if tree.args.get("with_") or tree.args.get("into"):
        raise ValueError("此版本不允许 CTE 或写入输出。")
    tables = list(tree.find_all(exp.Table))
    if not tables or any(
        t.name != "data" or t.db or t.catalog or not isinstance(t.this, exp.Identifier)
        for t in tables
    ):
        raise ValueError("只能读取当前数据集 data。")
    forbidden = (exp.Subquery, exp.Command, exp.Union, exp.Join)
    if any(isinstance(n, forbidden) for n in tree.walk()):
        raise ValueError("此版本不支持子查询、连接或集合操作。")
    allowed = {
        "SUM",
        "AVG",
        "COUNT",
        "MIN",
        "MAX",
        "ROUND",
        "COALESCE",
        "CAST",
        "TRY_CAST",
        "STRFTIME",
        "DATE_TRUNC",
        "LOWER",
        "UPPER",
        "LENGTH",
        "ABS",
        "NULLIF",
    }
    for func in tree.find_all(exp.Func):
        name = func.name.upper() if isinstance(func, exp.Anonymous) else func.sql_name()
        if name not in allowed:
            raise ValueError("不支持的 SQL 函数：" + name)
    return tree.sql(dialect="duckdb")


async def execute(path, sql, timeout=8):
    sql = validate_sql(sql)
    worker = Path(__file__).with_name("query_worker.py")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(worker),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, error = await asyncio.wait_for(
            process.communicate(json.dumps({"path": str(path), "sql": sql}).encode()),
            timeout,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        message = error.decode(errors="replace").splitlines()[-1:]
        raise ValueError(("查询执行失败：" + " ".join(message))[:500])
    result = json.loads(output)
    result["sql"] = sql
    result["checksum"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return result
