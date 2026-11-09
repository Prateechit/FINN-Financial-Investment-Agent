"""Evaluate the results engine on the portfolio: source used, arithmetic check, two-source agreement."""
import json
import sys

sys.path.insert(0, "backend")
from finn.db import init_db  # noqa: E402
from finn.push.results import results_card  # noqa: E402

init_db()
spec = json.load(open("backend/portfolio.json"))
rows, agree, compared, arith = [], 0, 0, 0
for h in spec["holdings"]:
    c = results_card(h["symbol"])
    if not c:
        rows.append((h["symbol"], "none", "", "", ""))
        continue
    xs = [x for x in c["checks"] if "matches" in x["name"]]
    ar = [x for x in c["checks"] if "PBT" in x["name"]]
    compared += bool(xs)
    agree += bool(xs) and all(x["ok"] for x in xs)
    arith += bool(ar) and ar[0]["ok"]
    rows.append((h["symbol"], c["quarter"]["label"], c["source"], c["kind"],
                 "agree" if xs and all(x["ok"] for x in xs) else ("differ: " + "; ".join(x["detail"] for x in xs if not x["ok"]) if xs else "single source")))
for r in rows:
    print(" | ".join(map(str, r)))
print(f"\n{len(rows)} companies · arithmetic check passed {arith} · two sources compared {compared}, agreed {agree}")
