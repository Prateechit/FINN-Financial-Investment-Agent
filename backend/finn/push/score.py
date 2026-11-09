"""Materiality score (0–100) with human-readable reasons. Deterministic so every rank is explainable."""
import re

BASE = {
    "results": 80, "M&A": 72, "fund_raise": 65, "management_change": 45, "litigation": 68, "insider_trading": 45,
    "earnings_call": 25, "investor_meetings": 12, "credit_rating": 40, "dividend": 38, "bonus_split": 55, "capex": 60,
    "press_release": 35, "postal_ballot": 18, "agm_egm": 18, "pledging": 62, "unclassified": 6,
}

# (category or "*", regex, adjustment, reason). Applied in order; all matches count.
ADJUST = [
    ("results", r"newspaper|publication", -62, "Newspaper ad of results already filed"),
    ("results", r"investor presentation|earnings presentation", -35, "Results deck (numbers are in the main filing)"),
    ("results", r"corrigendum|revised|clarification", -40, "Correction / clarification to results"),
    ("results", r"intimation|to consider|will be held|is scheduled", -55, "Only a notice of an upcoming board meeting"),
    ("management_change", r"chief executive|\bceo\b|managing director|\bmd\b|chief financial|\bcfo\b|chairman|whole[- ]time director|chief operating|\bcoo\b",
     35, "Top-management role (CEO/MD/CFO/Chair)"),
    ("management_change", r"demise", 40, "Death of a key person"),
    ("management_change", r"independent director|non[- ]executive", -10, "Board-level, non-executive role"),
    ("management_change", r"company secretary|compliance officer|senior management personnel|\bsmp\b", -20, "Junior KMP change"),
    ("management_change", r"re-?appoint", -15, "Re-appointment, not a change"),
    ("credit_rating", r"downgrad|negative|watch with negative", 45, "Rating downgrade / negative outlook"),
    ("credit_rating", r"upgrad|positive", 25, "Rating upgrade / positive outlook"),
    ("credit_rating", r"reaffirm|re-affirm|retained", -20, "Rating reaffirmed — no change"),
    ("credit_rating", r"withdraw", -15, "Rating withdrawn (often debt repaid)"),
    ("litigation", r"insolvency|nclt|fraud|forensic|default|arrest|search|seizure", 22, "Insolvency / fraud / default signal"),
    ("litigation", r"penalty of rs\.? ?[0-9,]{1,7}(\.\d+)?/?-? |no material impact|not material", -30, "Company says impact is immaterial"),
    ("M&A", r"incorporat|name change|strike[- ]off", -45, "Subsidiary housekeeping, not a deal"),
    ("M&A", r"completion|completed|consummat", -10, "Completion of a previously announced deal"),
    ("M&A", r"open offer|demerg|amalgamat|merger", 10, "Structural change to the company"),
    ("fund_raise", r"buy[- ]?back", 8, "Buyback — capital returned to shareholders"),
    ("fund_raise", r"\bqip\b|qualified institution|preferential|rights issue", 8, "Equity dilution"),
    ("fund_raise", r"commercial paper|\bncd|debenture|non[- ]convertible", -30, "Routine debt issuance"),
    ("earnings_call", r"transcript", 20, "Transcript — updates the Promise Ledger"),
    ("earnings_call", r"audio|recording|link", -10, "Call recording link"),
    ("insider_trading", r"promoter", 12, "Promoter-group transaction"),
    ("insider_trading", r"sold|sale|disposal|offer for sale", 8, "Insider selling"),
    ("pledging", r"release|revoc", -22, "Pledge released"),
    ("pledging", r"creation|invocation|invoked", 15, "New pledge / pledge invoked"),
    ("press_release", r"rumou?r|news (item|verification)|clarification", 20, "Exchange-sought clarification on news"),
    ("press_release", r"spurt in volume|price movement", 10, "Exchange query on unusual trading"),
    ("press_release", r"order|contract", 12, "Order win / contract"),
    ("press_release", r"fire|strike|lockout|disruption|closure|suspension|cancell", 30, "Operational disruption"),
    ("press_release", r"monthly business update|production|sales volume", 5, "Monthly operating data"),
    ("dividend", r"special dividend", 15, "Special dividend"),
    ("unclassified", r"resignation of statutory auditor|auditor.*resign", 69, "Auditor resigned mid-term — governance red flag"),
    ("unclassified", r"related party", 20, "Material related-party transaction"),
    ("unclassified", r"deviation|variation", 10, "Statement of deviation in use of funds"),
]
_ADJ = [(c, re.compile(p, re.I), a, r) for c, p, a, r in ADJUST]


def tier(score: int) -> str:
    return "critical" if score >= 75 else "notable" if score >= 45 else "routine"


def score(category: str, exch_category: str, text: str, weight: float = 0.0, price_move_pct: float | None = None,
          move_threshold: float = 4.0, annual_revenue_cr: float | None = None) -> tuple[int, list[str]]:
    s = BASE.get(category, 10)
    reasons = [f"{category.replace('_', ' ')} base {s}"]
    blob = f"{exch_category} {text}"
    for c, rx, adj, why in _ADJ:
        if c == category and rx.search(blob):
            s += adj
            reasons.append(f"{why} ({adj:+d})")
    if category == "litigation" and (pen := penalty_adjustment(blob, annual_revenue_cr)):
        s += pen[0]
        reasons.append(f"{pen[1]} ({pen[0]:+d})")
    if weight and s >= 30:
        bump = round(min(8, weight * 0.8))
        if bump:
            s += bump
            reasons.append(f"{weight:.1f}% of portfolio (+{bump})")
    if price_move_pct is not None and abs(price_move_pct) >= move_threshold and s >= 30:
        s += 10
        reasons.append(f"Stock moved {price_move_pct:+.1f}% that day (+10)")
    return max(0, min(100, s)), reasons


_PENALTY = re.compile(r"penalt(?:y|ies)[^.]{0,90}?(?:rs\.?|inr|₹)\s?([\d,]+(?:\.\d+)?)\s*(crores?|cr\b|lakhs?|lacs?|million)?", re.I)


def penalty_cr(text: str) -> float | None:
    """Largest penalty amount stated in the text, in ₹ crore."""
    best = None
    for m in _PENALTY.finditer(text or ""):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        cr = v if unit.startswith("cr") else v / 100 if unit.startswith(("lakh", "lac")) else v / 10 if unit == "million" else v / 1e7
        best = cr if best is None else max(best, cr)
    return best


def penalty_adjustment(text: str, annual_revenue_cr: float | None) -> tuple[int, str] | None:
    p = penalty_cr(text)
    if p is None or not annual_revenue_cr:
        return None
    share = p / annual_revenue_cr * 100
    amount = f"₹{p * 100:,.2f} lakh" if p < 1 else f"₹{p:,.1f} Cr"
    if share < 0.05:
        pct = "<0.001%" if share < 0.001 else f"{share:.3f}%"
        return -45, f"Penalty {amount} = {pct} of annual revenue — immaterial"
    if share > 1:
        return 15, f"Penalty {amount} = {share:.1f}% of annual revenue"
    return 0, f"Penalty {amount} = {share:.2f}% of annual revenue"
