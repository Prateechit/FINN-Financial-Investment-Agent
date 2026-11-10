"""Deterministic consistency checks on the memo's model-written prose.

The ledger and thesis models write sentences; the ledger's code guards then fix verdicts. Nothing made the prose agree
with the fixed verdicts or with the figures a sentence cites. These checks do, without a model call:

  - comparison wording: "sequential(ly)" / "quarter-on-quarter" describing the cited figures must rest on adjacent
    quarters, "year-on-year" on the same quarter a year apart (Q2 FY27 vs Q2 FY26 is year-on-year, never sequential);
    the words may still name a promise ("guidance for sequential margin improvement");
  - one series: the % figures a point quotes for one metric must come from one data series (the exchange filing's
    9.1% and the standardised statements' 2.4% are not one revenue-growth trend);
  - period labels: a figure is labelled with its own reporting period (the FY26 ROA is not "1.7% in Sep 2026");
  - promise status: a point may say a promise is met / validated / delivered only if every promise it cites is
    "delivered" in the ledger — a "too_early" promise (e.g. H2 FY27, not started) has not been tested — and may say
    one failed / was missed only if a promise it cites is "missed" (an "at_risk" promise has not failed);
  - the ledger's credibility summary: "missed X" / "hit X" must match X's final verdict, else FINN writes the summary
    from the verdicts themselves.
"""
import re

from . import periods

# ---------- comparison wording ----------

_SEQUENTIAL = re.compile(r"\bsequential(?:ly)?\b|\bquarter[- ]on[- ]quarter\b|\bq-?o-?q\b|\bfrom the (?:previous|prior|preceding) quarter\b", re.I)
_YEAR_ON_YEAR = re.compile(r"\byear[- ]on[- ]year\b|\by-?o-?y\b|\bfrom a year (?:earlier|ago)\b", re.I)


# Metric of a fact id, whatever its source: "calc.Q.pat_qoq.Sep 2026" → ("pat", "qoq"); "X.pat_yoy.Q2 FY27" →
# ("pat", "yoy"); "X.EBITDA margin.Q2 FY27", "calc.Q.ebitda_margin.Sep 2026" and "Q.OPM %.Sep 2026" → ("ebitda margin",
# None). A *_qoq / *_yoy fact is itself a comparison — one figure is enough evidence for it.
_METRIC_ALIAS = {"sales": "revenue", "revenues": "revenue", "net profit": "pat", "opm": "ebitda margin",
                 "operating margin": "ebitda margin"}


def _metric(fid: str) -> tuple[str, str | None]:
    body = re.sub(r"^(?:calc\.Q\.|calc\.|X\.|Q\.|A\.)", "", fid.rsplit(".", 1)[0])
    kind = None
    if m := re.search(r"[_ ](qoq|yoy)$", body, re.I):
        kind, body = m.group(1).lower(), body[:m.start()]
    name = re.sub(r"\s+", " ", body.replace("_", " ").replace("%", "")).strip().lower()
    return _METRIC_ALIAS.get(name, name), kind


class _Evidence:
    """Per metric: is there sequential evidence (adjacent quarters, or a QoQ figure) and year-on-year evidence (the same
    quarter a year apart, or a YoY figure) among the cited facts — including the figures a cited signal is computed
    from (S3 "2.4% YoY → 9.4%" is year-on-year evidence)?"""

    def __init__(self, evidence: list[dict]):
        quarters: dict[str, set] = {}
        self.seq: dict[str, str] = {}   # metric → description of the sequential evidence
        self.yoy: dict[str, str] = {}   # metric → description of the year-on-year evidence
        self.adjacent: dict[str, tuple] = {}
        self.year_apart: dict[str, tuple] = {}
        for e in _figures(evidence):
            fid = str(e.get("id") or "")
            if "." not in fid:
                continue
            metric, kind = _metric(fid)
            p = periods.fact_period(fid, e.get("period"))
            label = p.label if p else e.get("period")
            if kind == "qoq":
                self.seq.setdefault(metric, f"the {label} quarter-on-quarter {metric} change")
            elif kind == "yoy":
                self.yoy.setdefault(metric, f"the {label} year-on-year {metric} change")
            elif p and p.kind == "quarter":
                quarters.setdefault(metric, set()).add(p.start)
        for metric, qs in quarters.items():
            for a in sorted(qs):
                for b in sorted(qs):
                    if b == a.shift(1):
                        self.adjacent.setdefault(metric, (a, b))
                        self.seq.setdefault(metric, f"a {b.label} vs {a.label} comparison")
                    if b == a.shift(4):
                        self.year_apart.setdefault(metric, (a, b))
                        self.yoy.setdefault(metric, f"a {b.label} vs {a.label} comparison")
        self.metrics = set(quarters) | set(self.seq) | set(self.yoy)


