"""End-to-end smoke test: every API endpoint the frontend uses, through the same origin the browser uses.

python scripts/smoke_test.py [base_url]     (default: the Vite dev server, which proxies /api)
Exits non-zero on any failure, so it can gate a deploy.
"""
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5173").rstrip("/")
c = httpx.Client(base_url=BASE, timeout=120)
fails: list[str] = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


def get(path, **kw):
    t = time.time()
    r = c.get(path, **kw)
    return r, (time.time() - t) * 1000


r, ms = get("/")
check("frontend shell served", r.status_code == 200 and '<div id="root">' in r.text, f"{ms:.0f} ms")
r, ms = get("/manifest.webmanifest")
check("PWA manifest", r.status_code == 200 and r.json().get("short_name") == "FINN")

r, ms = get("/api/health")
h = r.json()
check("health", r.status_code == 200 and h["ok"], f"{h.get('announcements')} filings, llm tiers: { {k: len(v) for k, v in h['llm'].items()} }")
check("an LLM is configured for every tier", all(h["llm"].values()))

r, ms = get("/api/digest", params={"hours": 336})
d = r.json()
check("digest (2 weeks)", r.status_code == 200 and d["counts"]["filings"] > 0, f"{d['counts']} in {ms:.0f} ms")
st = d["stories"]
check("stories ranked by materiality", all(st[i]["materiality"] >= st[i + 1]["materiality"] for i in range(len(st) - 1)))
check("no routine items among stories", all(s["tier"] != "routine" for s in st))
res = [s for s in st if s["category"] == "results"]
check("results stories carry a results card", res and all((s["enrichment"] or {}).get("status") in ("ok", "pending") for s in res),
      f"{len(res)} results stories")
mg = [s for s in st if s["category"] == "management_change" and (s["enrichment"] or {}).get("changes")]
check("management stories name the person", all(s["title"].split(" — ")[0] for s in mg), f"{len(mg)} with people")
check("every story has reasons for its rank", all(len(s["reasons"]) >= 1 for s in st))
check("clustered stories list related filings", any(s["related"] for s in st))
r, ms = get("/api/digest", params={"hours": 24})
check("digest (24h)", r.status_code == 200, f"{r.json()['counts']}")

r, ms = get("/api/alerts", params={"days": 7})
a = r.json()
check("alerts", r.status_code == 200 and "alerts" in a, f"{len(a['alerts'])} alerts in {ms:.0f} ms")
check("one price/volume alert per stock per day",
      len({(x['symbol'], x['date']) for x in a['alerts'] if x['kind'] != 'announcement'}) ==
      len([x for x in a['alerts'] if x['kind'] != 'announcement']))

s0 = c.get("/api/settings").json()
r = c.put("/api/settings", json={**s0, "price_move_pct": 10.0})
fewer = len(c.get("/api/alerts", params={"days": 7}).json()["alerts"])
c.put("/api/settings", json=s0)
check("thresholds change alerts immediately", r.status_code == 200 and fewer <= len(a["alerts"]),
      f"±10% → {fewer} alerts vs {len(a['alerts'])} at ±{s0['price_move_pct']}%")
check("invalid threshold rejected", c.put("/api/settings", json={"price_move_pct": 500}).status_code == 400)

r, ms = get("/api/portfolio")
p = r.json()
check("portfolio", r.status_code == 200 and len(p) == 19 and all(x["close"] for x in p), f"{len(p)} holdings")
check("weights sum to 100%", abs(sum(x["weight"] for x in p) - 100) < 0.01)

for sym in ("DIXON", "HDFCBANK", "PIDILITIND"):
    r, ms = get(f"/api/company/{sym}")
    cv = r.json()
    check(f"company page {sym}", r.status_code == 200 and cv["prices"] is not None,
          f"results: {(cv.get('results') or {}).get('quarter', {}).get('label')} via {(cv.get('results') or {}).get('source')}, {ms:.0f} ms")

r, ms = get("/api/search", params={"q": "pidi"})
check("search any NSE company", r.status_code == 200 and any(x["symbol"] == "PIDILITIND" for x in r.json()))

for sym in ("DIXON", "HDFCBANK"):
    r = c.post(f"/api/research/{sym}")
    m = r.json()
    secs = m.get("sections", {})
    led = secs.get("ledger") or {}
    check(f"research memo {sym}", r.status_code == 200 and m["status"] == "done",
          f"{len(led.get('rows', []))} ledger rows, verdicts {({k: v for k, v in (led.get('counts') or {}).items() if v})}")
    check(f"{sym}: ledger rows carry quotes and timeline", all(x["evidence"] and x["timeline"] for x in led.get("rows", [])))
    check(f"{sym}: every ledger row number-grounded", all(x["grounded"] for x in led.get("rows", [])))
    th = secs.get("thesis") or {}
    check(f"{sym}: 3 bull + 3 bear, all sourced", len(th.get("bull", [])) == 3 and len(th.get("bear", [])) == 3
          and all(p["refs"] for p in th["bull"] + th["bear"]))
    check(f"{sym}: no internal fact ids leak into prose",
          not any(t in str([x["delivered"] for x in led.get("rows", [])] + [p["point"] for p in th.get("bull", []) + th.get("bear", [])])
                  for t in ("calc.", "Q.OPM", "X.", "(S1", "(S2", "(L1", "(L2", "(G")))
check("unknown symbol fails cleanly", c.post("/api/research/NOTAREALCO").json().get("status") in ("running", "error"))

r = c.get("/api/research")
check("memo list", r.status_code == 200 and len(r.json()) >= 2)
r = c.get("/api/usage")
check("usage ledger", r.status_code == 200 and r.json()["tasks"], f"{len(r.json()['tasks'])} task types logged")
check("ingest endpoint is protected", c.post("/api/ingest").status_code == 401)

print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
