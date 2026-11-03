"""Read-only profiling and data quality diagnostics for imported datasets."""

from pathlib import Path
import duckdb


def profile_dataset(path, schema):
    columns = [item["name"] for item in schema]
    if not columns:
        raise ValueError("数据集没有可分析字段。")
    quoted = [f'"{name.replace(chr(34), chr(34) * 2)}"' for name in columns]
    connection = duckdb.connect(str(Path(path)), read_only=True)
    try:
        total = connection.execute("SELECT COUNT(*) FROM data").fetchone()[0]
        fields = []
        for item, column in zip(schema, quoted):
            distinct = connection.execute(
                f"SELECT COUNT(DISTINCT {column}) FROM data"
            ).fetchone()[0]
            non_null = connection.execute(
                f"SELECT COUNT({column}) FROM data"
            ).fetchone()[0]
            entry = {
                "name": item["name"],
                "type": item["type"],
                "null_count": total - non_null,
                "null_rate": round((total - non_null) / total, 4) if total else 0,
                "distinct_count": distinct,
                "distinct_rate": round(distinct / total, 4) if total else 0,
            }
            if item["type"] == "DOUBLE":
                entry["min"], entry["max"] = connection.execute(
                    f"SELECT MIN({column}), MAX({column}) FROM data"
                ).fetchone()
            fields.append(entry)
        duplicate_sql = (
            "SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) AS n "
            "FROM data GROUP BY " + ", ".join(quoted) + ")"
        )
        duplicate_rows = connection.execute(duplicate_sql).fetchone()[0]
    finally:
        connection.close()
    issues = []
    for item in fields:
        if item["null_count"]:
            issues.append(
                {
                    "field": item["name"],
                    "type": "missing_values",
                    "count": item["null_count"],
                }
            )
        if total and item["distinct_count"] <= 1:
            issues.append(
                {"field": item["name"], "type": "constant_field", "count": total}
            )
    if duplicate_rows:
        issues.append(
            {"field": None, "type": "duplicate_rows", "count": duplicate_rows}
        )
    return {"rows": total, "fields": fields, "issues": issues}
