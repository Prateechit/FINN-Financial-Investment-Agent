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


def _quarterly_pairs(evidence: list[dict]) -> tuple[list[tuple], list[tuple]]:
    """(adjacent pairs, year-apart pairs) among the cited quarterly figures, per metric."""
    by_metric: dict[str, set] = {}
    for e in evidence:
        fid = str(e.get("id") or "")
        if e.get("type") != "fact" or "value" not in e or "." not in fid:
            continue
        p = periods.fact_period(fid, e.get("period"))
        if p and p.kind == "quarter":
            by_metric.setdefault(fid.rsplit(".", 1)[0], set()).add(p.start)
    adjacent, year_apart = [], []
    for metric, qs in by_metric.items():
        for a in qs:
            for b in qs:
                if b == a.shift(1):
                    adjacent.append((metric, a, b))
                if b == a.shift(4):
                    year_apart.append((metric, a, b))
    return adjacent, year_apart


# "Sequential" can name a management promise rather than describe the cited figures: "consistent with guidance for
# sequential margin improvement", "the H2 FY27 sequential improvement promise is untested". Within a clause, a mention
# preceded by a promise/guidance word, or followed within three words by a promise noun, is about the promise.
_CLAUSE_BREAK = re.compile(r"[;,:()]|\s[—–-]\s|\b(?:while|whereas|but)\b", re.I)
_PROMISE_BEFORE = re.compile(r"\b(?:promis\w*|guid\w*|target\w*|goals?|commit\w*|pledg\w*|outlook|expect\w*|aim\w*|plan\w*)\b", re.I)
_PROMISE_AFTER = re.compile(r"^\W*(?:[\w‑-]+\W+){0,3}?(?:promise|guidance|target|goal|commitment|pledge|outlook)s?\b", re.I)


def _describes_figures(rx: re.Pattern, point: str) -> bool:
    """Does any mention of this comparison type describe the figures (not name a promise)?"""
    for clause in _CLAUSE_BREAK.split(point):
        for m in rx.finditer(clause or ""):
            if not (_PROMISE_BEFORE.search(clause[:m.start()]) or _PROMISE_AFTER.match(clause[m.end():])):
                return True
    return False


def comparison_issue(point: str, evidence: list[dict]) -> str | None:
    adjacent, year_apart = _quarterly_pairs(evidence)
    if _describes_figures(_SEQUENTIAL, point) and year_apart and not adjacent:
        _, a, b = year_apart[0]
        return f"Calls a {b.label} vs {a.label} comparison sequential; the same quarter a year apart is year-on-year."
    if _describes_figures(_YEAR_ON_YEAR, point) and adjacent and not year_apart:
        _, a, b = adjacent[0]
        return f"Calls a {b.label} vs {a.label} comparison year-on-year; adjacent quarters are sequential."
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
