"""Quarterly results card: headline numbers this quarter vs last quarter (QoQ) vs same quarter last year (YoY).

Primary path: NSE XBRL (exact rupee values). Fallback: screener.in quarterly table (₹ Cr).
No LLM is involved; every figure is traceable to a filing.
"""
import datetime as dt

from ..db import kv_get, kv_set
from ..pull import periods
from ..sources import nse, screener

CR = 1e7


def fy_label(d: dt.date) -> str:
    return periods.from_date(d).label


def _shift(d: dt.date, months: int) -> dt.date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _xbrl(url: str) -> dict:
    key = f"xbrl:{url}"
    if (hit := kv_get(key)) is not None:
        return hit
    facts = nse.xbrl_facts(nse.get_bytes(url))
    flat = {k: [[s, e, v] for (s, e), v in d.items()] for k, d in facts.items()}
    kv_set(key, flat)
    return flat


def _quarter_values(flat: dict, qe: dt.date) -> dict[str, float]:
    out = {}
    for k, triples in flat.items():
        for s, e, v in triples:
            if s and e == qe.isoformat():
                days = (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days
                if 80 <= days <= 100:
                    try:
                        out[k] = float(v)
                    except ValueError:
                        pass
    return out


def _kind(v: dict) -> str:
    if "OperatingProfitBeforeProvisionAndContingencies" in v:
        return "bank"
    rev = v.get("RevenueFromOperations") or 0
    if v.get("InterestEarned", 0) > 0.5 * rev and "ImpairmentOnFinancialInstruments" in v:
        return "lender"
    return "industrial"


def _metrics_xbrl(v: dict, kind: str) -> dict[str, float | None]:
    g = lambda k: v.get(k)
    if kind == "bank":
        pat = g("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates") or g("ProfitLossForThePeriod")
        ie, ix = g("InterestEarned"), g("InterestExpended")
        return {"revenue": g("Income") or ((ie or 0) + (g("OtherIncome") or 0)),
                "nii": ie - ix if ie is not None and ix is not None else None,
                "ppop": g("OperatingProfitBeforeProvisionAndContingencies"),
                "provisions": g("ProvisionsOtherThanTaxAndContingencies"),
                "pbt": g("ProfitLossFromOrdinaryActivitiesBeforeTax"), "pat": pat, "tax": g("TaxExpense"),
                "x_rev": ie, "x_pat": g("ProfitLossForThePeriod")}
    pat = g("ProfitLossForPeriod")
    if kind == "lender":
        ie, fc, imp, pbt = g("InterestEarned"), g("FinanceCosts"), g("ImpairmentOnFinancialInstruments"), g("ProfitBeforeTax")
        return {"revenue": g("RevenueFromOperations"), "nii": ie - fc if ie is not None and fc is not None else None,
                "ppop": pbt + imp if pbt is not None and imp is not None else None, "provisions": imp,
                "pbt": pbt, "pat": pat, "tax": g("TaxExpense"), "x_rev": g("RevenueFromOperations"), "x_pat": pat}
    rev, exp, fc, da = g("RevenueFromOperations"), g("Expenses"), g("FinanceCosts"), g("DepreciationDepletionAndAmortisationExpense")
    ebitda = rev - (exp - (fc or 0) - (da or 0)) if rev is not None and exp is not None else None
    return {"revenue": rev, "ebitda": ebitda, "pbt": g("ProfitBeforeTax"), "pat": pat, "tax": g("TaxExpense"),
            "other_income": g("OtherIncome"), "exceptional": g("ExceptionalItemsBeforeTax"),
            "below_line": g("ProfitBeforeTax") - (ebitda - (fc or 0) - (da or 0)) if ebitda is not None and g("ProfitBeforeTax") is not None else None,
            "x_rev": rev, "x_pat": pat}


LABELS = {"revenue": "Revenue", "ebitda": "EBITDA", "nii": "Net interest income", "ppop": "Pre-provision profit",
          "provisions": "Provisions", "pbt": "PBT", "pat": "PAT"}
HEADLINE = {"industrial": ["revenue", "ebitda", "pbt", "pat"],
            "bank": ["revenue", "nii", "ppop", "provisions", "pbt", "pat"],
            "lender": ["revenue", "nii", "ppop", "provisions", "pbt", "pat"]}


def _pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / abs(b) * 100, 1)


