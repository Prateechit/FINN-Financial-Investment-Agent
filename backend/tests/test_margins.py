"""Margin-comparison precision: quarterly margin comparisons are decided on exact margins, never on screener's
whole-number OPM %, and a comparison with only rounded figures is 'unverifiable'.

The TATATECH case is the row the production rebuild of 2026-11-09 produced: Q4 FY26 and Q2 FY26 both read "16%",
so the model called "EBITDA margins that exceed our Q2 run-rate" missed. From screener's own statement rows the exact
margins are 252 / 1,572 = 16.03% and 208 / 1,323 = 15.72%, so the promise was delivered.
"""
import copy
import importlib.util
import pathlib

import pytest

from finn.pull import financials, ledger, periods

HERE = pathlib.Path(__file__).parent

# TATATECH consolidated quarterly rows (screener.in), the quarters this promise involves.
TATATECH_Q = {"Sep 2025": (1323.0, 208.0, 16.0, 166.0), "Dec 2025": (1366.0, 193.0, 14.0, 7.0),
              "Mar 2026": (1572.0, 252.0, 16.0, 204.0)}  # sales, operating profit, OPM % (rounded), net profit

GUIDANCE = {"id": "G2.2", "call": "Q3 FY26", "subject": "EBITDA margin", "target": "exceed our Q2 run-rate",
            "horizon": "Q4", "period": "Q4 FY26",
            "statement": "For Q4, we expect sequential revenue growth in excess of 10%, and despite the impacts of new "
                         "labour codes, deliver EBITDA Margins that exceed our Q2 run-rate."}

# The row exactly as the 2026-11-09 production rebuild returned it.
REBUILT_ROW = {"subject": "Q4 FY26 EBITDA margin exceed Q2 run‑rate", "promise": "EBITDA margins exceed Q2 run‑rate for Q4 FY26",
               "verdict": "missed", "guidance_ids": ["G2.2"], "fact_ids": ["Q.OPM %.Mar 2026", "Q.OPM %.Sep 2025"],
               "why": "Margin did not exceed the Q2 run‑rate", "delivered": "Q4 margin 16% equals Q2 margin 16%"}


def _company(q: dict):
    cols = list(q)
    col = lambda i: [v[i] for v in q.values()]  # noqa: E731
    rows = {"Sales": col(0), "Operating Profit": col(1), "OPM %": col(2), "Net Profit": col(3),
            "Profit before tax": [round(v * 1.3, 1) for v in col(3)]}
    return {"symbol": "TATATECH", "basis": "consolidated", "name": "Tata Technologies", "about": None, "bse_code": None,
            "sector": None, "top": {}, "url": "https://example.invalid", "concalls": [], "annual_reports": [],
            "tables": {"quarters": {"cols": cols, "rows": rows}, "annual": None, "balance": None, "cashflow": None,
                       "ratios": None, "shareholding": None}}


def _facts(monkeypatch, q=TATATECH_Q) -> dict:
    monkeypatch.setattr(financials.screener, "company", lambda sym: _company(q))
    return financials.build("TATATECH")["facts"]


def _guard(row: dict, facts: dict, latest: str = "Sep 2026") -> dict:
    """The ledger's post-model guards, in build() order."""
    r = copy.deepcopy(row)
    guidance = {GUIDANCE["id"]: GUIDANCE}
    ledger._metric_guard(r, facts)
    ledger._period_guard(r, guidance, facts, periods.from_calendar(latest))
    ledger._margin_guard(r, guidance, facts)
    ledger._range_check(r, guidance, facts)
    ledger._horizon_guard(r, guidance, latest)
    return r


# ---------- the exact TATATECH case ----------

def test_tatatech_exact_margins_differ_where_rounded_opm_ties(monkeypatch):
    F = _facts(monkeypatch)
    assert F["Q.OPM %.Mar 2026"]["value"] == F["Q.OPM %.Sep 2025"]["value"] == 16.0      # screener: a tie
    assert F["calc.Q.ebitda_margin.Mar 2026"]["value"] == 16.03                           # 252 / 1,572
    assert F["calc.Q.ebitda_margin.Sep 2025"]["value"] == 15.72                           # 208 / 1,323