# How a clause names a metric. "PAT margin" is not "PAT"; a bare "margin" means whichever margin was cited.
_MENTION = {"pat margin": r"\b(?:pat|net profit|profit)\s+margins?\b",
            "ebitda margin": r"\b(?:ebitda|operating)\s+margins?\b|\bopm\b",
            "revenue": r"\b(?:revenues?|sales|top[- ]line)\b",
            "pat": r"\b(?:pat|net profit|profits?)\b(?!\s+margins?)"}


def _named_metrics(clause: str, cited: set) -> set:
    named = {m for m in cited if re.search(_MENTION.get(m, r"\b" + re.escape(m) + r"\b"), clause, re.I)}
    if not any("margin" in m for m in named) and re.search(r"\bmargins?\b", clause, re.I):
        named |= {m for m in cited if "margin" in m and not re.search(r"\b(?:pat|net profit|profit)\s+margins?\b", clause, re.I)}
    return named


# "Sequential" can name a management promise rather than describe the cited figures: "consistent with guidance for
# sequential margin improvement", "the H2 FY27 sequential improvement promise is untested". Within a clause, a mention
# preceded by a promise/guidance word, or followed within three words by a promise noun, is about the promise.
_CLAUSE_BREAK = re.compile(r"[;,:()]|\s[—–-]\s|\b(?:while|whereas|but)\b", re.I)
_PROMISE_BEFORE = re.compile(r"\b(?:promis\w*|guid\w*|target\w*|goals?|commit\w*|pledg\w*|outlook|expect\w*|aim\w*|plan\w*)\b", re.I)
_PROMISE_AFTER = re.compile(r"^\W*(?:[\w‑-]+\W+){0,3}?(?:promise|guidance|target|goal|commitment|pledge|outlook)s?\b", re.I)


def _figure_clauses(rx: re.Pattern, point: str) -> list[str]:
    """Clauses in which a mention of this comparison type describes the figures (not a promise)."""
    out = []
    for clause in _CLAUSE_BREAK.split(point):
        for m in rx.finditer(clause or ""):
            if not (_PROMISE_BEFORE.search(clause[:m.start()]) or _PROMISE_AFTER.match(clause[m.end():])):
                out.append(clause)
                break
    return out


def _mislabelled(rx: re.Pattern, point: str, ev: _Evidence, wrong: dict, right: dict) -> str | None:
    """A clause using this comparison word about a metric whose cited evidence is only the other kind of comparison.
    The metric is the one the clause names; if it names none of the cited metrics, the whole point's evidence decides."""
    for clause in _figure_clauses(rx, point):
        metrics = _named_metrics(clause, ev.metrics) or (ev.metrics if not right else set())
        for metric in sorted(metrics):
            if metric in wrong and metric not in right:
                return wrong[metric]
    return None


def comparison_issue(point: str, evidence: list[dict]) -> str | None:
    ev = _Evidence(evidence)
    if what := _mislabelled(_SEQUENTIAL, point, ev, ev.yoy, ev.seq):
        return f"Calls {what} sequential; the same quarter a year apart is year-on-year."
    if what := _mislabelled(_YEAR_ON_YEAR, point, ev, ev.seq, ev.yoy):
        return f"Calls {what} year-on-year; adjacent quarters are sequential."
    return None


# ---------- promise status ----------

_ACHIEVED = (r"(?:validat|vindicat|deliver|achiev|fulfil|honou?r|confirm|meet|met\b|kept\b|keep|hit\b|beat)\w*")
_PROMISE = r"(?:promise|guidance|target|goal|commitment|pledge)s?"
_CLAIMS_ACHIEVED = re.compile(rf"\b{_ACHIEVED}\s+(?:[\w'’‑-]+\s+){{0,5}}?{_PROMISE}\b|\b{_PROMISE}\s+(?:[\w'’‑-]+\s+){{0,4}}?(?:was\s+|were\s+|is\s+|has been\s+|been\s+)?{_ACHIEVED}", re.I)
_NEGATED = re.compile(r"\b(?:not|never|no|yet to|fail\w*|short of|without|cannot|can't|can’t)\s+(?:\w+\s+){0,2}$", re.I)
_STATUS = {"too_early": "too early to judge", "unverifiable": "not verifiable from the sources", "missed": "missed",
           "at_risk": "at risk", "on_track": "on track but not yet delivered", "dropped": "dropped",
           "goalposts_moved": "softened or pushed out"}


