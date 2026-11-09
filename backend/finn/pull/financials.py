"""Deterministic research sections from standardised statements. No LLM.

Every number is registered in a fact table with a stable id (e.g. "A.Sales.Mar 2026", "Q.OPM %.Sep 2026") so
LLM-written sections can cite facts instead of producing figures.
"""
import re

from ..sources import screener


class Facts:
    def __init__(self, source: str, url: str):
        self.source, self.url, self.items = source, url, {}

    def add(self, fid: str, label: str, value, unit: str, period: str) -> str:
        if value is not None:
            self.items[fid] = {"id": fid, "label": label, "value": value, "unit": unit, "period": period,
                               "source": self.source, "url": self.url}
        return fid

    def get(self, fid):
        return self.items.get(fid, {}).get("value")


def _series(tbl, row):
    if not tbl or row not in tbl["rows"]:
        return []
    return [(c, v) for c, v in zip(tbl["cols"], tbl["rows"][row])]


def _cagr(a, b, years):
    if a is None or b is None or a <= 0 or b <= 0 or years <= 0:
        return None
    return round(((b / a) ** (1 / years) - 1) * 100, 1)


def _fy(col: str) -> str:
    m = re.match(r"(\w{3}) (\d{4})", col)
    return f"FY{m.group(2)[2:]}" if m and m.group(1) == "Mar" else col


