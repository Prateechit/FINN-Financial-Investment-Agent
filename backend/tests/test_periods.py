"""Fiscal-period alignment: calendar ↔ fiscal mapping, promise-period resolution, the ledger period guard, the new
quarterly facts, model-input labels, verifier evidence and the production audit.

Real rows from the production DIXON, HDFCBANK and TATATECH memos live in tests/ledger_rows_fixture.json (public data).
"""
import copy
import datetime as dt
import importlib.util
import json
import pathlib

import pytest

from finn.pull import financials, ledger, periods, verify
from finn.pull.periods import FQ
from finn.pull.transcripts import attach_period, quarter_discussed

HERE = pathlib.Path(__file__).parent
FIXTURE = json.loads((HERE / "ledger_rows_fixture.json").read_text(encoding="utf-8"))


# ---------- fiscal calendar ----------

@pytest.mark.parametrize("calendar,label", [("Mar 2026", "Q4 FY26"), ("Jun 2026", "Q1 FY27"), ("Sep 2026", "Q2 FY27"),
                                            ("Dec 2025", "Q3 FY26"), ("Mar 2025", "Q4 FY25"), ("Dec 2026", "Q3 FY27")])
def test_calendar_month_to_fiscal_quarter_and_back(calendar, label):
    fq = periods.from_calendar(calendar)
    assert fq.label == label and fq.calendar == calendar


def test_quarter_arithmetic_crosses_the_fiscal_year_boundary():
    assert FQ(27, 1).prev() == FQ(26, 4) and FQ(26, 4).shift(1) == FQ(27, 1)
    assert FQ(27, 2).year_ago() == FQ(26, 2)
    assert periods.from_label("Q4 FY'26") == periods.from_label("Q4FY26") == periods.from_label("Q4 FY2026") == FQ(26, 4)


def test_call_date_to_quarter_discussed():
    assert quarter_discussed(dt.date(2026, 1, 1)) == "Q3 FY26"   # Jan call reports Dec quarter
    assert quarter_discussed(dt.date(2026, 5, 1)) == "Q4 FY26"   # May call reports Mar quarter
    assert quarter_discussed(dt.date(2026, 11, 1)) == "Q2 FY27"


# ---------- resolving what management said ----------

@pytest.mark.parametrize("horizon,call,expected", [
    ("Q4", "Q3 FY26", "Q4 FY26"),          # the Tata Technologies case
    ("Q1", "Q4 FY26", "Q1 FY27"),          # year boundary
    ("Q4", "Q4 FY26", "Q4 FY27"),          # a Q4 call's "Q4" is next year's
    ("H2 FY27", "Q2 FY27", "H2 FY27"),
    ("Q3 FY27", "Q2 FY27", "Q3 FY27"),     # explicit periods stand
    ("H2", "Q2 FY27", "H2 FY27"),
    ("second half", "Q1 FY27", "H2 FY27"),
    ("FY27", "Q1 FY27", "FY27"),
    ("FY26-27", "Q1 FY27", "FY27"),
    ("current fiscal", "Q4 FY26", "FY27"),  # a Q4 call happens in the next fiscal year
    ("next fiscal", "Q3 FY26", "FY27"),
])
def test_resolve_promise_period(horizon, call, expected):
    assert periods.resolve(horizon, call).label == expected


@pytest.mark.parametrize("vague", ["medium term", "next 2-3 years", "next quarter onwards", "", None])
def test_vague_horizons_are_not_guessed(vague):
    assert periods.resolve(vague, "Q2 FY27") is None


def test_extraction_stores_resolved_period_next_to_the_original_words():
    g = attach_period({"horizon": "Q4", "statement": "For Q4, we expect sequential revenue growth in excess of 10%"}, "Q3 FY26")
    assert g["period"] == "Q4 FY26" and g["period_kind"] == "quarter" and g["horizon"] == "Q4"
    assert attach_period({"horizon": "medium term"}, "Q2 FY27")["period"] is None


@pytest.mark.parametrize("fid,period,expected", [
    ("Q.Sales.Mar 2026", "Mar 2026", "Q4 FY26"), ("A.Sales.Mar 2026", "Mar 2026", "FY26"),
    ("calc.capex.Mar 2026", "Mar 2026", "FY26"), ("calc.Q.revenue_qoq.Mar 2026", "Mar 2026", "Q4 FY26"),
    ("calc.ytd_revenue_growth", "FY27 YTD (2Q)", "FY27 YTD"), ("A.Sales.TTM", "TTM", None),
    ("calc.revenue_cagr_5y", "FY21–FY26", None),
])
def test_fact_periods(fid, period, expected):
    p = periods.fact_period(fid, period)
    assert (p.label if p else None) == expected


# ---------- ledger period guard on the real production rows ----------