_NEGATION_INSIDE = re.compile(r"\b(?:not|never|no|yet to|n't|n’t|fail\w*|cannot)\b", re.I)


def _cited_promises(refs: list[str], ledger_rows: dict[str, dict]) -> list[dict]:
    """Ledger rows a point cites: directly (L3) or through a guidance item a row is built on (G5.2)."""
    rows = [ledger_rows[r] for r in refs if r in ledger_rows]
    rows += [row for row in ledger_rows.values() if set(refs) & set(row.get("guidance_ids") or []) and row not in rows]
    return rows


# A failure assertion about a promise — "failing stability targets", "missed the guided range", "target not met".
_FAILED = (r"(?:fail(?:s|ed|ing|ure)?|miss(?:es|ed|ing)?|f[ae]ll(?:s|ing)?\s+short\s+of|not\s+(?:been\s+)?"
           r"(?:achieved|met|delivered|kept)|unmet|undelivered|broke|broken|breach(?:es|ed|ing)?)")
_FAIL_TARGET = rf"(?:{_PROMISE}|guid(?:ed|ance)\s+(?:range|levels?))"
# After the promise noun, "missing" describes something else ("targets remain unverifiable due to missing data").
_FAILED_AFTER = _FAILED.replace("miss(?:es|ed|ing)?", "miss(?:es|ed)?")
_CLAIMS_FAILED = re.compile(rf"\b{_FAILED}\s+(?:[\w'’‑-]+\s+){{0,5}}?{_FAIL_TARGET}\b|\b{_PROMISE}\s+(?:[\w'’‑-]+\s+){{0,4}}?"
                            rf"(?:was\s+|were\s+|is\s+|are\s+|has\s+been\s+|have\s+been\s+|been\s+|remains?\s+)?{_FAILED_AFTER}\b", re.I)


def _offending_claim(point: str, refs: list[str], evidence: list[dict], ledger_rows: dict[str, dict],
                     latest: periods.FQ | None):
    """The first claim in the point that a promise was met — or failed — which its ledger verdict contradicts.

    A "met" claim needs every promise it cites to be delivered; a "failed / missed" claim needs a cited promise that
    is actually missed (an at_risk or too_early promise has not failed). A cited guidance item about a period that
    hasn't started can be neither. Returns (match, cited rows the claim misjudges, issue) or None."""
    rows = _cited_promises(refs, ledger_rows)
    unstarted = [p for e in evidence if e.get("type") == "guidance" and latest
                 and (p := periods.promise_period(e)) and p.start > latest]
    for kind, rx, verdict in (("met", _CLAIMS_ACHIEVED, "delivered"), ("failed", _CLAIMS_FAILED, "missed")):
        for m in rx.finditer(point):
            if _NEGATED.search(point[:m.start()]) or (kind == "met" and _NEGATION_INSIDE.search(m.group(0))):
                continue
            wrong = [r for r in rows if r.get("verdict") != verdict]
            if kind == "failed" and any(r.get("verdict") == "missed" for r in rows):
                wrong = []  # the failure claim is about the promise that was missed
            said = "is met" if kind == "met" else "failed or was missed"
            if wrong:
                row = wrong[0]
                p = periods.latest_promise(row.get("evidence") or [])
                when = f" ({p.label} hasn't started)" if p and latest and p.start > latest else ""
                return m, wrong, (f"Says a promise {said}, but the ledger marks '{row.get('subject')}' "
                                  f"{_STATUS.get(row.get('verdict'), row.get('verdict'))}{when}.")
            if unstarted and not rows:
                return m, [], f"Says a promise {said}, but the promise is about {unstarted[0].label}, which hasn't started."
    return None


def promise_issue(point: str, refs: list[str], evidence: list[dict], ledger_rows: dict[str, dict],
                  latest: periods.FQ | None) -> str | None:
    found = _offending_claim(point, refs, evidence, ledger_rows, latest)
    return found[2] if found else None