def build(symbol: str) -> dict:
    c = screener.company(symbol)
    t = c["tables"]
    lender = screener.is_lender(c)
    F = Facts("screener.in standardised statements", c["url"])
    A, Q, B, CF, R, SH = (t.get(k) for k in ("annual", "quarters", "balance", "cashflow", "ratios", "shareholding"))
    top_line = "Revenue" if lender else "Sales"
    op_row, margin_row = ("Financing Profit", "Financing Margin %") if lender else ("Operating Profit", "OPM %")

    # ---- register facts ----
    for tbl, prefix, rows in [(A, "A", [top_line, op_row, margin_row, "Net Profit", "Interest", "Depreciation", "Other Income", "Profit before tax", "EPS in Rs", "Dividend Payout %"]),
                              (Q, "Q", [top_line, op_row, margin_row, "Net Profit", "Profit before tax", "Other Income", "Gross NPA %", "Net NPA %"]),
                              (B, "B", ["Equity Capital", "Reserves", "Borrowings", "Borrowing", "Deposits", "Total Liabilities", "Fixed Assets", "CWIP", "Investments", "Other Assets"]),
                              (CF, "CF", ["Cash from Operating Activity", "Cash from Investing Activity", "Cash from Financing Activity", "Free Cash Flow"]),
                              (R, "R", ["Debtor Days", "Inventory Days", "Days Payable", "Cash Conversion Cycle", "Working Capital Days", "ROCE %", "ROE %"]),
                              (SH, "SH", ["Promoters", "FIIs", "DIIs", "Public"])]:
        for row in rows:
            unit = "%" if row.endswith("%") or prefix == "SH" else "days" if "Days" in row or "Cycle" in row else "₹" if row == "EPS in Rs" else "₹ Cr"
            for col, v in _series(tbl, row):
                F.add(f"{prefix}.{row}.{col}", row, v, unit, col)

    # ---- trajectory ----
    ann = [(col, v) for col, v in _series(A, top_line) if col != "TTM"]
    pat = dict(_series(A, "Net Profit"))
    traj_rows = []
    for col, rev in ann[-10:]:
        traj_rows.append({"period": _fy(col), "col": col, "revenue": rev, "op_profit": dict(_series(A, op_row)).get(col),
                          "margin": dict(_series(A, margin_row)).get(col), "pat": pat.get(col)})
    cagr = {}
    for yrs in (3, 5, 10):
        if len(ann) > yrs:
            a0, a1 = ann[-1 - yrs], ann[-1]
            cagr[f"revenue_{yrs}y"] = F.add(f"calc.revenue_cagr_{yrs}y", f"Revenue CAGR {yrs}y", _cagr(a0[1], a1[1], yrs), "%", f"{_fy(a0[0])}–{_fy(a1[0])}")
            cagr[f"pat_{yrs}y"] = F.add(f"calc.pat_cagr_{yrs}y", f"PAT CAGR {yrs}y", _cagr(pat.get(a0[0]), pat.get(a1[0]), yrs), "%", f"{_fy(a0[0])}–{_fy(a1[0])}")

    qrows = []
    qs = _series(Q, top_line)
    qpat = dict(_series(Q, "Net Profit"))
    qmar = dict(_series(Q, margin_row))
    for i, (col, rev) in enumerate(qs):
        yoy_col = qs[i - 4][0] if i >= 4 else None
        g = round((rev / qs[i - 4][1] - 1) * 100, 1) if yoy_col and rev and qs[i - 4][1] else None
        pg = round((qpat[col] / qpat[yoy_col] - 1) * 100, 1) if yoy_col and qpat.get(col) and qpat.get(yoy_col) and qpat[yoy_col] > 0 else None
        F.add(f"calc.Q.revenue_yoy.{col}", "Revenue growth YoY", g, "%", col)
        F.add(f"calc.Q.pat_yoy.{col}", "PAT growth YoY", pg, "%", col)
        qrows.append({"period": col, "revenue": rev, "revenue_yoy": g, "margin": qmar.get(col), "pat": qpat.get(col), "pat_yoy": pg})

    # Year-to-date growth for the current fiscal year (what full-year guidance is usually tracked against)
    ytd = None
    if qs:
        last = qs[-1][0]
        m = re.match(r"(\w{3}) (\d{4})", last)
        if m:
            fy_start_year = int(m.group(2)) if m.group(1) != "Mar" else int(m.group(2)) - 1
            if m.group(1) in ("Jan", "Feb", "Mar"):
                fy_start_year = int(m.group(2)) - 1
            cur = [(col, v) for col, v in qs if _in_fy(col, fy_start_year)]
            prev = [(col, v) for col, v in qs if _in_fy(col, fy_start_year - 1)][:len(cur)]
            if cur and len(prev) == len(cur) and all(v for _, v in cur + prev):
                s1, s0 = sum(v for _, v in cur), sum(v for _, v in prev)
                label = f"FY{(fy_start_year + 1) % 100:02d} YTD ({len(cur)}Q)"
                ytd = {"label": label, "revenue": round(s1, 1), "prior": round(s0, 1), "growth": round((s1 / s0 - 1) * 100, 1)}
                F.add("calc.ytd_revenue_growth", f"Revenue growth {label} vs prior-year period", ytd["growth"], "%", label)
                m_cur = [qmar.get(col) for col, _ in cur if qmar.get(col) is not None]
                if m_cur:
                    F.add("calc.ytd_margin", f"Average {margin_row} {label}", round(sum(m_cur) / len(m_cur), 1), "%", label)

    # ---- balance sheet ----
    bal = []
    borrow_row = "Borrowings" if B and "Borrowings" in B["rows"] else "Borrowing"
    for col, eq in _series(B, "Equity Capital"):
        res = dict(_series(B, "Reserves")).get(col)
        debt = dict(_series(B, borrow_row)).get(col)
        nw = (eq or 0) + (res or 0)
        de = round(debt / nw, 2) if debt is not None and nw else None
        F.add(f"calc.net_worth.{col}", "Net worth", round(nw, 1), "₹ Cr", col)
        F.add(f"calc.de.{col}", "Debt / equity", de, "x", col)
        bal.append({"period": col, "net_worth": round(nw, 1), "debt": debt, "de": de,
                    "deposits": dict(_series(B, "Deposits")).get(col)})
    wc = []
    for col, d in _series(R, "Debtor Days"):
        wc.append({"period": col, "debtor_days": d, "inventory_days": dict(_series(R, "Inventory Days")).get(col),
                   "payable_days": dict(_series(R, "Days Payable")).get(col),
                   "ccc": dict(_series(R, "Cash Conversion Cycle")).get(col), "wc_days": dict(_series(R, "Working Capital Days")).get(col),
                   "roce": dict(_series(R, "ROCE %")).get(col)})

    # ---- cash quality ----
    cash = []
    for col, cfo in _series(CF, "Cash from Operating Activity"):
        fcf = dict(_series(CF, "Free Cash Flow")).get(col)
        p = pat.get(col)
        capex = round(cfo - fcf, 1) if cfo is not None and fcf is not None else None
        conv = round(cfo / p * 100) if cfo is not None and p and p > 0 else None
        F.add(f"calc.capex.{col}", "Capex (CFO − FCF)", capex, "₹ Cr", col)
        F.add(f"calc.cfo_pat.{col}", "CFO / PAT", conv, "%", col)
        cash.append({"period": col, "cfo": cfo, "fcf": fcf, "capex": capex, "pat": p, "cfo_pat": conv})
    last5 = cash[-5:]
    conv5 = None
    if last5 and all(x["cfo"] is not None and x["pat"] for x in last5):
        conv5 = round(sum(x["cfo"] for x in last5) / sum(x["pat"] for x in last5) * 100)
        F.add("calc.cfo_pat_5y", "Cumulative 5y CFO / PAT", conv5, "%", f"{last5[0]['period']}–{last5[-1]['period']}")
        F.add("calc.fcf_5y", "Cumulative 5y free cash flow", round(sum(x["fcf"] or 0 for x in last5), 1), "₹ Cr",
              f"{last5[0]['period']}–{last5[-1]['period']}")

    if lender:  # screener's "Financing Margin %" is not meaningful for banks; use PAT margin
        for r in traj_rows + qrows:
            r["margin"] = round(r["pat"] / r["revenue"] * 100, 1) if r.get("pat") is not None and r.get("revenue") else None
    signals = _signals(F, traj_rows, qrows, bal, wc, cash, conv5, lender, SH)
    top = c["top"]
    snapshot = {
        "name": c["name"], "symbol": symbol, "sector": c["sector"], "basis": c["basis"], "lender": lender,
        "market_cap": top.get("Market Cap"), "price": top.get("Current Price"), "pe": top.get("Stock P/E"),
        "roce": top.get("ROCE"), "roe": top.get("ROE"), "dividend_yield": top.get("Dividend Yield"),
        "book_value": top.get("Book Value"), "high_low": top.get("High / Low"),
        "ttm_revenue": dict(_series(A, top_line)).get("TTM"), "ttm_pat": pat.get("TTM"),
        "ttm_margin": None if lender else dict(_series(A, margin_row)).get("TTM"),
        "about": c["about"], "url": c["url"], "bse_code": c["bse_code"],
    }
    return {"snapshot": snapshot, "trajectory": {"annual": traj_rows, "quarterly": qrows[-8:], "cagr": {k: F.get(v) for k, v in cagr.items()}, "ytd": ytd,
                                                 "margin_label": "PAT margin" if lender else "Operating margin"},
            "balance_sheet": {"rows": bal, "working_capital": wc, "borrow_label": borrow_row},
            "cash": {"rows": cash, "cfo_pat_5y": conv5},
            "signals": signals, "facts": F.items, "concalls": c["concalls"], "annual_reports": c["annual_reports"]}


