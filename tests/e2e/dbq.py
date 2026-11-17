"""Read JACK's database from the e2e script, whichever store the app is using.

Usage: python tests/e2e/dbq.py <data dir> "<SQL>"   (prints the first column of the first row)

Since Milestone 6, JACK runs on embedded PostgreSQL (decision D-1), falling back to SQLite when
PostgreSQL can't run (for example as root). The SQL is written for SQLite; the few dialect
differences used in the e2e checks are translated for PostgreSQL.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path


def pg_port(data: Path) -> int | None:
    pid_file = data / "pg16" / "postmaster.pid"
    try:
        lines = pid_file.read_text().splitlines()
        pid, port = int(lines[0]), int(lines[3])
        os.kill(pid, 0)
        return port
    except (OSError, ValueError, IndexError):
        return None


def to_pg(sql: str) -> str:
    # json_extract(col,'$.a.b') -> (col::jsonb #>> '{a,b}')
    sql = re.sub(r"json_extract\((\w+(?:\.\w+)?),\s*'\$\.([\w.]+)'\)",
                 lambda m: f"({m.group(1)}::jsonb #>> '{{{m.group(2).replace('.', ',')}}}')", sql)
    return re.sub(r"\b(succeeded)\s*=\s*1\b", r"\1", sql)


def main() -> int:
    data, sql = Path(sys.argv[1]), sys.argv[2]
    port = pg_port(data)
    if port is not None:
        import psycopg

        password = (data / "pg16.pass").read_text().strip()
        with psycopg.connect(host="127.0.0.1", port=port, user="jack", password=password,
                             dbname="jack", connect_timeout=3) as conn:
            row = conn.execute(to_pg(sql)).fetchone()  # type: ignore[arg-type]
    else:
        db = data / "jack.db"
        if not db.exists():
            return 1
        row = sqlite3.connect(db).execute(sql).fetchone()
    if row is None or row[0] is None:
        return 1
    v = row[0]
    print(str(v).lower() if isinstance(v, bool) else v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