# ---------- one series per comparison ----------

_PCT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%")


def _figures(evidence: list[dict]) -> list[dict]:
    """Cited figures with values: fact evidence, plus the facts a cited signal is computed from."""
    out = []
    for e in evidence:
        if e.get("type") == "fact" and isinstance(e.get("value"), (int, float)):
            out.append(e)
        out += [f for f in e.get("figures") or [] if isinstance(f.get("value"), (int, float))]
    return out


def series_issue(point: str, evidence: list[dict]) -> str | None:
    """A trend a point draws for one metric must come from one series: when its quoted % figures span several periods,
    one data series must supply a quoted figure for every one of them. "Revenue growth accelerated to 9.1% … up from
    2.4%" pairs the exchange filing's 9.1% (Q2 FY27) with the standardised statements' 2.4% (Q3 FY26), whose own Q2 FY27
    figure is 9.4% — flagged. Quoting both series' figures for the same quarter beside one series' trend ("2.4% → 9.4%,
    alongside 9.1% total income growth") is not a cross-series trend. Nothing is substituted: the issue names what each
    series has."""
    mix = _mixed_series(point, evidence)
    if not mix:
        return None
    metric, kind, facts, used = mix
    source = lambda f: "exchange filing" if f["id"].startswith("X.") else "standardised statements"  # noqa: E731
    shown = " and ".join(f"{v:g}% ({q.label}, {source(f)})" for _, q, v, f in sorted(used, key=lambda u: -u[2]))
    alt = [f"the {source(f)} {'gives' if f['id'].startswith('X.') else 'give'} {f['value']:g}% for {q.label}"
           for s, q, v, f in facts if (s, q) not in {(s2, q2) for s2, q2, _, _ in used}
           and q in {q2 for s2, q2, _, _ in used if s2 != s}]
    name = f"{metric} growth ({kind.upper()})" if kind else metric
    return (f"Mixes two {name} series: {shown}. Compare figures from one series"
            + (f" — {'; '.join(dict.fromkeys(alt))}." if alt else "."))


def _mixed_series(point: str, evidence: list[dict]):
    """The first metric whose quoted figures form a cross-series trend: (metric, kind, all its cited figures, the quoted
    ones), each figure as (series, quarter, |value|, fact). None if every trend comes from one series."""
    quoted = {round(float(x), 2) for x in _PCT.findall(point)}
    if len(quoted) < 2:
        return None
    by_metric: dict[tuple, list[tuple]] = {}
    for f in _figures(evidence):
        fid = str(f.get("id") or "")
        p = periods.fact_period(fid, f.get("period")) if "." in fid else None
        if p:
            by_metric.setdefault(_metric(fid), []).append((fid.rsplit(".", 1)[0], p.start, round(abs(float(f["value"])), 2), f))
    for (metric, kind), facts in sorted(by_metric.items(), key=lambda kv: kv[0]):
        series = {s for s, *_ in facts}
        used = list({(s, q, v): (s, q, v, f) for s, q, v, f in facts if v in quoted}.values())
        spanned = {q for _, q, _, _ in used}
        if len(series) < 2 or len(spanned) < 2 or any(all(any(s == one and q == p for s, q, _, _ in used) for p in spanned)
                                                      for one in series):
            continue
        return metric, kind, facts, used
    return None


