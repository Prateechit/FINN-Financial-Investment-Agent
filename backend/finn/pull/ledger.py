"""Promise Ledger: what management guided vs what the reported numbers show.

Reasoning runs over (a) quote-verified guidance items and (b) the deterministic fact table — never raw
documents — so the model judges, but cannot invent, evidence. Output ids and numbers are validated.
"""
import json
import re

from ..grounding import ungrounded
from ..llm import chat_json
from . import narrative, periods

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
- Periods: India's fiscal year runs April–March. Q1 = Apr–Jun, Q2 = Jul–Sep, Q3 = Oct–Dec, Q4 = Jan–Mar, and FY26
  ends in March 2026 — so "Mar 2026" is Q4 FY26 and "Sep 2026" is Q2 FY27. Each GUIDANCE line states the fiscal period
  the promise is about; each ACTUALS line is tagged with its fiscal period in [brackets]. Judge a promise only with
  facts from its own period (plus the quarter before for a sequential promise, or the same quarter a year earlier for
  a year-on-year one) — never with the latest quarter just because it is latest. A quarter or half-year that has not
  started yet is "too_early".
- Sequential (quarter-on-quarter) promises: cite calc.Q.revenue_qoq / calc.Q.pat_qoq for that quarter. Quarterly
  margin promises: cite calc.Q.ebitda_margin (exact, two decimals) for every quarter compared. OPM % is rounded to
  whole numbers, so two quarters can look tied (16% vs 16%) when they are not — never decide a comparison on it.

Return JSON:
{"rows":[{"subject":"short label, e.g. 'FY27 revenue growth'","metric":"metric type","promise":"max 18 words: target + horizon",
  "guidance_ids":["G1.2"],"trajectory":[{"call":"Q4 FY26","guidance_id":"G1.2","stance":"set"}],
  "delivered":"max 25 words: what actually happened","fact_ids":["calc.ytd_revenue_growth"],
  "verdict":"one verdict","why":"max 30 words"}],
 "credibility":"max 45 words: overall read on whether this management's guidance can be relied on, and in which areas"}
The credibility read must agree with your verdicts: say a promise was missed only if its row is "missed", and met or
delivered only if its row is "delivered". A promise whose horizon is still running (on_track / at_risk) has not been
missed or delivered yet — say it is at risk or on track."""


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
             or fid.startswith(("Q.", "A.")) and fid.split(".", 1)[1].startswith(raw_keep)
             and not _has_exact_margin(fid, facts)]  # a quarter's rounded OPM % is hidden when its exact margin exists
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
    def line(fid):
        f = facts[fid]
        fiscal = periods.tag(fid, f["period"])  # "Q.Sales.Mar 2026" → [Q4 FY26]; "A.Sales.Mar 2026" → [FY26]
        return (f"{fid} = {fmt(f['value'], f['unit'])}" + ("" if f["period"] in fid else f" ({f['period']})")
                + (f" [{fiscal}]" if fiscal else "")
                + ("" if f["label"].split(" (")[0] in fid else f" — {f['label']}"))
    return "\n".join(line(fid) for fid in keep), keep


def _guidance_text(calls: list[dict]) -> str:
    out = []
    for c in sorted(calls, key=lambda c: c["guidance"][0]["id"] if c.get("guidance") else "Z"):
        for g in c.get("guidance", []):
            p = periods.promise_period(g)
            said = g.get("horizon")
            when = (f"period {p.label}" + (f" (said: {said!r})" if said and said.strip().upper() != p.label.upper() else "")
                    if p else f"horizon {said!r}")
            out.append(f"{g['id']} | {g['call']} call | {g.get('subject')} | target {g.get('target')} | {when} | "
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
        _period_guard(r, guidance, facts, periods.from_calendar(latest_quarter))
        _margin_guard(r, guidance, facts)
        _range_check(r, guidance, facts)
        _horizon_guard(r, guidance, latest_quarter)
        _subject_guard(r, guidance)
        stances = {t["call"]: t for t in r.get("trajectory") or [] if t.get("call") in call_order}
        r["timeline"] = [{"call": c, **({"stance": stances[c]["stance"], "guidance_id": stances[c].get("guidance_id")}
                                         if c in stances else {"stance": "silent"})} for c in call_order]
        r["evidence"] = [guidance[g] for g in r["guidance_ids"]]
        r["facts"] = [facts[f] for f in r["fact_ids"]]
    # What needs attention first: broken or shifting promises, then kept ones, then what can't be judged yet.
    order = ["missed", "at_risk", "goalposts_moved", "dropped", "delivered", "on_track", "too_early", "unverifiable"]
    rows.sort(key=lambda r: order.index(r["verdict"]))
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    result = {"status": "ok", "rows": rows, "credibility": out.get("credibility"), "counts": counts, "calls": call_order,
              "warnings": problems}
    _credibility_guard(result)
    return result


def _credibility_guard(result: dict) -> None:
    """The model writes the credibility read alongside its own verdicts, before the code guards change any; it must
    agree with the final ones. If it calls a promise missed/delivered that the ledger doesn't, state the record."""
    text = readable_ids(result.get("credibility") or "", {})
    if issue := narrative.credibility_issue(text, result["rows"]):
        result["credibility_check"] = {"replaced": text, "issue": issue}
        result["credibility"] = narrative.credibility_summary(result["rows"])


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