def _guarded(sym: str, subject: str, **override):
    memo = FIXTURE[sym]
    row = copy.deepcopy(next(r for r in memo["rows"] if r["subject"] == subject))
    row.update(override)
    facts = {f["id"]: f for f in row["facts"]}
    facts.update({f["id"]: f for f in override.get("_facts", [])})
    row.pop("_facts", None)
    guidance = {g["id"]: g for g in row["evidence"]}
    ledger._period_guard(row, guidance, facts, periods.from_calendar(memo["latest_quarter"]))
    return row


def test_tatatech_q4_sequential_growth_on_wrong_quarters_is_rejected():
    r = _guarded("TATATECH", "Q4 FY26 sequential revenue growth")
    assert r["downgraded_from"] == "missed" and r["verdict"] == "unverifiable"
    assert "not the promised Q4 FY26" in r["why"] and "Q2 FY27" in r["why"]
    assert r["fact_ids"] == [] and r["rejected_fact_ids"] == ["Q.Sales.Sep 2026", "Q.Sales.Jun 2026"]


def test_tatatech_q4_sequential_growth_on_the_right_quarters_is_kept():
    qoq = {"id": "calc.Q.revenue_qoq.Mar 2026", "label": "Revenue growth QoQ (sequential)", "value": 15.1, "unit": "%", "period": "Mar 2026"}
    r = _guarded("TATATECH", "Q4 FY26 sequential revenue growth", verdict="delivered",
                 fact_ids=["Q.Sales.Mar 2026", "Q.Sales.Dec 2025", qoq["id"]],
                 _facts=[{"id": "Q.Sales.Mar 2026", "label": "Sales", "value": 1572.0, "unit": "₹ Cr", "period": "Mar 2026"},
                         {"id": "Q.Sales.Dec 2025", "label": "Sales", "value": 1366.0, "unit": "₹ Cr", "period": "Dec 2025"}, qoq])
    assert r["verdict"] == "delivered" and "downgraded_from" not in r


def test_tatatech_q4_margin_judged_on_q2_figures_is_rejected():
    r = _guarded("TATATECH", "Q4 FY26 EBITDA margin vs Q2 run-rate")
    assert r["verdict"] == "unverifiable" and "Q4 FY26" in r["why"]


def test_tatatech_h2_fy27_not_started_is_too_early():
    r = _guarded("TATATECH", "H2 FY27 sequential margin improvement")
    assert r["downgraded_from"] == "on_track" and r["verdict"] == "too_early"
    assert "H2 FY27 hasn't started" in r["why"] and "Q2 FY27" in r["why"]


@pytest.mark.parametrize("sym", ["DIXON", "HDFCBANK"])
def test_dixon_and_hdfcbank_verdicts_unchanged_by_the_new_guards(sym):
    memo = FIXTURE[sym]
    latest = memo["latest_quarter"]
    for original in memo["rows"]:
        row = copy.deepcopy(original)
        facts = {f["id"]: f for f in row["facts"]}
        guidance = {g["id"]: g for g in row["evidence"]}
        ledger._period_guard(row, guidance, facts, periods.from_calendar(latest))
        ledger._horizon_guard(row, guidance, latest)
        assert row["verdict"] == original["verdict"], (sym, original["subject"])


def test_missed_uses_resolved_period_for_its_deadline():
    g = {"G1": {"id": "G1", "call": "Q2 FY27", "horizon": "H2 FY27"}, "G2": {"id": "G2", "call": "Q2 FY26", "horizon": "FY26"}}
    running = {"verdict": "missed", "guidance_ids": ["G1"], "why": ""}
    ledger._horizon_guard(running, g, "Dec 2026")  # H2 FY27 running in Q3 FY27
    assert running["verdict"] == "at_risk"
    ended = {"verdict": "missed", "guidance_ids": ["G2"], "why": ""}
    ledger._horizon_guard(ended, g, "Sep 2026")
    assert ended["verdict"] == "missed"


# ---------- new quarterly facts ----------

def _fake_company(sales: dict, lender=False):
    cols = list(sales)
    rev = list(sales.values())
    rows = {"Sales": rev, "Operating Profit": [round(v * 0.1625, 1) for v in rev], "OPM %": [16.0] * len(rev),
            "Net Profit": [round(v * 0.12, 1) for v in rev], "Profit before tax": [round(v * 0.16, 1) for v in rev]}
    if lender:
        rows = {"Revenue": rev, "Interest": [v * 0.5 for v in rev], "Financing Profit": [v * 0.2 for v in rev],
                "Financing Margin %": [-5.0] * len(rev), "Net Profit": [v * 0.15 for v in rev]}
    return {"symbol": "TEST", "basis": "consolidated", "name": "Test Co", "about": None, "bse_code": None, "sector": None,
            "top": {}, "url": "https://example.invalid", "concalls": [], "annual_reports": [],
            "tables": {"quarters": {"cols": cols, "rows": rows}, "annual": None, "balance": None, "cashflow": None,
                       "ratios": None, "shareholding": None}}