def _build(kind, cur, prev, yoy, qe, basis, source, links, notes):
    rows = []
    for k in HEADLINE[kind]:
        c, p, y = (m.get(k) if m else None for m in (cur, prev, yoy))
        label = "Total income" if (k == "revenue" and kind == "bank") else LABELS[k]
        rows.append({"key": k, "label": label, "cur": _cr(c), "prev": _cr(p), "yoy": _cr(y),
                     "qoq_pct": _pct(c, p), "yoy_pct": _pct(c, y)})
    margins = []
    num = "ebitda" if kind == "industrial" else "ppop"
    for k, label in [(num, "EBITDA margin" if kind == "industrial" else "Pre-provision margin"), ("pat", "PAT margin")]:
        vals = [(m[k] / m["revenue"] * 100) if m and m.get(k) is not None and m.get("revenue") else None for m in (cur, prev, yoy)]
        margins.append({"label": label, "cur": _r(vals[0]), "prev": _r(vals[1]), "yoy": _r(vals[2]),
                        "qoq_bps": _bps(vals[0], vals[1]), "yoy_bps": _bps(vals[0], vals[2])})
    checks = []
    if cur and cur.get("pbt") is not None and cur.get("tax") is not None and cur.get("pat") is not None:
        implied = cur["pbt"] - cur["tax"]
        diff = abs(implied - cur["pat"]) / max(abs(cur["pat"]), 1)
        checks.append({"name": "PBT − tax ≈ PAT", "ok": diff < 0.05,
                       "detail": f"PBT−tax = {_cr(implied)} Cr vs PAT {_cr(cur['pat'])} Cr"
                                 + ("" if diff < 0.05 else " (gap = associates/minority/discontinued items)")})
    if kind == "industrial" and cur and yoy and all(m.get(k) is not None for m in (cur, yoy) for k in ("ebitda", "pbt", "below_line")):
        e_g, p_g = _pct(cur["ebitda"], yoy["ebitda"]), _pct(cur["pbt"], yoy["pbt"])
        if e_g is not None and p_g is not None and abs(e_g - p_g) >= 20:
            notes.append(f"EBITDA {e_g:+.0f}% YoY but PBT {p_g:+.0f}% YoY — the gap is below the operating line: "
                         f"other income + exceptional items + associates were ₹{_cr(cur['below_line'])} Cr this quarter "
                         f"vs ₹{_cr(yoy['below_line'])} Cr a year ago.")
    if kind == "industrial" and cur and cur.get("exceptional"):
        notes.append(f"Includes an exceptional item of ₹{_cr(cur['exceptional'])} Cr in PBT.")
    if kind == "industrial" and cur and cur.get("other_income") and cur.get("pbt") and cur["other_income"] > 0.3 * cur["pbt"]:
        notes.append(f"Other income is {cur['other_income'] / cur['pbt'] * 100:.0f}% of PBT — profit quality depends on non-operating income.")
    return {"kind": kind, "basis": basis, "source": source, "links": links, "notes": notes, "checks": checks,
            "quarter": {"label": fy_label(qe), "end": qe.isoformat()},
            "prev_label": fy_label(_shift(qe, -3)), "yoy_label": fy_label(_shift(qe, -12)),
            "rows": rows, "margins": margins, "headline": _headline(rows, margins),
            "_x": {"revenue": _cr(cur.get("x_rev")) if cur else None, "pat": _cr(cur.get("x_pat")) if cur else None}}


def _cr(v):
    return None if v is None else round(v / CR, 1)


def _r(v):
    return None if v is None else round(v, 1)


def _bps(a, b):
    return None if a is None or b is None else round((a - b) * 100)


def _headline(rows, margins) -> str:
    parts = []
    for r in rows:
        if r["key"] in ("revenue", "pat") and r["yoy_pct"] is not None:
            parts.append(f"{r['label']} {r['yoy_pct']:+.0f}% YoY")
    m = margins[0]
    if m["yoy_bps"] is not None:
        parts.append(f"{m['label']} {m['yoy_bps']:+d} bps YoY")
    return " · ".join(parts)