def test_tatatech_q4_fy26_margin_vs_q2_run_rate_is_delivered_on_exact_margins(monkeypatch):
    r = _guard(REBUILT_ROW, _facts(monkeypatch))
    assert r["verdict"] == "delivered" and r["downgraded_from"] == "missed"
    assert r["fact_ids"] == ["calc.Q.ebitda_margin.Mar 2026", "calc.Q.ebitda_margin.Sep 2025"]
    assert r["replaced_fact_ids"] == ["Q.OPM %.Mar 2026", "Q.OPM %.Sep 2025"]
    assert r["margin_check"] == {"result": "above",
                                 "target": {"period": "Q4 FY26", "value": 16.03, "fact": "calc.Q.ebitda_margin.Mar 2026"},
                                 "base": {"period": "Q2 FY26", "value": 15.72, "fact": "calc.Q.ebitda_margin.Sep 2025"}}
    assert "16.03% in Q4 FY26" in r["why"] and "15.72% in Q2 FY26" in r["why"]
    assert "period_check" not in r  # the right quarters were cited; only the precision was wrong


def test_exact_margin_not_above_the_base_is_missed(monkeypatch):
    lower = {**TATATECH_Q, "Mar 2026": (1572.0, 243.7, 16.0, 204.0)}  # 15.50%: still "16%" rounded, but below 15.72%
    r = _guard({**REBUILT_ROW, "verdict": "delivered"}, _facts(monkeypatch, lower))
    assert r["verdict"] == "missed" and r["downgraded_from"] == "delivered"
    assert r["margin_check"]["result"] == "not_above" and "15.5% in Q4 FY26" in r["why"]


def test_correct_model_verdict_is_kept_with_exact_figures(monkeypatch):
    r = _guard({**REBUILT_ROW, "verdict": "delivered", "why": "Model's own reason"}, _facts(monkeypatch))
    assert r["verdict"] == "delivered" and "downgraded_from" not in r and r["why"] == "Model's own reason"
    assert r["fact_ids"] == ["calc.Q.ebitda_margin.Mar 2026", "calc.Q.ebitda_margin.Sep 2025"]


# ---------- rounded ties without exact figures ----------

ROUNDED_ONLY = {fid: {"id": fid, "label": "OPM %", "value": 16.0, "unit": "%", "period": fid.split(".", 2)[2]}
                for fid in ("Q.OPM %.Mar 2026", "Q.OPM %.Sep 2025")}


@pytest.mark.parametrize("model_said", ["missed", "delivered", "on_track", "at_risk"])
def test_rounded_tie_without_exact_margins_is_unverifiable(model_said):
    r = _guard({**REBUILT_ROW, "verdict": model_said}, ROUNDED_ONLY)
    assert r["verdict"] == "unverifiable" and r["downgraded_from"] == model_said
    assert r["why"] == "Only rounded margins are available (16% in Q4 FY26 vs 16% in Q2 FY26), and they can't settle a margin comparison."
    assert r["margin_check"] == {"result": "rounded_only", "quarters": ["Q2 FY26", "Q4 FY26"]}


def test_exact_figure_for_only_one_quarter_is_not_mixed_with_a_rounded_one():
    facts = {**ROUNDED_ONLY, "calc.Q.ebitda_margin.Mar 2026": {"id": "calc.Q.ebitda_margin.Mar 2026", "label": "EBITDA margin",
                                                               "value": 16.03, "unit": "%", "period": "Mar 2026"}}
    r = _guard(REBUILT_ROW, facts)
    assert r["verdict"] == "unverifiable" and r["fact_ids"] == REBUILT_ROW["fact_ids"]


def test_exchange_filing_margins_count_as_exact():
    x = {f"X.EBITDA margin.{q}": {"id": f"X.EBITDA margin.{q}", "label": "EBITDA margin (exchange filing)", "value": v,
                                  "unit": "%", "period": q} for q, v in (("Q4 FY26", 16.0), ("Q2 FY26", 15.7))}
    r = _guard(REBUILT_ROW, {**ROUNDED_ONLY, **x})
    assert r["verdict"] == "delivered" and r["fact_ids"] == ["X.EBITDA margin.Q4 FY26", "X.EBITDA margin.Q2 FY26"]


# ---------- rows the guard must leave alone ----------

def test_single_quarter_margin_is_made_exact_without_changing_the_verdict(monkeypatch):
    r = {**REBUILT_ROW, "verdict": "at_risk", "why": "unchanged", "fact_ids": ["Q.OPM %.Mar 2026"]}
    ledger._margin_guard(r, {"G2.2": GUIDANCE}, _facts(monkeypatch))
    assert r["verdict"] == "at_risk" and r["why"] == "unchanged" and r["fact_ids"] == ["calc.Q.ebitda_margin.Mar 2026"]


