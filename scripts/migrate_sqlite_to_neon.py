"""Copy a FINN SQLite database into Postgres (Neon). Safe to rerun; never writes to the source.

python scripts/migrate_sqlite_to_neon.py SOURCE.db [--verify-only]

- Source is opened read-only and read through the app's own table definitions, so JSON / dates / booleans are
  converted exactly as the app reads them.
- Target is DATABASE_URL_UNPOOLED (else DATABASE_URL) from backend/.env — the direct connection suits bulk loads.
  Tables are created from the models if missing.
- Rows are inserted with INSERT … ON CONFLICT (primary key) DO NOTHING: reruns add nothing twice and never overwrite
  rows the cloud app has written or updated since. One transaction per table.
- Afterwards every table is compared row by row (content fingerprints), and the llm_calls id sequence is advanced.
No connection string, password or key is ever printed.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

ORDER = ["companies", "prices_eod", "announcements", "alerts", "kv", "llm_calls"]
BATCH = {"kv": 40}  # kv rows can be ~0.2 MB each


def pg_url() -> str:
    env = {**dotenv_values(ROOT / "backend" / ".env"), **os.environ}
    url = env.get("DATABASE_URL_UNPOOLED") or env.get("DATABASE_URL")
    if not url or url.startswith("sqlite"):
        sys.exit("No Postgres DATABASE_URL(_UNPOOLED) configured in backend/.env")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
    return url


def norm(v):
    """Canonical form for fingerprints, identical for values read from SQLite and from Postgres."""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, float):
        return repr(round(v, 9))
    return v


def fingerprint(row) -> str:
    return hashlib.sha256(json.dumps([norm(v) for v in row], sort_keys=True, default=str).encode()).hexdigest()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    source = Path(args[0]).resolve()
    verify_only = "--verify-only" in sys.argv

    target = pg_url()  # resolve before the override below
    os.environ["DATABASE_URL"] = "sqlite://"  # keep finn.db's import-time engine off both databases
    from finn.db import Base

    src = create_engine(f"sqlite:///file:{source.as_posix()}?mode=ro&uri=true")
    dst = create_engine(target, pool_pre_ping=True)
    with dst.connect() as c:
        print("target:", c.execute(text("select current_database()")).scalar(), "on",
              c.execute(text("select split_part(version(), ' ', 2)")).scalar(), "(Postgres)")
    if not verify_only:
        Base.metadata.create_all(dst)

    report, ok = [], True
    for name in ORDER:
        table = Base.metadata.tables[name]
        pk = [c.name for c in table.primary_key.columns]
        with src.connect() as s:
            rows = [dict(r._mapping) for r in s.execute(select(table))]
        t0 = time.time()
        with dst.connect() as d:
            before = d.execute(select(func.count()).select_from(table)).scalar()
        if not verify_only and rows:
            with dst.begin() as d:  # one transaction per table
                size = BATCH.get(name, 500)
                for i in range(0, len(rows), size):
                    stmt = pg_insert(table).values(rows[i:i + size]).on_conflict_do_nothing(index_elements=pk)
                    d.execute(stmt)  # driver rowcount is -1 for multi-row inserts; count before/after instead
            if name == "llm_calls":
                with dst.begin() as d:
                    d.execute(text("select setval(pg_get_serial_sequence('llm_calls','id'), "
                                   "greatest((select coalesce(max(id), 0) from llm_calls), 1))"))
        def rows_by_key(conn):
            return {tuple(norm(r[k]) for k in pk): fingerprint([r[c.name] for c in table.c])
                    for r in (x._mapping for x in conn.execute(select(table)))}
        with src.connect() as s, dst.connect() as d:
            src_rows, dst_rows = rows_by_key(s), rows_by_key(d)
            dst_n = d.execute(select(func.count()).select_from(table)).scalar()
        missing = sum(1 for k in src_rows if k not in dst_rows)                              # real loss
        identical = sum(1 for k, f in src_rows.items() if dst_rows.get(k) == f)
        updated = len(src_rows) - missing - identical  # key present, content newer in target (cloud app wrote it)
        only_target = sum(1 for k in dst_rows if k not in src_rows)                          # created by the cloud app
        ok &= missing == 0
        report.append((name, len(rows), dst_n - before, dst_n, identical, updated, missing, only_target, round(time.time() - t0, 1)))

    print(f"\n{'table':14s} {'source':>7s} {'inserted':>9s} {'target':>7s} {'identical':>10s} {'updated':>8s} {'missing':>8s} {'new':>5s}  secs")
    for r in report:
        print(f"{r[0]:14s} {r[1]:7d} {r[2]:9d} {r[3]:7d} {r[4]:10d} {r[5]:8d} {r[6]:8d} {r[7]:5d}  {r[8]}")
    print("\nupdated = row exists in target with newer content written by the app after migration (kept, by design)")
    print("RESULT:", "no source row is missing from the target" if ok else "MISSING ROWS — see 'missing'")
    sys.exit(0 if ok else 1)


_SECRET = re.compile(r"(postgres(?:ql)?(?:\+psycopg)?://)[^\s'\"]+|(password|passwd|pwd)\s*[=:]\s*\S+|"
                     r"(host|user|dbname)\s*=\s*\S+|ep-[a-z0-9-]+(?:\.[a-z0-9.-]+)?|npg_[A-Za-z0-9]+|"
                     r"(for user )['\"][^'\"]+['\"]", re.I)


def redact(msg: str) -> str:
    return _SECRET.sub(lambda m: (m.group(1) or m.group(4) or "") + "[REDACTED]", msg)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 — never let a driver error print connection details
        sys.exit(f"migration failed: {type(e).__name__}: {redact(str(e))[:500]}")
