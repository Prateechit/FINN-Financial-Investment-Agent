"""Promise Ledger: what management guided vs what the reported numbers show.

Reasoning runs over (a) quote-verified guidance items and (b) the deterministic fact table — never raw
documents — so the model judges, but cannot invent, evidence. Output ids and numbers are validated.
"""
import json
import re

from ..grounding import ungrounded
from ..llm import chat_json

VERDICTS = ["delivered", "missed", "on_track", "at_risk", "goalposts_moved", "dropped", "too_early", "unverifiable"]

SYSTEM = """You audit management credibility for a public-markets investor: compare what management PROMISED on earnings
calls with what the company actually REPORTED. You receive GUIDANCE items (verbatim, with ids) from successive calls,
oldest first, and ACTUALS (reported figures, with fact ids). Use nothing else — no outside knowledge.

Group guidance about the same thing across calls into one row (e.g. FY27 revenue growth guided in three calls).
For each row decide a verdict:
- delivered: the horizon has ended and actuals meet the target
- missed: the horizon has ended and actuals fall short
- on_track / at_risk: horizon still running; judge from year-to-date or latest-quarter actuals
- goalposts_moved: the target was lowered, softened or pushed out in a later call
- dropped: a specific promise that later calls stop mentioning, with no explanation
- too_early: horizon running and no actual yet bears on it
- unverifiable: actuals given cannot test it (e.g. non-financial promise with no later evidence)

Rules:
- Quote numbers exactly as they appear in GUIDANCE or ACTUALS. Do not compute new numbers (no differences, no sums).
- cite guidance_ids and fact_ids that support each row; fact_ids must be ids from ACTUALS.
- "trajectory": one entry per call where this promise was discussed: stance = set|reiterated|raised|lowered|softened.
- Be strict: "delivered" only if the actual meets or beats the target (inside a range counts). Below the low end of a
  range is "missed" — "close to" is not delivered. If year-to-date or latest-quarter actuals move AGAINST an open
  promise (e.g. margins falling while expansion is promised), the verdict is "at_risk", not "too_early".
- Coverage: include every distinct company-level promise on revenue/growth, margins and profit, plus capex and the
  largest segment promises — including open ones, so the investor sees what is still outstanding. 6–8 rows when the
  guidance supports it, most material first. Margin promises must be compared with the reported margin facts.

Return JSON:
{"rows":[{"subject":"short label, e.g. 'FY27 revenue growth'","metric":"metric type","promise":"max 18 words: target + horizon",
  "guidance_ids":["G1.2"],"trajectory":[{"call":"Q4 FY26","guidance_id":"G1.2","stance":"set"}],
  "delivered":"max 25 words: what actually happened","fact_ids":["calc.ytd_revenue_growth"],
  "verdict":"one verdict","why":"max 30 words"}],
 "credibility":"max 45 words: overall read on whether this management's guidance can be relied on, and in which areas"}"""


def readable_ids(text: str, facts: dict) -> str:
    """Models occasionally write a fact id into prose ("Q.OPM %.Jun 2026 was 3%"); show the label instead."""
    for fid in sorted((f for f in facts if f in text), key=len, reverse=True):
        text = text.replace(fid, f"{facts[fid]['label'].replace(' %', '')} ({facts[fid]['period']})")
    # "fell -44.9%" → "fell 44.9%": the verb already carries the sign
    return re.sub(r"\b(fell|declined|dropped|decreased|contracted|shrank|down|lower) (by )?-(?=\d)", r"\1 \2", text)


def fmt(v: float, unit: str) -> str:
    """How a fact is shown to the model — and therefore how the model will quote it."""
    if unit == "₹ Cr":
        return f"₹{v:,.0f} Cr" if abs(v) >= 100 else f"₹{v:,.1f} Cr"
    if unit == "%":
        return f"{v:g}%"
    if unit == "x":
        return f"{v:g}x"
    if unit == "days":
        return f"{v:.0f} days"
    if unit == "₹":
        return f"₹{v:,.2f}"
    return f"{v:g} {unit}"


def _actuals_text(facts: dict) -> tuple[str, list[str]]:
    keep = []
    for fid, f in facts.items():
        if fid.startswith(("calc.", "Q.", "A.")) and not fid.startswith(("Q.Other", "A.Other", "A.EPS", "A.Interest", "A.Depreciation")):
            keep.append(fid)
    # Most recent periods matter most; cap the prompt size.
    keep = keep[-260:]
    lines = [f"{fid} = {fmt(facts[fid]['value'], facts[fid]['unit'])} ({facts[fid]['label']}, {facts[fid]['period']})" for fid in keep]
    return "\n".join(lines), keep


def _guidance_text(calls: list[dict]) -> str:
    out = []
    for c in sorted(calls, key=lambda c: c["guidance"][0]["id"] if c.get("guidance") else "Z"):
        for g in c.get("guidance", []):
            out.append(f"{g['id']} | call {g['call']} | {g['metric']} | {g.get('subject')} | target: {g.get('target')} | "
                       f"horizon: {g.get('horizon')} | \"{g['statement']}\"")
    return "\n".join(out)