def _promise(r: dict, guidance: dict) -> periods.Period | None:
    """The period the row's promise is about: from its most recent guidance item that names one."""
    return periods.latest_promise([guidance[g] for g in r["guidance_ids"] if g in guidance])


def _period_guard(r: dict, guidance: dict, facts: dict, latest: periods.FQ | None) -> None:
    """Evidence must come from the promise's own period; a period that hasn't started can only be 'too_early'."""
    promise = _promise(r, guidance)
    cited = [(fid, periods.fact_period(fid, facts[fid]["period"])) for fid in r["fact_ids"]]
    result = periods.check(r["verdict"], promise, cited, latest)
    if not result:
        return
    verdict, reason = result
    r["downgraded_from"], r["verdict"], r["why"] = r["verdict"], verdict, reason
    r["period_check"] = {"promise_period": promise.label, "latest": latest.label,
                         "cited": [p.label if p else None for _, p in cited]}
    if verdict == "unverifiable":  # wrong-period figures are not evidence for this promise
        r["rejected_fact_ids"], r["fact_ids"] = r["fact_ids"], []
        r["delivered"] = f"No reported figure for {promise.label} was cited."
    else:
        r["delivered"] = f"{promise.label} has not been reported yet."


# Quarterly operating-margin facts. screener's OPM % is rounded to whole numbers, so Q4 FY26 and Q2 FY26 can both read
# 16% while the exact margins are 16.03% and 15.72%. Exact families, in order of preference: FINN's own operating
# profit ÷ sales (two decimals), then the company's exchange filing. (Lender margins are a different metric: not here.)
ROUNDED_MARGIN = "Q.OPM %."
EXACT_MARGINS = ("calc.Q.ebitda_margin.", "X.EBITDA margin.")
_RAISE = re.compile(r"\b(exceed\w*|above|improv\w*|expan\w*|higher|increas\w*|better|beat\w*|ahead)\b", re.I)
_LOWER = re.compile(r"\b(below|declin\w*|lower\w*|reduc\w*|compress\w*|contract\w*|fall\w*|drop\w*)\b", re.I)


def _has_exact_margin(fid: str, facts: dict) -> bool:
    return fid.startswith(ROUNDED_MARGIN) and f"{EXACT_MARGINS[0]}{fid[len(ROUNDED_MARGIN):]}" in facts


def margin_quarter(fid: str, period: str | None) -> periods.FQ | None:
    """Fiscal quarter of a quarterly operating-margin fact (rounded or exact); None for anything else."""
    if not fid.startswith((ROUNDED_MARGIN, *EXACT_MARGINS)):
        return None
    p = periods.fact_period(fid, period)
    return p.start if p and p.kind == "quarter" else None