def test_sequential_growth_and_exact_ebitda_margin_facts(monkeypatch):
    sales = FIXTURE["TATATECH"]["quarterly_sales"]
    monkeypatch.setattr(financials.screener, "company", lambda sym: _fake_company(sales))
    F = financials.build("TEST")["facts"]
    assert F["calc.Q.revenue_qoq.Mar 2026"]["value"] == 15.1          # 1,572 vs 1,366
    assert F["calc.Q.revenue_qoq.Sep 2026"]["value"] == 2.0           # 1,699 vs 1,665
    assert "calc.Q.revenue_qoq.Dec 2024" not in F                     # no prior quarter
    assert F["calc.Q.ebitda_margin.Mar 2026"]["value"] == 16.25       # exact, not screener's rounded 16
    assert F["calc.Q.pat_qoq.Mar 2026"]["value"] == 15.1


def test_lenders_get_no_ebitda_margin(monkeypatch):
    monkeypatch.setattr(financials.screener, "company", lambda sym: _fake_company({"Jun 2026": 100.0, "Sep 2026": 110.0}, lender=True))
    F = financials.build("TEST")["facts"]
    assert not any(k.startswith("calc.Q.ebitda_margin") for k in F) and F["calc.Q.revenue_qoq.Sep 2026"]["value"] == 10.0


# ---------- what the models see ----------

def test_ledger_input_tags_every_dated_fact_with_its_fiscal_period():
    facts = {"Q.Sales.Mar 2026": {"id": "Q.Sales.Mar 2026", "label": "Sales", "value": 1572.0, "unit": "₹ Cr", "period": "Mar 2026"},
             "A.Sales.Mar 2026": {"id": "A.Sales.Mar 2026", "label": "Sales", "value": 5402.0, "unit": "₹ Cr", "period": "Mar 2026"},
             "X.pat.Q2 FY27": {"id": "X.pat.Q2 FY27", "label": "PAT (exchange filing)", "value": 180.0, "unit": "₹ Cr", "period": "Q2 FY27"}}
    text, _ = ledger._actuals_text(facts)
    assert "Q.Sales.Mar 2026 = ₹1,572 Cr [Q4 FY26]" in text
    assert "A.Sales.Mar 2026 = ₹5,402 Cr [FY26]" in text
    assert "X.pat.Q2 FY27 = ₹180 Cr —" in text and "[Q2 FY27]" not in text  # already in the id


def test_ledger_input_states_each_promise_period():
    g = {"id": "G2.1", "call": "Q3 FY26", "subject": "sequential revenue growth", "target": "in excess of 10%", "horizon": "Q4",
         "statement": "For Q4, we expect sequential revenue growth in excess of 10%"}
    text = ledger._guidance_text([{"guidance": [g]}])
    assert "G2.1 | Q3 FY26 call |" in text and "period Q4 FY26 (said: 'Q4')" in text
    assert "Q1 = Apr–Jun" in ledger.SYSTEM and "Mar 2026\" is Q4 FY26" in ledger.SYSTEM


def test_verifier_evidence_carries_fiscal_periods():
    fact = verify._evidence_text({"type": "fact", "id": "Q.Sales.Sep 2026", "label": "Sales", "value": 1699.0, "unit": "₹ Cr", "period": "Sep 2026"})
    assert "(Sep 2026 = Q2 FY27)" in fact
    said = verify._evidence_text({"type": "guidance", "call": "Q3 FY26", "horizon": "Q4", "statement": "For Q4, …"})
    assert "(Q3 FY26 call) about Q4 FY26" in said
    row = copy.deepcopy(next(r for r in FIXTURE["TATATECH"]["rows"] if r["subject"] == "Q4 FY26 sequential revenue growth"))
    claim = verify.claims_for({}, {"rows": [row]})[0]
    assert "(promise period: Q4 FY26)" in claim["claim"] and any("Q2 FY27" in e for e in claim["evidence"])


# ---------- production audit ----------

def test_audit_flags_tatatech_and_passes_dixon_hdfcbank():
    spec = importlib.util.spec_from_file_location("audit_periods", HERE.parent.parent / "scripts" / "audit_periods.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)

    def memo(sym):
        m = FIXTURE[sym]
        return {"sections": {"trajectory": {"quarterly": [{"period": m["latest_quarter"]}]}, "ledger": {"rows": m["rows"]}}}

    _, tata = audit.audit_memo(memo("TATATECH"))
    assert sorted(f["subject"] for f in tata if f["problem"]) == sorted(
        ["Q4 FY26 sequential revenue growth", "Q4 FY26 EBITDA margin vs Q2 run-rate", "H2 FY27 sequential margin improvement"])
    for sym in ("DIXON", "HDFCBANK"):
        checked, findings = audit.audit_memo(memo(sym))
        assert checked > 0 and not [f for f in findings if f["problem"]]
