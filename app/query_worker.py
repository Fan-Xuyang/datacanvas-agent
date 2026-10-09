"""Dedicated bounded DuckDB process; no generated Python is executed."""

import json
import sys
import duckdb


def main():
    request = json.loads(sys.stdin.read())
    c = duckdb.connect(
        request["path"],
        read_only=True,
        config={
            "enable_external_access": "false",
            "autoload_known_extensions": "false",
            "autoinstall_known_extensions": "false",
            "threads": "1",
            "memory_limit": "256MB",
        },
    )
    try:
        cursor = c.execute(request["sql"])
        rows = cursor.fetchmany(501)
        print(
            json.dumps(
                {
                    "columns": [x[0] for x in cursor.description],
                    "rows": rows[:500],
                    "truncated": len(rows) > 500,
                },
                default=str,
                ensure_ascii=True,
                allow_nan=False,
            )
        )
    finally:
        c.close()


if __name__ == "__main__":
    main()