_Q = r"Q([1-4])(?:\s*(?:of\s+)?FY\s?'?(\d{2,4}))?"
# A quarter is a comparison base only when the text compares with it: "Q2 run-rate", "Q2 level", "versus Q2",
# "above our Q2 …", "exceed the Q2 …". A quarter merely mentioned ("Q3 was soft") or a deadline ("recover by Q4",
# "in Q4") is not.
_BASE_AFTER = re.compile(rf"\b{_Q}(?:['’]s)?\s+(?:margins?\s+)?(?:run[- ]?rates?|levels?|base(?:line)?|exit(?:\s+rate)?)\b", re.I)
_BASE_BEFORE = re.compile(rf"\b(?:versus|vs\.?|than|above|over|exceed(?:s|ed|ing)?|beat(?:s|ing)?|surpass(?:es|ed|ing)?|"
                          rf"ahead\s+of|below|under|compared\s+(?:with|to)|relative\s+to)\s+(?:the\s+|our\s+|its\s+|their\s+)?"
                          rf"{_Q}\b", re.I)
_SEQUENTIAL_WORD = re.compile(r"\bsequential(?:ly)?\b|\bquarter[- ]on[- ]quarter\b|\bq-?o-?q\b", re.I)


def _base_quarter(r: dict, guidance: dict, promise: periods.Period) -> tuple[periods.FQ | None, str | None]:
    """The quarter a single-quarter margin promise is compared with, when the promise explicitly names one.

    "exceed our Q2 run-rate" → the latest Q2 before the promised quarter (said on a Q3 FY26 call about Q4 FY26: Q2
    FY26); "above the Q2 FY26 level" → Q2 FY26; "sequential" → the quarter before. Only a comparison counts: a quarter
    merely mentioned in the statement, a deadline ("recover by Q4") or the promised quarter itself is not a base, and a
    base must come before the promised quarter. A promise with a numeric target (low / high) is a level promise —
    the range check judges it, so no base is looked for. Returns (quarter, None); (None, None) if none is named;
    (None, reason) if two different ones are.
    """
    items = [guidance[g] for g in r["guidance_ids"] if g in guidance]
    if any(g.get("low") is not None or g.get("high") is not None for g in items):
        return None, None
    sources = [" ".join(str(g.get("target") or "") for g in items),
               f"{r.get('subject') or ''} {r.get('promise') or ''}",
               " ".join(str(g.get("statement") or "") for g in items)]
    for text in sources:
        found = set()
        for m in [*_BASE_AFTER.finditer(text), *_BASE_BEFORE.finditer(text)]:
            q = int(m.group(1))
            if m.group(2):
                fq = periods.FQ(int(m.group(2)) % 100, q)
            elif q == promise.start.q:
                continue  # the promised quarter itself
            else:
                fq = next(promise.start.shift(-k) for k in range(1, 4) if promise.start.shift(-k).q == q)
            if fq < promise.start:  # a base is an earlier quarter; a later one is a deadline, not a comparison
                found.add(fq)
        if len(found) > 1:
            return None, f"The promise names more than one comparison quarter ({', '.join(x.label for x in sorted(found))})."
        if found:
            return found.pop(), None
    if any(_SEQUENTIAL_WORD.search(t) for t in sources[:2]):
        return promise.start.prev(), None
    return None, None


def _margin_families(quarters: list, facts: dict) -> list[dict]:
    """Per exact source family (in order of preference): {quarter: fact id} for the quarters asked about."""
    return [{q: fid for fid, f in facts.items() if fid.startswith(prefix)
             and (q := margin_quarter(fid, f["period"])) in quarters} for prefix in EXACT_MARGINS]