@pytest.mark.parametrize("verdict", ["too_early", "unverifiable", "goalposts_moved", "dropped"])
def test_non_outcome_verdicts_are_not_decided_by_the_margin_guard(verdict):
    row = {**REBUILT_ROW, "verdict": verdict}
    ledger._margin_guard(row, {"G2.2": GUIDANCE}, ROUNDED_ONLY)
    assert row["verdict"] == verdict and "margin_check" not in row


def test_lender_margins_are_not_touched():
    pp = {f"X.Pre-provision margin.{q}": {"id": f"X.Pre-provision margin.{q}", "label": "Pre-provision margin (exchange filing)",
                                          "value": v, "unit": "%", "period": q} for q, v in (("Q2 FY26", 3.1), ("Q2 FY27", 3.0))}
    row = {**REBUILT_ROW, "verdict": "at_risk", "fact_ids": list(pp)}
    ledger._margin_guard(row, {"G2.2": GUIDANCE}, pp)
    assert row["verdict"] == "at_risk" and row["fact_ids"] == list(pp) and "margin_check" not in row


# ---------- what the model sees, and the whole build ----------

def test_ledger_input_hides_rounded_opm_where_an_exact_margin_exists(monkeypatch):
    F = _facts(monkeypatch)
    F["Q.OPM %.Jun 2025"] = {"id": "Q.OPM %.Jun 2025", "label": "OPM %", "value": 15.0, "unit": "%", "period": "Jun 2025"}
    text, ids = ledger._actuals_text(F)
    assert "calc.Q.ebitda_margin.Mar 2026 = 16.03% [Q4 FY26]" in text and "calc.Q.ebitda_margin.Sep 2025 = 15.72%" in text
    assert "Q.OPM %.Mar 2026" not in ids and "Q.OPM %.Sep 2025" not in ids
    assert "Q.OPM %.Jun 2025" in ids  # no exact margin for that quarter: the rounded one stays
    assert "never decide a comparison on it" in ledger.SYSTEM


def test_ledger_build_end_to_end_decides_the_tatatech_row_on_exact_margins(monkeypatch):
    F = _facts(monkeypatch)
    rev = {"id": "G2.1", "call": "Q3 FY26", "subject": "sequential revenue growth", "target": "in excess of 10%",
           "horizon": "Q4", "period": "Q4 FY26", "statement": GUIDANCE["statement"]}
    calls = [{"call": "Q3 FY26", "guidance": [rev, GUIDANCE]}]
    first = {**REBUILT_ROW, "delivered": "Margin did not exceed the Q2 run-rate"}  # cites the (now hidden) rounded ids
    second = {**first, "fact_ids": ["calc.Q.ebitda_margin.Mar 2026", "calc.Q.ebitda_margin.Sep 2025"]}
    prompts = []

    def fake_chat_json(tag, tier, system, user, max_tokens):
        prompts.append(user)
        return {"rows": [copy.deepcopy(first if len(prompts) == 1 else second)], "credibility": "ok"}

    monkeypatch.setattr(ledger, "chat_json", fake_chat_json)
    out = ledger.build(calls, F, "Mar 2026")
    row = out["rows"][0]
    assert "unknown fact ids ['Q.OPM %.Mar 2026', 'Q.OPM %.Sep 2025']" in prompts[1]  # rounded ids are not citable
    assert row["verdict"] == "delivered" and row["downgraded_from"] == "missed"
    assert [f["value"] for f in row["facts"]] == [16.03, 15.72]


# ---------- the production audit ----------

def test_audit_flags_rounded_margin_comparison_and_passes_the_guarded_row(monkeypatch):
    spec = importlib.util.spec_from_file_location("audit_periods", HERE.parent.parent / "scripts" / "audit_periods.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    F = _facts(monkeypatch)

    def memo(row):
        stored = {**row, "evidence": [GUIDANCE], "facts": [F[f] for f in row["fact_ids"]]}
        return {"sections": {"trajectory": {"quarterly": [{"period": "Sep 2026"}]}, "ledger": {"rows": [stored]}}}

    _, before = audit.audit_memo(memo(REBUILT_ROW))
    assert [f["problem"] for f in before] == [
        "Margin comparison of Q2 FY26, Q4 FY26 decided on rounded OPM % (Q.OPM %.Mar 2026, Q.OPM %.Sep 2025); exact margins are needed."]
    _, after = audit.audit_memo(memo(_guard(REBUILT_ROW, F)))
    assert not [f for f in after if f["problem"]]