def from_xbrl(symbol: str, qe: dt.date | None = None) -> dict | None:
    filings = nse.results_filings(symbol)
    if not filings:
        return None
    qe = qe or filings[0]["qe"]
    targets = [qe, _shift(qe, -3), _shift(qe, -12)]
    for consolidated in (True, False):
        by_q = {f["qe"]: f for f in filings if f["consolidated"] == consolidated}
        if qe not in by_q:
            continue
        vals = []
        for t in targets:
            f = by_q.get(t)
            vals.append(_quarter_values(_xbrl(f["xbrl"]), t) if f else None)
        if not vals[0]:
            continue
        kind = _kind(vals[0])
        ms = [_metrics_xbrl(v, kind) if v else None for v in vals]
        links = [by_q[t]["xbrl"] for t in targets if t in by_q]
        notes = [] if all(vals) else ["Comparative quarter not available in XBRL; growth shown only where both periods exist."]
        return _build(kind, *ms, qe, "consolidated" if consolidated else "standalone", "NSE XBRL", links, notes)
    return None


def _q_end(label: str) -> dt.date | None:
    try:
        d = dt.datetime.strptime(label, "%b %Y").date()
    except ValueError:
        return None
    return _shift(d.replace(day=1), 0)


def from_screener(symbol: str) -> dict | None:
    c = screener.company(symbol)
    t = c["tables"].get("quarters")
    if not t:
        return None
    ends = [_q_end(x) for x in t["cols"]]
    rows = t["rows"]
    lender = screener.is_lender(c)

    def at(qe):
        if qe not in ends:
            return None
        i = ends.index(qe)
        g = lambda k: None if rows.get(k) is None or rows[k][i] is None else rows[k][i] * CR
        if lender:
            return {"revenue": g("Revenue"), "nii": (g("Revenue") - g("Interest")) if g("Revenue") and g("Interest") else None,
                    "ppop": g("Financing Profit"), "provisions": None, "pbt": g("Profit before tax"), "pat": g("Net Profit"),
                    "tax": None, "x_rev": g("Revenue"), "x_pat": g("Net Profit")}
        ebitda, pbt = g("Operating Profit"), g("Profit before tax")
        below = pbt - (ebitda - (g("Interest") or 0) - (g("Depreciation") or 0)) if ebitda is not None and pbt is not None else None
        return {"revenue": g("Sales"), "ebitda": ebitda, "pbt": pbt, "pat": g("Net Profit"), "tax": None,
                "below_line": below, "x_rev": g("Sales"), "x_pat": g("Net Profit")}

    qe = ends[-1]
    cur = at(qe)
    if not cur:
        return None
    kind = "lender" if lender else "industrial"
    out = _build(kind, cur, at(_shift(qe, -3)), at(_shift(qe, -12)), qe, c["basis"], "screener.in", [c["url"]],
                 ["Figures from screener.in's standardised table; exchange XBRL not yet available."])
    if lender:
        out["notes"].append("Screener's 'Financing Profit' is used as pre-provision profit; provisions not broken out.")
    return out


def results_card(symbol: str) -> dict | None:
    """XBRL first, screener fallback, with a cross-check whenever both cover the same quarter."""
    xb = sc = None
    try:
        xb = from_xbrl(symbol)
    except Exception as e:  # noqa: BLE001 — degrade to the secondary source
        print("xbrl failed", symbol, e)
    try:
        sc = from_screener(symbol)
    except Exception as e:  # noqa: BLE001
        print("screener failed", symbol, e)
    if xb and sc and sc["quarter"]["end"] > xb["quarter"]["end"]:
        primary, other = sc, xb  # exchange XBRL lags for this company
    else:
        primary, other = xb or sc, sc if xb else None
    if primary and other and primary["quarter"]["end"] == other["quarter"]["end"]:
        checks = []
        for key in ("revenue", "pat"):
            a, b = primary["_x"].get(key), other["_x"].get(key)
            if a is not None and b is not None:
                ok = abs(a - b) <= max(abs(a), 1) * 0.02
                label = "Top line" if key == "revenue" else "PAT"
                checks.append({"name": f"{label} matches {other['source']}", "ok": ok, "detail": f"{a:,} vs {b:,} Cr"})
        primary["checks"] += checks
    if primary:
        primary.pop("_x", None)
    return primary