def build(calls: list[dict], facts: dict, latest_quarter: str) -> dict:
    guidance = {g["id"]: g for c in calls for g in c.get("guidance", [])}
    if len(guidance) < 2:
        return {"status": "insufficient", "rows": [], "note": "Not enough verifiable guidance in the available transcripts."}
    actuals, fact_ids = _actuals_text(facts)
    gtext = _guidance_text(calls)
    call_order = [c["call"] for c in reversed(calls)]  # oldest → newest
    user = (f"Latest reported quarter: {latest_quarter}. Calls (oldest→newest): {', '.join(call_order)}.\n\n"
            f"GUIDANCE:\n{gtext}\n\nACTUALS:\n{actuals}")
    evidence = gtext + "\n" + actuals
    out = chat_json("ledger", "reason", SYSTEM, user, max_tokens=10000)
    rows, problems = _validate(out, guidance, set(fact_ids), evidence)
    if problems:
        retry = user + "\n\nYour previous answer had these problems; fix them:\n- " + "\n- ".join(problems[:12])
        out2 = chat_json("ledger_retry", "reason", SYSTEM, retry, max_tokens=10000)
        rows2, problems2 = _validate(out2, guidance, set(fact_ids), evidence)
        if len(problems2) < len(problems):
            out, rows, problems = out2, rows2, problems2
    for r in rows:
        for k in ("promise", "delivered", "why"):
            r[k] = readable_ids(r.get(k) or "", facts)
        _range_check(r, guidance, facts)
        stances = {t["call"]: t for t in r.get("trajectory") or [] if t.get("call") in call_order}
        r["timeline"] = [{"call": c, **({"stance": stances[c]["stance"], "guidance_id": stances[c].get("guidance_id")}
                                         if c in stances else {"stance": "silent"})} for c in call_order]
        r["evidence"] = [guidance[g] for g in r["guidance_ids"]]
        r["facts"] = [facts[f] for f in r["fact_ids"]]
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    return {"status": "ok", "rows": rows, "credibility": out.get("credibility"), "counts": counts, "calls": call_order,
            "warnings": problems}


def _validate(out: dict, guidance: dict, fact_ids: set, evidence: str):
    rows, problems = [], []
    for i, r in enumerate((out.get("rows") or [])[:8]):
        r["guidance_ids"] = [g for g in r.get("guidance_ids") or [] if g in guidance]
        bad_facts = [f for f in r.get("fact_ids") or [] if f not in fact_ids]
        r["fact_ids"] = [f for f in r.get("fact_ids") or [] if f in fact_ids]
        if not r["guidance_ids"]:
            problems.append(f"row {i + 1} ('{r.get('subject')}') cites no valid guidance id")
            continue
        if bad_facts:
            problems.append(f"row {i + 1} cites unknown fact ids {bad_facts}")
        if r.get("verdict") not in VERDICTS:
            problems.append(f"row {i + 1} has invalid verdict {r.get('verdict')!r}")
            r["verdict"] = "unverifiable"
        # A judgement needs evidence: a reported figure, or a later call where management speaks to it.
        later_calls = {guidance[g]["call"] for g in r["guidance_ids"]}
        if r["verdict"] in ("delivered", "missed", "on_track", "at_risk") and not r["fact_ids"] and len(later_calls) < 2:
            r["downgraded_from"] = r["verdict"]
            r["verdict"] = "unverifiable"
            r["why"] = "No reported figure or later management statement in the sources tests this promise."
        text = " ".join(str(r.get(k) or "") for k in ("promise", "delivered", "why"))
        if bad := ungrounded(text, evidence):
            problems.append(f"row {i + 1} uses numbers not in GUIDANCE/ACTUALS: {bad[:5]}")
            r["grounded"] = False
        else:
            r["grounded"] = True
        rows.append(r)
    return rows, problems


_UNIT = {"Cr": "₹ Cr", "%": "%"}


def _range_check(r: dict, guidance: dict, facts: dict) -> None:
    """Compare the cited actual with the guided numeric range in code; override a lenient verdict.

    Applied only when the latest guidance in the row has a numeric range and exactly one cited fact shares its unit,
    so a segment target is never compared with a company-wide figure by accident.
    """
    nums = [guidance[g] for g in r["guidance_ids"] if guidance[g].get("low") is not None and guidance[g].get("unit") in _UNIT]
    if not nums:
        return
    g = nums[-1]
    same = [facts[f] for f in r["fact_ids"] if facts[f]["unit"] == _UNIT[g["unit"]]]
    if len(same) != 1:
        return
    v, lo = same[0]["value"], float(g["low"])
    hi = float(g["high"]) if g.get("high") is not None else lo
    result = "below" if v < lo * 0.995 else "above" if v > hi * 1.005 else "within"
    r["check"] = {"actual": v, "low": lo, "high": hi, "unit": same[0]["unit"], "result": result,
                  "fact": same[0]["label"], "period": same[0]["period"], "guidance_id": g["id"]}
    # "delivered" means the horizon has ended, so a shortfall is a miss. For a running horizon only rate targets (%)
    # are comparable year-to-date; a level target (₹ Cr over 3 years) is naturally below target part-way through.
    if result == "below" and (r["verdict"] == "delivered" or (r["verdict"] == "on_track" and g["unit"] == "%")):
        r["downgraded_from"] = r["verdict"]
        r["verdict"] = "missed" if r["verdict"] == "delivered" else "at_risk"
        rng = f"{fmt(lo, same[0]['unit'])}–{fmt(hi, same[0]['unit'])}" if hi != lo else fmt(lo, same[0]["unit"])
        r["why"] = f"{same[0]['label']} was {fmt(v, same[0]['unit'])} ({same[0]['period']}), below the guided {rng}."


def compact(ledger: dict) -> str:
    """Short text form for downstream prompts."""
    return json.dumps([{"id": f"L{i + 1}", "subject": r["subject"], "verdict": r["verdict"], "why": r.get("why")}
                       for i, r in enumerate(ledger.get("rows", []))])