def _pct_spans(point: str, value: float) -> list[tuple[int, int]]:
    """Where a % figure equal to `value` (to 2 decimals) is written in the point."""
    return [m.span() for m in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%", point) if round(float(m.group(1)), 2) == value]


def _use_one_series(point: str, refs: list[str], evidence: list[dict]):
    """Repair a cross-series trend by moving it onto the one series that has a cited figure for every period the trend
    spans: each figure quoted from the other series is replaced by that series' figure for the same period, and a
    reference cited only for a replaced figure is dropped. The figure comes from the cited evidence — nothing is looked
    up or estimated — and the repair is skipped when it would be ambiguous (no single such series, or the replaced
    figure written more than once or shared with another cited metric). Returns (point, refs, evidence) or None."""
    mix = _mixed_series(point, evidence)
    if not mix:
        return None
    metric, kind, facts, used = mix
    spanned = {q for _, q, _, _ in used}
    targets = [s for s in sorted({s for s, *_ in facts}) if all(any(s2 == s and q == p for s2, q, _, _ in facts) for p in spanned)]
    if len(targets) != 1:
        return None
    target = targets[0]
    all_values = [round(abs(float(f["value"])), 2) for f in _figures(evidence)]
    edits, replaced = [], []
    for s, q, v, f in used:
        if s == target or any(s2 == target and q2 == q and v2 == v for s2, q2, v2, _ in facts):
            continue
        spans = _pct_spans(point, v)
        if len(spans) != 1 or all_values.count(v) > 1:
            return None
        new = next(f2 for s2, q2, _, f2 in facts if s2 == target and q2 == q)
        edits.append((spans[0], f"{abs(float(new['value'])):g}%"))
        replaced.append(f["id"])
    if not edits:
        return None
    for (a, b), text in sorted(edits, reverse=True):
        point = point[:a] + text + point[b:]
    if len(refs) == len(evidence):
        pairs = [(r, e) for r, e in zip(refs, evidence) if not (e.get("type") == "fact" and e.get("id") in replaced)]
        if pairs:
            refs, evidence = [r for r, _ in pairs], [e for _, e in pairs]
    return point, refs, evidence


# ---------- each figure carries its own period ----------

_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_LABEL = rf"(?:Q[1-4]\s?FY\s?'?\d{{2,4}}|H[12]\s?FY\s?'?\d{{2,4}}|FY\s?'?\d{{2,4}}(?:\s?[-–/]\s?'?\d{{2,4}})?|{_MONTHS}\s\d{{4}})"
# A % figure with the period it is attached to: "1.7% in Sep 2026", "2.4% YoY (Dec 2025)", "9.4% YoY in Q2 FY27".
# Only a preposition or bracket attaches a label — "16.1% exceeded Q2 FY26's 15.7%" names Q2 FY26 for the next figure.
_VALUE_LABEL = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s?%\s*(?:(?:YoY|QoQ|y-?o-?y|q-?o-?q|year[- ]on[- ]year|"
                          rf"quarter[- ]on[- ]quarter|sequentially)\s*)?(?:\(\s*|(?:in|for|during|as\s+of|at)\s+)"
                          rf"(?P<label>{_LABEL})(?![\w-])", re.I)


def _fact_fiscal(f: dict) -> periods.Period | None:
    """Fiscal period of a cited figure; annual facts stored with period "FY26" fall back to their id ("… .Mar 2026")."""
    fid = str(f.get("id") or "")
    return periods.fact_period(fid, f.get("period")) or (periods.fact_period(fid, fid.rsplit(".", 1)[1]) if "." in fid else None)


def _label_period(text: str) -> periods.Period | None:
    fq = periods.from_calendar(text)
    return periods.quarter(fq) if fq else periods.resolve(text, None)


def _fits(fact: periods.Period, label: periods.Period) -> bool:
    """Does this label name the figure's own period? An FY figure may also be named by its year-end quarter (Mar
    2026 for FY26), and a year-to-date figure by its fiscal year."""
    if (fact.start, fact.end) == (label.start, label.end):
        return True
    if fact.kind == "year" and label.kind == "quarter" and label.start == fact.end:
        return True
    return fact.kind == "ytd" and label.kind == "year" and label.covers(fact)


def _period_labels(point: str, evidence: list[dict]) -> list[tuple]:
    """Mislabelled figures: (label span, label text, cited facts with that value, their periods), where no cited fact
    with that value has the labelled period."""
    figs = [(round(abs(float(f["value"])), 2), f, p) for f in _figures(evidence) if (p := _fact_fiscal(f))]
    out = []
    for m in _VALUE_LABEL.finditer(point):
        v, label = round(float(m.group(1)), 2), _label_period(m.group("label"))
        cands = [(f, p) for v2, f, p in figs if v2 == v]
        if label and cands and not any(_fits(p, label) for _, p in cands):
            out.append((m.span("label"), m.group("label"), cands))
    return out


def period_label_issue(point: str, evidence: list[dict]) -> str | None:
    """A figure must be labelled with its own reporting period: the FY26 ROA (1.7%) is not "1.7% in Sep 2026"."""
    bad = _period_labels(point, evidence)
    if not bad:
        return None
    _, text, cands = bad[0]
    f, p = cands[0]
    return f"Labels the {p.label} figure {abs(float(f['value'])):g}% ({f['id']}) as {text}; use its own period, {p.label}."


def _relabel_periods(point: str, evidence: list[dict]) -> str:
    """Repair a mislabelled figure by naming its own period, when exactly one cited fact has that value and the wrong
    label appears once: "1.7% in Sep 2026" → "1.7% in FY26" for calc.roa.Mar 2026."""
    for (a, b), text, cands in sorted(_period_labels(point, evidence), key=lambda x: -x[0][0]):
        if len(cands) != 1 or point.count(text) != 1:
            continue
        point = point[:a] + cands[0][1].label + point[b:]
    return point


_CLAUSE_SEP = re.compile(r",\s+|;\s+|\s+[—–]\s+|\s+-\s+")


def trim_unmet_promise_claim(point: str, refs: list[str], evidence: list[dict], ledger_rows: dict[str, dict],
                             latest: periods.FQ | None) -> tuple[str, list[str], list[dict]] | None:
    """Last resort for a point that, after its rewrite, still says a promise was met — or failed — when its ledger
    verdict says otherwise: drop the clause that says so ("…, validating sequential margin improvement guidance";
    "…, failing stability targets") when the rest of the sentence stands on its own as a figure-based claim, and drop
    the references only that clause used (the misjudged promises' ledger rows and guidance).

    Returns (point, refs, evidence) — which must pass every narrative check — or None when the claim is the main
    clause and there is nothing sound to keep. The caller re-verifies the trimmed text.
    """
    found = _offending_claim(point, refs, evidence, ledger_rows, latest)
    if not found:
        return None
    m, wrong, _ = found
    before = [s for s in _CLAUSE_SEP.finditer(point) if s.end() <= m.start()]
    if not before:
        return None
    after = next((s for s in _CLAUSE_SEP.finditer(point) if s.start() >= m.end()), None)
    kept = (point[:before[-1].start()] + (point[after.start():] if after else "")).strip().rstrip(".,;") + "."
    if not re.search(r"\d", kept):
        return None
    wrong_ids = {g for r in wrong for g in r.get("guidance_ids") or []}
    drop = {ref for ref in refs if (ref in ledger_rows and ledger_rows[ref] in wrong) or ref in wrong_ids}
    drop |= {e.get("id") for e in evidence if e.get("type") == "guidance" and latest
             and (p := periods.promise_period(e)) and p.start > latest}
    if len(refs) == len(evidence) and any(r not in drop for r in refs):
        pairs = [(r, e) for r, e in zip(refs, evidence) if r not in drop]
        refs, evidence = [r for r, _ in pairs], [e for _, e in pairs]
    if comparison_issue(kept, evidence) or series_issue(kept, evidence) or period_label_issue(kept, evidence) or \
            promise_issue(kept, refs, evidence, ledger_rows, latest):
        return None
    return kept, refs, evidence


def repair_point(point: str, refs: list[str], evidence: list[dict], ledger_rows: dict[str, dict],
                 latest: periods.FQ | None) -> tuple[str, list[str], list[dict]] | None:
    """Deterministic last-resort repair of a point still flagged after its rewrite, in this order: name each mislabelled
    figure's own period; move a cross-series trend onto the one series covering it; drop a clause that says an
    untested / unmet promise was met, or a not-missed one failed. Every figure used is already cited. Returns the
    repaired (point, refs, evidence) only if it then passes every narrative check — else None (the point stays
    disputed). The caller re-verifies the repaired text."""
    original = point
    point = _relabel_periods(point, evidence)
    if fixed := _use_one_series(point, refs, evidence):
        point, refs, evidence = fixed
    if promise_issue(point, refs, evidence, ledger_rows, latest):
        cut = trim_unmet_promise_claim(point, refs, evidence, ledger_rows, latest)
        if not cut:
            return None
        point, refs, evidence = cut
    if point == original:
        return None
    if comparison_issue(point, evidence) or series_issue(point, evidence) or period_label_issue(point, evidence) or \
            promise_issue(point, refs, evidence, ledger_rows, latest):
        return None
    return point, refs, evidence


def thesis_issues(thesis: dict, ledger: dict, latest: periods.FQ | None) -> dict[str, dict]:
    """{"bull2": {"supported": False, "issue": "…"}} for every bull/bear point that fails a check."""
    led = {f"L{i + 1}": r for i, r in enumerate(ledger.get("rows", []))}
    out = {}
    for side in ("bull", "bear"):
        for i, p in enumerate(thesis.get(side) or []):
            ev = p.get("evidence") or []
            issues = [x for x in (comparison_issue(p["point"], ev), series_issue(p["point"], ev),
                                  period_label_issue(p["point"], ev),
                                  promise_issue(p["point"], p.get("refs") or [], ev, led, latest)) if x]
            if issues:  # every reason goes to the rewrite, so fixing one doesn't leave the other
                out[f"{side}{i + 1}"] = {"supported": False, "issue": " ".join(issues)}
    return out


# ---------- credibility summary ----------

_OUTCOME_WORDS = {
    "missed": re.compile(r"\bmiss(?:ed|es)?\b|\bfell short\b|\bfailed to (?:meet|deliver|hit|achieve)\b", re.I),  # not "missing data"
    "delivered": re.compile(r"\b(?:delivered|delivers|hit|met|achieved|kept|beat)\b", re.I),
}
_CLAUSE = re.compile(r"[.;:]|,?\s*\b(?:but|while|whereas|although|though|yet)\b|,\s*and\b")
_STOP = {"the", "a", "an", "of", "and", "to", "in", "on", "for", "its", "their", "our", "with", "by", "that", "this", "is",
         "was", "were", "has", "have", "had", "be", "been", "management", "managements", "target", "targets", "goal",
         "goals", "guidance", "promise", "promises", "reliably", "consistently", "largely", "mostly", "it", "they",
         "missed", "miss", "misses", "delivered", "hit", "met", "achieved", "kept", "beat", "fell", "short", "failed"}


# Words many promises share; a clause naming only these could be about any of them.
_GENERIC = re.compile(r"^(?:fy\d{2}|q[1-4]|h[12]|margins?|revenues?|growth|profit|operating|ebitda|sequential|run|rate|"
                      r"total|overall|financial|metrics?|yoy|qoq)$")


def _tokens(s: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in _STOP}


def credibility_issue(text: str | None, rows: list[dict]) -> str | None:
    """Does the summary call a promise missed/delivered when the final ledger verdict says otherwise?"""
    if not text:
        return None
    for clause in _CLAUSE.split(text):
        for verdict, rx in _OUTCOME_WORDS.items():
            m = rx.search(clause or "")
            if not m or re.search(r"\b(?:not|never|no|without)\s+(?:\w+\s+)?$", clause[:m.start()], re.I):
                continue
            words = _tokens(clause)
            # A clause can name several promises ("capex targets and operating margins show misses or pressure"):
            # it is consistent if any promise it names by a distinctive word ("capex") has that verdict.
            named = [r for r in rows if any(not _GENERIC.match(t) for t in words & _tokens(r.get("subject")))]
            if any(r.get("verdict") == verdict for r in named):
                continue
            scored = [(len(words & _tokens(r.get("subject"))), r) for r in rows]
            best = max((s for s, _ in scored), default=0)
            about = [r for s, r in scored if s == best and s >= 2]
            if about and not any(r.get("verdict") == verdict for r in about):
                r = about[0]
                return f"Says '{m.group(0)}' about '{r.get('subject')}', which the ledger marks {r.get('verdict')}."
            if not about and not any(r.get("verdict") == verdict for r in rows):
                return f"Says '{m.group(0)}', but no promise in the ledger is {verdict}."
    return None


_SUMMARY = [("delivered", "delivered"), ("missed", "missed"), ("goalposts_moved", "softened or pushed out"),
            ("dropped", "dropped"), ("at_risk", "at risk"), ("on_track", "on track"), ("too_early", "too early to judge")]


def credibility_summary(rows: list[dict]) -> str:
    """The track record stated from the final verdicts — used when the model's summary contradicts them."""
    parts = []
    for verdict, label in _SUMMARY:
        subj = [r["subject"] for r in rows if r.get("verdict") == verdict]
        if subj:
            parts.append(f"{len(subj)} {label} ({'; '.join(subj)})")
    n_unv = sum(1 for r in rows if r.get("verdict") == "unverifiable")
    if n_unv:
        parts.append(f"{n_unv} not verifiable from the filings")
    if not parts:
        return ""
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Of {len(rows)} promise{'s' if len(rows) != 1 else ''} tracked: {body}."
