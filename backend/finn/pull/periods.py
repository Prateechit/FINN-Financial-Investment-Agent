"""Indian fiscal calendar — the one place FINN converts between calendar months, fiscal quarters and the periods
management talks about.

FY26 runs Apr 2025 – Mar 2026: Q1 = Apr–Jun, Q2 = Jul–Sep, Q3 = Oct–Dec, Q4 = Jan–Mar. So "Mar 2026" is Q4 FY26 and
"Sep 2026" is Q2 FY27. A bare "Q4" on an earnings call means the next Q4 from the call's point of view.
"""
import datetime as dt
import re
from dataclasses import dataclass

_MONTH = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
_ABBR = {v: k.title() for k, v in _MONTH.items()}
OUTCOME = ("delivered", "missed", "on_track", "at_risk")


@dataclass(frozen=True, order=True)
class FQ:
    """A fiscal quarter. fy is the two-digit fiscal year (26 = FY26, ending Mar 2026); q is 1–4."""
    fy: int
    q: int

    @property
    def label(self) -> str:
        return f"Q{self.q} FY{self.fy:02d}"

    @property
    def calendar(self) -> str:
        """Quarter-end month as screener labels it: Q4 FY26 → 'Mar 2026'."""
        month = {1: 6, 2: 9, 3: 12, 4: 3}[self.q]
        return f"{_ABBR[month]} {2000 + self.fy - (0 if self.q == 4 else 1)}"

    def shift(self, n: int) -> "FQ":
        i = self.fy * 4 + (self.q - 1) + n
        return FQ(i // 4, i % 4 + 1)

    def prev(self) -> "FQ":
        return self.shift(-1)

    def year_ago(self) -> "FQ":
        return self.shift(-4)


@dataclass(frozen=True)
class Period:
    kind: str  # "quarter" | "half" | "year" | "ytd"
    start: FQ
    end: FQ
    label: str

    def contains(self, fq: FQ) -> bool:
        return self.start <= fq <= self.end

    def covers(self, other: "Period") -> bool:
        return self.start <= other.start and other.end <= self.end


def from_date(d: dt.date) -> FQ:
    return FQ((d.year + 1 if d.month >= 4 else d.year) % 100, ((d.month - 4) % 12) // 3 + 1)


def from_calendar(period: str) -> FQ | None:
    """'Mar 2026' → Q4 FY26; 'Sep 2026' → Q2 FY27."""
    m = re.fullmatch(r"\s*([A-Za-z]{3})\w*\s+(\d{4})\s*", period or "")
    if not m or m.group(1).upper() not in _MONTH:
        return None
    return from_date(dt.date(int(m.group(2)), _MONTH[m.group(1).upper()], 1))


def from_label(label: str) -> FQ | None:
    """'Q4 FY26' / 'Q4FY26' / "Q4 FY'26" / 'Q4 FY2026' → Q4 FY26."""
    m = re.search(r"\bQ([1-4])\s*(?:OF\s+)?FY\s?'?(\d{2,4})\b", (label or "").upper())
    return FQ(int(m.group(2)) % 100, int(m.group(1))) if m else None


def quarter(fq: FQ) -> Period:
    return Period("quarter", fq, fq, fq.label)


def half(fy: int, h: int) -> Period:
    return Period("half", FQ(fy, 1 if h == 1 else 3), FQ(fy, 2 if h == 1 else 4), f"H{h} FY{fy:02d}")


def year(fy: int) -> Period:
    return Period("year", FQ(fy, 1), FQ(fy, 4), f"FY{fy:02d}")


def quarter_discussed(call_date: dt.date) -> FQ:
    """The quarter an earnings call reports: a call in Nov discusses the Sep quarter, Feb → Dec, May → Mar, Aug → Jun."""
    return from_date(call_date).prev()


_FY = r"FY\s?'?(\d{2,4})(?:\s?[-–/]\s?'?(\d{2,4}))?"  # FY26, FY'26, FY2026, FY26-27 (= FY27)


def _fy_value(m: re.Match, first: int) -> int:
    return int(m.group(first + 1) or m.group(first)) % 100


def resolve(horizon: str | None, call: str | FQ | None) -> Period | None:
    """The fiscal period a promise is about, from its stated horizon and the call it was made on.

    Explicit periods ("Q3 FY27", "H2 FY27", "FY27") stand. A bare "Q4"/"H2" is the next such period from the quarter
    in progress at the time of the call (a Q3 FY26 call happens during Q4 FY26, so its "Q4" is Q4 FY26, and a Q4 FY26
    call's "Q1" is Q1 FY27). "Current/this fiscal" and "next fiscal" resolve to fiscal years. Anything vaguer
    ("medium term", "next 2–3 years") returns None.
    """
    h = re.sub(r"\s+", " ", (horizon or "").upper())
    if not h:
        return None
    discussed = from_label(call) if isinstance(call, str) else call
    current = discussed.shift(1) if discussed else None  # the quarter in progress when the call took place

    m = re.search(rf"\bQ([1-4])\b\s*(?:OF\s+)?(?:{_FY})?", h) or re.search(rf"\bQ([1-4])(?:{_FY})", h)
    if m:
        q = int(m.group(1))
        if m.group(2):
            return quarter(FQ(_fy_value(m, 2), q))
        if current:
            fq = FQ(current.fy, q)
            return quarter(fq if fq >= current else FQ(current.fy + 1, q))
        return None

    m = re.search(rf"\b(?:H([12])|(FIRST|SECOND) HALF)\b\s*(?:OF\s+)?(?:{_FY})?", h)
    if m:
        hh = int(m.group(1)) if m.group(1) else (1 if m.group(2) == "FIRST" else 2)
        if m.group(3):
            return half(_fy_value(m, 3), hh)
        if current:
            p = half(current.fy, hh)
            return p if p.end >= current else half(current.fy + 1, hh)
        return None

    if current and re.search(r"\b(CURRENT|THIS) (FISCAL|FINANCIAL YEAR)\b", h):
        return year(current.fy)
    if current and re.search(r"\bNEXT (FISCAL|FINANCIAL YEAR)\b", h):
        return year(current.fy + 1)
    years = [_fy_value(x, 1) for x in re.finditer(_FY, h)]
    if years and not re.search(r"\b(MEDIUM|LONG)[- ]TERM\b|\bYEARS\b", h):
        return year(max(years))
    return None


def fact_period(fid: str, period: str | None) -> Period | None:
    """Fiscal period of a FINN fact. Quarterly series (Q., calc.Q., X.) are quarters; a March value of an annual
    series (A., calc.capex, calc.roa, …) is that fiscal year. TTM and multi-year spans have no single period."""
    p = (period or "").strip()
    if fq := from_label(p):
        return quarter(fq)
    if m := re.fullmatch(r"FY(\d{2}) YTD \((\d)Q\)", p):
        fy = int(m.group(1))
        return Period("ytd", FQ(fy, 1), FQ(fy, int(m.group(2))), f"FY{fy:02d} YTD")
    fq = from_calendar(p)
    if not fq:
        return None
    if fid.startswith(("Q.", "calc.Q.", "X.")) or fq.q != 4:
        return quarter(fq)
    return year(fq.fy)


def tag(fid: str, period: str | None) -> str | None:
    """Fiscal label to show next to a fact ('Q4 FY26', 'FY26', 'FY27 YTD'); None when the id already says it."""
    p = fact_period(fid, period)
    return None if p is None or p.label in fid else p.label


def promise_period(g: dict) -> Period | None:
    """Period of a guidance item: the stored resolved period if present, else resolved from horizon + call."""
    return resolve(g.get("period") or g.get("horizon"), g.get("call"))


def latest_promise(items: list[dict]) -> Period | None:
    """Period a ledger row's promise is about: from its most recent guidance item (by call) that names one."""
    for g in sorted(items, key=lambda g: from_label(g.get("call") or "") or FQ(0, 1), reverse=True):
        if p := promise_period(g):
            return p
    return None


def check(verdict: str, promise: Period | None, cited: list[tuple[str, Period | None]], latest: FQ | None):
    """Is this verdict judged on the promise's own period? Returns None, or (new_verdict, reason).

    - A quarter or half-year promise that hasn't started yet can only be 'too_early'.
    - A quarter or half-year promise that has ended must cite at least one figure from inside that period; the
      quarter before (sequential base) or a year earlier may be cited alongside, but not instead.
    - A fiscal-year promise judged 'delivered'/'missed' must cite a figure from that fiscal year. (A future fiscal
      year is a deadline — current figures can show the trend — so it is not forced to 'too_early'.)
    """
    if promise is None or latest is None or verdict not in OUTCOME:
        return None
    dated = [(fid, p) for fid, p in cited if p is not None]
    named = ", ".join(sorted({p.label for _, p in dated})) or "no dated period"
    if promise.kind in ("quarter", "half"):
        if promise.start > latest:
            return "too_early", f"{promise.label} hasn't started yet — the latest reported quarter is {latest.label}."
        if promise.end <= latest and not any(promise.covers(p) for _, p in dated if p.kind == "quarter"):
            return "unverifiable", f"The cited figures are for {named}, not the promised {promise.label}."
    elif promise.kind == "year" and promise.end <= latest and verdict in ("delivered", "missed"):
        if dated and not any(promise.covers(p) for _, p in dated):
            return "unverifiable", f"The cited figures are for {named}, not the promised {promise.label}."
    return None
