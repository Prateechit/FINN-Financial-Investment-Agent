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
- No proxies: judge a promise only with a fact that measures the same thing (NIM ≠ PAT margin, ROA ≠ profit,
  credit-deposit ratio ≠ debt/equity, balance-sheet growth ≠ revenue growth). If no such fact exists the verdict is
  "unverifiable" — say which figure is missing. Facts marked "(exchange filing)" are the company's own XBRL figures.

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
    text = re.sub(r"\s*\((?:G\d+\.\d+(?:,\s*)?)+\)", "", text)  # "(G1.4)": guidance ids belong in citations, not prose
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


_MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def _ordinal(period: str) -> int | None:
    m = re.fullmatch(r"(\w{3}) (\d{4})", period)
    return int(m.group(2)) * 12 + _MONTHS[m.group(1)] if m and m.group(1) in _MONTHS else None


def _actuals_text(facts: dict) -> tuple[str, list[str]]:
    """Facts a five-call ledger can need: the last 8 quarters and 4 years, plus every derived figure.

    Older history adds tokens, not judgement — and a smaller prompt fits free tiers with per-minute token caps.
    """
    # Raw statement rows a guidance audit uses: top line, operating margin, profit, asset quality. Everything else it
    # needs is a derived (calc.) or exchange-filing (X.) figure.
    raw_keep = ("Sales.", "Revenue.", "OPM %.", "Operating Profit.", "Net Profit.", "Gross NPA %.", "Net NPA %.")
    cands = [fid for fid in facts if fid.startswith(("calc.", "X."))
             and not fid.startswith(("calc.net_worth.", "calc.cfo_pat.", "calc.fcf_5y"))
             or fid.startswith(("Q.", "A.")) and fid.split(".", 1)[1].startswith(raw_keep)]
    family = lambda fid: fid.rsplit(".", 1)[0] if _ordinal(facts[fid]["period"]) is not None else None  # noqa: E731
    latest: dict = {}
    for fid in cands:
        if (fam := family(fid)) is not None:
            latest[fam] = max(latest.get(fam, 0), _ordinal(facts[fid]["period"]))
    keep = []
    for fid in cands:
        fam = family(fid)
        window = 21 if fid.startswith(("Q.", "calc.Q.")) else 36  # 8 quarters / 4 fiscal years
        if fam is None or _ordinal(facts[fid]["period"]) >= latest[fam] - window:
            keep.append(fid)
    lines = [f"{fid} = {fmt(facts[fid]['value'], facts[fid]['unit'])}" + ("" if facts[fid]["period"] in fid else f" ({facts[fid]['period']})")
             + ("" if facts[fid]["label"].split(" (")[0] in fid else f" — {facts[fid]['label']}") for fid in keep]
    return "\n".join(lines), keep


def _guidance_text(calls: list[dict]) -> str:
    out = []
    for c in sorted(calls, key=lambda c: c["guidance"][0]["id"] if c.get("guidance") else "Z"):
        for g in c.get("guidance", []):
            out.append(f"{g['id']} | {g['call']} | {g.get('subject')} | target {g.get('target')} | {g.get('horizon')} | "
                       f"\"{g['statement'][:240]}\"")
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
    out = chat_json("ledger", "reason", SYSTEM, user, max_tokens=20000)
    rows, problems = _validate(out, guidance, set(fact_ids), evidence)
    if problems:
        retry = user + "\n\nYour previous answer had these problems; fix them:\n- " + "\n- ".join(problems[:12])
        out2 = chat_json("ledger_retry", "reason", SYSTEM, retry, max_tokens=20000)
        rows2, problems2 = _validate(out2, guidance, set(fact_ids), evidence)
        if len(problems2) < len(problems):
            out, rows, problems = out2, rows2, problems2
    for r in rows:
        for k in ("promise", "delivered", "why"):
            r[k] = readable_ids(r.get(k) or "", facts)
        _metric_guard(r, facts)
        _range_check(r, guidance, facts)
        _horizon_guard(r, guidance, latest_quarter)
        stances = {t["call"]: t for t in r.get("trajectory") or [] if t.get("call") in call_order}
        r["timeline"] = [{"call": c, **({"stance": stances[c]["stance"], "guidance_id": stances[c].get("guidance_id")}
                                         if c in stances else {"stance": "silent"})} for c in call_order]
        r["evidence"] = [guidance[g] for g in r["guidance_ids"]]
        r["facts"] = [facts[f] for f in r["fact_ids"]]
    # What needs attention first: broken or shifting promises, then kept ones, then what can't be judged yet.
    order = ["missed", "at_risk", "goalposts_moved", "dropped", "delivered", "on_track", "too_early", "unverifiable"]
    rows.sort(key=lambda r: order.index(r["verdict"]))
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

