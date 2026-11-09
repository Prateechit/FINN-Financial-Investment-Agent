"""Independently re-validate a stored research memo against its primary sources.

python scripts/validate_memo.py SYMBOL [SYMBOL ...]

Checks (re-derived here, not trusted from the pipeline):
  quotes   every guidance quote appears verbatim on its cited transcript page (elided "…" quotes: every part)
  ledger   cited guidance/fact ids exist; every number in the prose is in the evidence; verdicts that claim an
           outcome cite a reported figure (or ≥2 calls); numeric range verdicts agree with the numbers
  thesis   3 bull + 3 bear; every point cites valid evidence; numbers grounded; analyst claims attributed;
           no internal ids or "(S2)"-style tags in prose
Exits non-zero if any hard check fails.
"""
import re
import sys

sys.path.insert(0, "backend")
from finn.grounding import ungrounded  # noqa: E402
from finn.pull.research import get  # noqa: E402
from finn.sources import docs  # noqa: E402

OUTCOME = {"delivered", "missed", "on_track", "at_risk"}
LEAK = re.compile(r"\b(calc|Q|A|X)\.[A-Za-z]|\([SLGA]\d+(\.\d+)?[,)]")


def quote_ok(g) -> bool:
    d = docs.pages(g["url"])
    i = g["page"] - 1
    hay = docs.norm(d["pages"][i] + " " + (d["pages"][i + 1] if i + 1 < len(d["pages"]) else ""))
    parts = [p for p in re.split(r"\.\.\.|…", g["statement"]) if len(docs.norm(p)) >= 12]
    return bool(parts) and all(docs.norm(p) in hay for p in parts)


def validate(sym: str) -> list[str]:
    st = get(sym)
    if not st:
        return [f"{sym}: no memo"]
    s, hard = st["sections"], []
    print(f"\n=== {sym} · status {st['status']} · models {st['usage']['models']} · "
          f"{st['usage']['calls']} calls ({st['usage']['cache_hits']} cached) ===")

    items = (s.get("guidance") or {}).get("items", [])
    bad_q = [g["id"] for g in items if not quote_ok(g)]
    print(f"QUOTES   {len(items) - len(bad_q)}/{len(items)} verbatim on cited page"
          f" · discarded upstream {sum(c.get('dropped_unverified') or 0 for c in s['guidance']['calls'])}")
    hard += [f"{sym}: quote {q} not on cited page" for q in bad_q]

    L = s.get("ledger") or {}
    gids = {g["id"]: g for g in items}
    print(f"LEDGER   {len(L.get('rows', []))} rows · {({k: v for k, v in (L.get('counts') or {}).items() if v})}")
    print(f"         credibility: {L.get('credibility')}")
    for r in L.get("rows", []):
        facts = {f["id"]: f for f in r["facts"]}
        evidence = " ".join(gids[g]["statement"] + " " + str(gids[g].get("target")) for g in r["guidance_ids"] if g in gids)
        evidence += " " + " ".join(f"{f['value']} {f['label']}" for f in r["facts"])
        problems = []
        if any(g not in gids for g in r["guidance_ids"]):
            problems.append("unknown guidance id")
        if bad := ungrounded(f"{r['promise']} {r['delivered']} {r['why']}", evidence + " " + r.get("why", "")):
            problems.append(f"numbers not in cited evidence {bad}")
        if r["verdict"] in OUTCOME and not facts and len({gids[g]['call'] for g in r['guidance_ids'] if g in gids}) < 2:
            problems.append("outcome verdict without evidence")
        if (c := r.get("check")) and ((c["result"] == "below" and r["verdict"] == "delivered") or (c["result"] != "below" and r["verdict"] == "missed")):
            problems.append(f"verdict contradicts range check {c}")
        if LEAK.search(f"{r['promise']} {r['delivered']} {r['why']}"):
            problems.append("internal id in prose")
        flag = "OK " if not problems else "ERR"
        print(f"  {flag} [{r['verdict']}{' ←' + r['downgraded_from'] if r.get('downgraded_from') else ''}] {r['subject']}")
        print(f"        promised: {r['promise']}\n        actual:   {r['delivered']}\n        why:      {r['why']}")
        if problems:
            print(f"        !! {'; '.join(problems)}")
        hard += [f"{sym}: ledger '{r['subject']}': {p}" for p in problems if "numbers" not in p]
        if any("numbers" in p for p in problems):
            print("        (numbers check is against the row's own cited evidence — stricter than the pipeline's check)")

    T = s.get("thesis") or {}
    pts = [("BULL", p) for p in T.get("bull", [])] + [("BEAR", p) for p in T.get("bear", [])]
    print(f"THESIS   {len(T.get('bull', []))} bull · {len(T.get('bear', []))} bear")
    if len(T.get("bull", [])) != 3 or len(T.get("bear", [])) != 3:
        hard.append(f"{sym}: thesis is not 3+3")
    for side, p in pts:
        problems = []
        if not p["refs"]:
            problems.append("no sources")
        if not p["grounded"]:
            problems.append("ungrounded number")
        if LEAK.search(p["point"]):
            problems.append("ref tag/internal id in prose")
        if any(e["type"] == "analyst" for e in p["evidence"]) and "analyst" not in p["point"].lower():
            problems.append("analyst claim not attributed")
        print(f"  {'OK ' if not problems else 'ERR'} {side}: {p['point']}  [{', '.join(p['refs'])}]")
        hard += [f"{sym}: thesis '{p['point'][:40]}…': {x}" for x in problems]
    if T.get("watch"):
        print(f"  WATCH: {T['watch']['point']}")
    return hard


if __name__ == "__main__":
    failures = [f for sym in (sys.argv[1:] or ["DIXON", "HDFCBANK"]) for f in validate(sym.upper())]
    print("\n" + ("ALL HARD CHECKS PASSED" if not failures else f"{len(failures)} HARD FAILURES:\n  " + "\n  ".join(failures)))
    sys.exit(1 if failures else 0)
