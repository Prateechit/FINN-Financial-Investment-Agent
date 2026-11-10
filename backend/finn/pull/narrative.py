"""Deterministic consistency checks on the memo's model-written prose.

The ledger and thesis models write sentences; the ledger's code guards then fix verdicts. Nothing made the prose agree
with the fixed verdicts or with the figures a sentence cites. These checks do, without a model call:

  - comparison wording: "sequential(ly)" / "quarter-on-quarter" describing the cited figures must rest on adjacent
    quarters, "year-on-year" on the same quarter a year apart (Q2 FY27 vs Q2 FY26 is year-on-year, never sequential);
    the words may still name a promise ("guidance for sequential margin improvement");
  - promise status: a point may say a promise is met / validated / delivered only if every promise it cites is
    "delivered" in the ledger — a "too_early" promise (e.g. H2 FY27, not started) has not been tested;
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
    quarter a year apart, or a YoY figure) among the cited facts?"""

    def __init__(self, evidence: list[dict]):
        quarters: dict[str, set] = {}
        self.seq: dict[str, str] = {}   # metric → description of the sequential evidence
        self.yoy: dict[str, str] = {}   # metric → description of the year-on-year evidence
        self.adjacent: dict[str, tuple] = {}
        self.year_apart: dict[str, tuple] = {}
        for e in evidence:
            fid = str(e.get("id") or "")
            if e.get("type") != "fact" or "value" not in e or "." not in fid:
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


def _claims_achievement(point: str) -> bool:
    """'validating the promise' — but not 'has not yet validated the promise' / 'promise has not been met'."""
    return any(not _NEGATED.search(point[:m.start()]) and not _NEGATION_INSIDE.search(m.group(0))
               for m in _CLAIMS_ACHIEVED.finditer(point))


def _cited_promises(refs: list[str], ledger_rows: dict[str, dict]) -> list[dict]:
    """Ledger rows a point cites: directly (L3) or through a guidance item a row is built on (G5.2)."""
    rows = [ledger_rows[r] for r in refs if r in ledger_rows]
    rows += [row for row in ledger_rows.values() if set(refs) & set(row.get("guidance_ids") or []) and row not in rows]
    return rows


def promise_issue(point: str, refs: list[str], evidence: list[dict], ledger_rows: dict[str, dict],
                  latest: periods.FQ | None) -> str | None:
    if not _claims_achievement(point):
        return None
    for row in _cited_promises(refs, ledger_rows):
        if row.get("verdict") != "delivered":
            p = periods.latest_promise(row.get("evidence") or [])
            when = f" ({p.label} hasn't started)" if p and latest and p.start > latest else ""
            return (f"Says a promise is met, but the ledger marks '{row.get('subject')}' "
                    f"{_STATUS.get(row.get('verdict'), row.get('verdict'))}{when}.")
    for e in evidence:  # a cited guidance item about a period that hasn't started, even with no ledger row
        if e.get("type") == "guidance" and latest and (p := periods.promise_period(e)) and p.start > latest:
            return f"Says a promise is met, but the promise is about {p.label}, which hasn't started."
    return None


def thesis_issues(thesis: dict, ledger: dict, latest: periods.FQ | None) -> dict[str, dict]:
    """{"bull2": {"supported": False, "issue": "…"}} for every bull/bear point that fails a check."""
    led = {f"L{i + 1}": r for i, r in enumerate(ledger.get("rows", []))}
    out = {}
    for side in ("bull", "bear"):
        for i, p in enumerate(thesis.get(side) or []):
            ev = p.get("evidence") or []
            issues = [x for x in (comparison_issue(p["point"], ev),
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