# Metrics that are often guided but easy to "judge" with a look-alike number. A row about one of these may only be
# judged with a fact that measures it; otherwise it is unverifiable. (pattern in promise → pattern a fact id must match)
_METRIC_GUARDS = [
    (r"\bnim\b|net interest margin", r"\bnim\b|net interest margin", "net interest margin"),
    (r"\bcasa\b", r"casa", "CASA ratio"),
    (r"\blcr\b|liquidity coverage", r"lcr", "liquidity coverage ratio"),
    (r"credit[- ]deposit|\bldr\b|loan[- ]to[- ]deposit", r"credit_deposit|ldr", "credit-deposit ratio"),
    (r"\broa\b|return on (average )?assets?", r"calc\.roa", "return on assets"),
    (r"balance[- ]sheet growth", r"calc\.asset_growth", "balance-sheet growth"),
    (r"cost[- ]to[- ]income|cost[- ]to[- ]earnings", r"cost_income", "cost-to-income ratio"),
    (r"\bgnpa\b|gross npa|asset quality", r"npa", "NPA ratio"),
]


def _fy_of(quarter_end: str) -> int | None:
    """'Sep 2026' → 27 (FY27)."""
    o = _ordinal(quarter_end)
    if o is None:
        return None
    year, month = divmod(o, 12)
    return (year + 1 if month >= 3 else year) % 100


def _horizon_guard(r: dict, guidance: dict, latest_quarter: str) -> None:
    """'Missed' means the deadline has passed. If the latest guidance on this promise still has an open horizon
    (a future fiscal year, 'medium term', 'next N years'), the honest verdict is 'at_risk'."""
    if r["verdict"] != "missed":
        return
    fy = _fy_of(latest_quarter)
    horizon = str(guidance[r["guidance_ids"][-1]].get("horizon") or "").lower()
    years = [int(y) % 100 for y in re.findall(r"fy\s?'?(\d{2,4})", horizon)]
    open_ended = re.search(r"medium|long|years?|next|coming|over the|ahead|future", horizon)
    if open_ended or (fy and years and max(years) >= fy):
        r["downgraded_from"] = "missed"
        r["verdict"] = "at_risk"
        r["why"] = f"The promise's horizon ({horizon}) has not ended, so it cannot be missed yet. " + (r.get("why") or "")


def _metric_guard(r: dict, facts: dict) -> None:
    text = f"{r.get('subject')} {r.get('promise')}".lower()
    for promise_rx, fact_rx, name in _METRIC_GUARDS:
        if re.search(promise_rx, text):
            if not any(re.search(fact_rx, f"{fid} {facts[fid]['label']}", re.I) for fid in r["fact_ids"]):
                if r["verdict"] not in ("unverifiable", "goalposts_moved", "dropped"):
                    r["downgraded_from"] = r["verdict"]
                    r["verdict"] = "unverifiable"
                    r["why"] = (f"The sources give no {name} figure, so this promise can't be judged; "
                                f"FINN does not substitute a different metric.")
                    r["delivered"] = f"No reported {name} in the filings used."
                    r["fact_ids"] = []
            return


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
                       for i, r in enumerate(ledger.get("rows", []))], ensure_ascii=False)  # "₹" must stay parseable