def _cite_instead(r: dict, cited: dict, fid: str) -> None:
    """Replace the row's cited quarterly margin(s) for the promised quarter with one exact fact id."""
    swapped = list(dict.fromkeys(fid if f in cited else f for f in r["fact_ids"]))
    if replaced := [f for f in r["fact_ids"] if f not in swapped]:
        r["replaced_fact_ids"] = replaced
    r["fact_ids"] = swapped


def _margin_guard(r: dict, guidance: dict, facts: dict) -> None:
    """Quarterly margin comparisons are decided on exact margins, never on rounded OPM %.

    Cited rounded margins are replaced by one exact family that covers every quarter compared. When a single-quarter
    promise names its comparison quarter ("exceed our Q2 run-rate") but only the promised quarter is cited, that
    quarter's exact margin is attached from the same family — looked up, never estimated. A comparison with no exact
    figure for every quarter is 'unverifiable'. A single-quarter promise to raise the margin above another quarter's
    level is then decided in code from the exact pair.
    """
    cited = {fid: q for fid in r["fact_ids"] if (q := margin_quarter(fid, facts[fid]["period"]))}
    if not cited:
        return
    quarters = sorted(set(cited.values()))
    promise = _promise(r, guidance)
    base_needed = None
    if (len(quarters) == 1 and r["verdict"] in periods.OUTCOME and promise and promise.kind == "quarter"
            and quarters[0] == promise.start):
        base_needed, ambiguous = _base_quarter(r, guidance, promise)
        if ambiguous:
            # Judge nothing, but show the promised quarter's exact margin rather than a rounded one.
            target = next((ids[promise.start] for ids in _margin_families([promise.start], facts) if promise.start in ids), None)
            if target:
                _cite_instead(r, cited, target)
            r["downgraded_from"], r["verdict"] = r["verdict"], "unverifiable"
            r["why"], r["delivered"] = ambiguous, "The comparison quarter could not be identified."
            r["margin_check"] = {"result": "base_ambiguous", "target": promise.label}
            return
        if base_needed:
            quarters = sorted({promise.start, base_needed})
    families = _margin_families(quarters, facts)
    exact = next((ids for ids in families if len(ids) == len(quarters)), None)
    if base_needed and not exact:
        # The named comparison quarter has no exact margin in the sources: say so, judge nothing, and still show the
        # promised quarter's exact figure if there is one.
        target = next((ids[promise.start] for ids in families if promise.start in ids), None)
        if target:
            _cite_instead(r, cited, target)
        shown = f"{fmt(facts[target]['value'], '%')} in {promise.label}" if target else f"the {promise.label} margin"
        r["downgraded_from"], r["verdict"] = r["verdict"], "unverifiable"
        r["why"] = (f"No exact margin for {base_needed.label} in the sources, so {shown} can't be compared with the "
                    f"{base_needed.label} level.")
        r["delivered"] = f"No exact {base_needed.label} margin figure to compare with."
        r["margin_check"] = {"result": "base_missing", "target": promise.label, "base": base_needed.label}
        return
    if exact:
        swapped = list(dict.fromkeys(exact[cited[fid]] if fid in cited else fid for fid in r["fact_ids"]))
        if replaced := [fid for fid in r["fact_ids"] if fid not in swapped]:
            r["replaced_fact_ids"] = replaced
        if base_needed and exact[base_needed] not in swapped:
            swapped.append(exact[base_needed])
            r["attached_fact_ids"] = [exact[base_needed]]
        r["fact_ids"] = swapped
    if len(quarters) < 2 or r["verdict"] not in periods.OUTCOME:
        return
    if not exact:
        one = {}
        for fid, q in cited.items():
            one.setdefault(q, fid)
        shown = " vs ".join(f"{fmt(facts[fid]['value'], '%')} in {q.label}" for q, fid in one.items())
        r["downgraded_from"], r["verdict"] = r["verdict"], "unverifiable"
        r["why"] = f"Only rounded margins are available ({shown}), and they can't settle a margin comparison."
        r["delivered"] = "No exact margin figure in the sources for the quarters compared."
        r["margin_check"] = {"result": "rounded_only", "quarters": [q.label for q in quarters]}
        return
    if not promise or promise.kind != "quarter" or len(quarters) != 2 or promise.start not in exact:
        return
    said = " ".join(str(x or "") for x in (r.get("subject"), r.get("promise"),
                                            *(guidance[g].get("target") for g in r["guidance_ids"] if g in guidance)))
    if not _RAISE.search(said) or _LOWER.search(said):  # only "raise above that level" promises are decided here
        return
    base_q = next(q for q in quarters if q != promise.start)
    t, b = facts[exact[promise.start]], facts[exact[base_q]]
    above = t["value"] > b["value"]
    r["margin_check"] = {"result": "above" if above else "not_above", "target": {"period": promise.label, "value": t["value"], "fact": t["id"]},
                         "base": {"period": base_q.label, "value": b["value"], "fact": b["id"]}}
    verdict = "delivered" if above else "missed"
    if verdict != r["verdict"]:
        r["downgraded_from"], r["verdict"] = r["verdict"], verdict
        r["why"] = (f"Exact EBITDA margin: {fmt(t['value'], '%')} in {promise.label} vs {fmt(b['value'], '%')} in "
                    f"{base_q.label} — {'above' if above else 'not above'} the {base_q.label} level.")
        r["delivered"] = f"EBITDA margin {fmt(t['value'], '%')} in {promise.label} ({fmt(b['value'], '%')} in {base_q.label})."