def _in_fy(col: str, start_year: int) -> bool:
    m = re.match(r"(\w{3}) (\d{4})", col)
    if not m:
        return False
    mon, yr = m.group(1), int(m.group(2))
    return (yr == start_year and mon in ("Jun", "Sep", "Dec")) or (yr == start_year + 1 and mon == "Mar")


def _signals(F, traj, qrows, bal, wc, cash, conv5, lender, SH) -> list[dict]:
    """Plain, computed observations, each tagged good/bad/neutral and tied to fact ids."""
    out = []

    def add(tone, text, facts):
        out.append({"tone": tone, "text": text, "facts": [f for f in facts if f in F.items]})

    if len(traj) >= 4 and not lender:
        a, b = traj[-4], traj[-1]
        if a["margin"] is not None and b["margin"] is not None and abs(b["margin"] - a["margin"]) >= 2:
            tone = "good" if b["margin"] > a["margin"] else "bad"
            label = "Financing margin" if lender else "Operating margin"
            add(tone, f"{label} {'expanded' if tone == 'good' else 'compressed'} from {a['margin']}% ({a['period']}) to {b['margin']}% ({b['period']}).",
                [f"A.{'Financing Margin %' if lender else 'OPM %'}.{a['col']}", f"A.{'Financing Margin %' if lender else 'OPM %'}.{b['col']}"])
    r5, p5 = F.get("calc.revenue_cagr_5y"), F.get("calc.pat_cagr_5y")
    if r5 is not None and p5 is not None:
        tone = "good" if p5 >= r5 else "bad" if p5 < r5 - 5 else "neutral"
        add(tone, f"5-year revenue CAGR {r5}% vs PAT CAGR {p5}% — profits {'outgrew' if p5 > r5 else 'lagged'} sales.",
            ["calc.revenue_cagr_5y", "calc.pat_cagr_5y"])
    recent = [q for q in qrows if q["revenue_yoy"] is not None][-4:]
    if len(recent) >= 3:
        gs = [q["revenue_yoy"] for q in recent]
        if gs[-1] < gs[0] - 5:
            add("bad", f"Revenue growth decelerating: {gs[0]}% YoY ({recent[0]['period']}) → {gs[-1]}% ({recent[-1]['period']}).",
                [f"calc.Q.revenue_yoy.{recent[0]['period']}", f"calc.Q.revenue_yoy.{recent[-1]['period']}"])
        elif gs[-1] > gs[0] + 5:
            add("good", f"Revenue growth accelerating: {gs[0]}% YoY ({recent[0]['period']}) → {gs[-1]}% ({recent[-1]['period']}).",
                [f"calc.Q.revenue_yoy.{recent[0]['period']}", f"calc.Q.revenue_yoy.{recent[-1]['period']}"])
    if qrows and qrows[-1]["revenue_yoy"] is not None and qrows[-1]["pat_yoy"] is not None:
        q = qrows[-1]
        gap = q["pat_yoy"] - q["revenue_yoy"]
        if abs(gap) >= 20 and (q["pat_yoy"] < 0 or q["revenue_yoy"] < 0 or abs(gap) >= 40):
            add("bad" if gap < 0 else "good",
                f"Latest quarter ({q['period']}): revenue {q['revenue_yoy']:+}% YoY but profit {q['pat_yoy']:+}% YoY — "
                f"{'profit is not keeping up with sales' if gap < 0 else 'profit is outrunning sales'}.",
                [f"calc.Q.revenue_yoy.{q['period']}", f"calc.Q.pat_yoy.{q['period']}"])
    if not lender and len(qrows) >= 5 and qrows[-1]["margin"] is not None and qrows[-5]["margin"] is not None:
        a, b = qrows[-5], qrows[-1]
        if abs(b["margin"] - a["margin"]) >= 1:
            add("good" if b["margin"] > a["margin"] else "bad",
                f"Quarterly operating margin {b['margin']}% ({b['period']}) vs {a['margin']}% a year earlier.",
                [f"Q.OPM %.{a['period']}", f"Q.OPM %.{b['period']}"])
    if conv5 is not None and not lender:
        tone = "good" if conv5 >= 90 else "bad" if conv5 < 70 else "neutral"
        add(tone, f"Over 5 years, operating cash flow was {conv5}% of reported profit"
            + (" — profits are converting to cash." if tone == "good" else " — a meaningful share of profit is not turning into cash." if tone == "bad" else "."),
            ["calc.cfo_pat_5y"])
    if not lender and len(bal) >= 3:
        a, b = bal[-3], bal[-1]
        if a["de"] is not None and b["de"] is not None and abs(b["de"] - a["de"]) >= 0.2:
            add("bad" if b["de"] > a["de"] else "good", f"Debt/equity moved from {a['de']}x ({a['period']}) to {b['de']}x ({b['period']}).",
                [f"calc.de.{a['period']}", f"calc.de.{b['period']}"])
        elif b["de"] is not None and b["de"] < 0.1:
            add("good", f"Balance sheet is virtually debt-free (debt/equity {b['de']}x).", [f"calc.de.{b['period']}"])
    if len(wc) >= 3 and wc[-1]["ccc"] is not None and wc[-3]["ccc"] is not None and abs(wc[-1]["ccc"] - wc[-3]["ccc"]) >= 15:
        a, b = wc[-3], wc[-1]
        add("bad" if b["ccc"] > a["ccc"] else "good", f"Cash conversion cycle {'lengthened' if b['ccc'] > a['ccc'] else 'shortened'} from {a['ccc']:.0f} to {b['ccc']:.0f} days ({a['period']} → {b['period']}).",
            [f"R.Cash Conversion Cycle.{a['period']}", f"R.Cash Conversion Cycle.{b['period']}"])
    prom = _series(SH, "Promoters")
    if len(prom) >= 4 and prom[-1][1] is not None and prom[-4][1] is not None and abs(prom[-1][1] - prom[-4][1]) >= 1:
        a, b = prom[-4], prom[-1]
        add("bad" if b[1] < a[1] else "good", f"Promoter holding {'fell' if b[1] < a[1] else 'rose'} from {a[1]}% to {b[1]}% ({a[0]} → {b[0]}).",
            [f"SH.Promoters.{a[0]}", f"SH.Promoters.{b[0]}"])
    if lender:
        npa = [(q["period"], F.get(f"Q.Gross NPA %.{q['period']}")) for q in qrows]
        npa = [x for x in npa if x[1] is not None]
        if len(npa) >= 4 and abs(npa[-1][1] - npa[-4][1]) >= 0.2:
            a, b = npa[-4], npa[-1]
            add("bad" if b[1] > a[1] else "good", f"Gross NPA moved from {a[1]}% to {b[1]}% ({a[0]} → {b[0]}).",
                [f"Q.Gross NPA %.{a[0]}", f"Q.Gross NPA %.{b[0]}"])
    return out
