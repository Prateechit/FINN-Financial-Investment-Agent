"""Audit Promise Ledger rows for fiscal-period alignment — read-only (GET requests only).

python scripts/audit_periods.py [--api https://finn-api-bbyo.onrender.com] [SYMBOL ...]

For every ledger row whose promise names a fiscal period, applies the same rule the ledger now enforces
(backend/finn/pull/periods.check):
  - a quarter / half-year that has not started can only be "too_early";
  - an ended quarter / half-year must be judged on a figure from inside it;
  - an ended fiscal year judged delivered/missed must cite a figure from that year.
Also lists, for information, cited quarters that are neither inside the promise nor its comparison base.
Memos built before the fix may fail; rebuild them, then re-run. Exits 1 if any row fails.
"""
import json
import re
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from finn.pull import periods  # noqa: E402  (pure module: no database, no network, no LLM)

DEFAULT_API = os.getenv("FINN_API_URL", "https://finn-api-bbyo.onrender.com")


def get(api: str, path: str):
    with urllib.request.urlopen(api.rstrip("/") + path, timeout=180) as r:
        return json.load(r)


def audit_memo(memo: dict) -> tuple[int, list[dict]]:
    secs = memo.get("sections") or {}
    q = (secs.get("trajectory") or {}).get("quarterly") or []
    latest = periods.from_calendar(q[-1]["period"]) if q else None
    checked, findings = 0, []
    for r in (secs.get("ledger") or {}).get("rows", []):
        promise = periods.latest_promise(r.get("evidence") or [])
        if not promise:
            continue
        checked += 1
        cited = [(f["id"], periods.fact_period(f["id"], f.get("period"))) for f in r.get("facts", [])]
        verdict = r.get("downgraded_from") if r.get("period_check") else r["verdict"]  # judge what the model said
        result = periods.check(verdict, promise, cited, latest)
        inside = [promise.start.shift(i) for i in range(4) if promise.contains(promise.start.shift(i))]
        base = {promise.start.prev(), *(fq.year_ago() for fq in inside)}  # sequential base, year-ago quarters
        named = {int(n) for g in r.get("evidence") or [] for n in re.findall(r"\bQ([1-4])\b", g.get("statement", ""))}
        base |= {promise.start.shift(-k) for k in range(1, 5) if promise.start.shift(-k).q in named}  # e.g. "our Q2 run-rate"
        unrelated = sorted({p.label for _, p in cited if p and p.kind == "quarter" and not promise.covers(p) and p.start not in base})
        if result or r.get("period_check"):
            findings.append({"subject": r["subject"], "verdict": r["verdict"], "period": promise.label,
                             "cited": [fid for fid, _ in cited] or r.get("rejected_fact_ids"),
                             "problem": (result or (None, None))[1], "guarded": bool(r.get("period_check")),
                             "unrelated": unrelated})
    return checked, findings


def main(argv: list[str]) -> int:
    api = DEFAULT_API
    if "--api" in argv:
        i = argv.index("--api")
        api, argv = argv[i + 1], argv[:i] + argv[i + 2:]
    symbols = argv or [m["symbol"] for m in get(api, "/api/research") if m.get("status") in ("done", "partial")]
    total, failing = 0, 0
    for sym in symbols:
        memo = get(api, f"/api/research/{urllib.parse.quote(sym)}")
        checked, findings = audit_memo(memo)
        total += checked
        open_problems = [f for f in findings if f["problem"] and not f["guarded"]]
        failing += len(open_problems)
        print(f"{sym}: {checked} period-specific row(s), {len(open_problems)} failing"
              + (f", {sum(f['guarded'] for f in findings)} already corrected by the ledger guard" if any(f["guarded"] for f in findings) else ""))
        for f in findings:
            status = "corrected" if f["guarded"] else "FAIL"
            print(f"  [{status}] {f['subject']!r} — {f['verdict']} | promise {f['period']} | cited {f['cited']}")
            if f["problem"]:
                print(f"           {f['problem']}")
            if f["unrelated"]:
                print(f"           unrelated quarters cited: {f['unrelated']}")
    print(f"\n{total} period-specific rows checked across {len(symbols)} memo(s); {failing} failing.")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