# A fiscal label in a title, matched whole — including year ranges ("FY26-27", "FY2026–27"), which mean the later year.
_FY_LABEL = r"FY\s?'?\d{2,4}(?:\s?[-–/]\s?'?\d{2,4})?"
_PERIOD_LABEL = re.compile(rf"\b(?:(?:Q[1-4]|H[12])\s?)?{_FY_LABEL}\b", re.I)


def _overlap(a: periods.Period, b: periods.Period) -> bool:
    return a.start <= b.end and b.start <= a.end


def _subject_guard(r: dict, guidance: dict) -> None:
    """The row's title must name a period the promise is about. A model-written subject such as "Q2 FY27 sequential
    EBITDA margin improvement" for a promise only ever about H2 FY27 is retitled "H2 FY27 …".

    Left alone: a title with no fiscal label; one whose period overlaps ANY guidance item in the row (an original
    period the promise was first made for, or a comparison period alongside it); and every goalposts_moved / dropped
    row, whose title naming the original period is the point. Only the label changes — never the verdict."""
    if r.get("verdict") in ("goalposts_moved", "dropped"):
        return
    promise = _promise(r, guidance)
    subject = r.get("subject") or ""
    named = [(m, periods.resolve(m.group(0), None)) for m in _PERIOD_LABEL.finditer(subject)]
    named = [(m, p) for m, p in named if p]
    if not promise or not named:
        return
    said = [p for g in r["guidance_ids"] if g in guidance and (p := periods.promise_period(guidance[g]))] or [promise]
    if any(_overlap(p, g) for _, p in named for g in said):
        return
    m = named[0][0]
    r["subject_corrected_from"] = subject
    r["subject"] = subject[:m.start()] + promise.label + subject[m.end():]


def _horizon_guard(r: dict, guidance: dict, latest_quarter: str) -> None:
    """'Missed' means the deadline has passed. If the latest guidance on this promise still has an open horizon
    (a future fiscal year, 'medium term', 'next N years'), the honest verdict is 'at_risk'."""
    if r["verdict"] != "missed":
        return
    latest = periods.from_calendar(latest_quarter)
    promise = _promise(r, guidance)
    if promise and latest:  # resolved period: the deadline is its last quarter
        if promise.end > latest:
            r["downgraded_from"], r["verdict"] = "missed", "at_risk"
            r["why"] = f"The promise's period ({promise.label}) has not ended, so it cannot be missed yet. " + (r.get("why") or "")
        return
    fy = latest.fy if latest else None
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
