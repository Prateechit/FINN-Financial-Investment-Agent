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
    # A promise that names no comparison quarter: the cited margin is made exact and nothing else changes.
    # (A promise that does name one — "exceed our Q2 run-rate" — gets its base attached; see the tests below.)
    g = {**GUIDANCE, "target": "hold EBITDA margin around 16%", "statement": "We aim to hold EBITDA margin around 16% in Q4."}
    r = {**REBUILT_ROW, "subject": "Q4 FY26 EBITDA margin", "promise": "hold EBITDA margin around 16% in Q4 FY26",
         "verdict": "at_risk", "why": "unchanged", "fact_ids": ["Q.OPM %.Mar 2026"]}
    ledger._margin_guard(r, {"G2.2": g}, _facts(monkeypatch))
    assert r["verdict"] == "at_risk" and r["why"] == "unchanged" and r["fact_ids"] == ["calc.Q.ebitda_margin.Mar 2026"]
    assert "attached_fact_ids" not in r and "margin_check" not in r


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


# ---------- a single-quarter promise that names its base quarter (production TATATECH rebuild, 2026-11-10) ----------
# The rebuild on 5332283 judged "EBITDA margins that exceed our Q2 run-rate" delivered, citing only the Q4 FY26 exact
# margin (16.03%): the Q2 FY26 base (15.72%) was quoted in the row's text but not attached as evidence.

PROD_ROW = {"subject": "Q4 FY26 EBITDA margin", "promise": "EBITDA margin in Q4 FY26 to exceed Q2 FY26 run‑rate",
            "verdict": "delivered", "guidance_ids": ["G2.2"], "fact_ids": ["calc.Q.ebitda_margin.Mar 2026"],
            "why": "Margin beat the prior‑quarter benchmark", "delivered": "Q4 FY26 margin 16.03% vs Q2 FY26 15.72%"}
# Q1 / Q2 FY27 rows from screener (sales, operating profit, OPM %, net profit), for the H2 FY27 row
TATATECH_Q_FY27 = {**TATATECH_Q, "Jun 2026": (1665.0, 267.0, 16.0, 170.0), "Sep 2026": (1699.0, 273.0, 16.0, 172.0)}


def test_production_row_gets_its_named_q2_base_attached_and_decided(monkeypatch):
    r = _guard(PROD_ROW, _facts(monkeypatch))
    assert r["fact_ids"] == ["calc.Q.ebitda_margin.Mar 2026", "calc.Q.ebitda_margin.Sep 2025"]
    assert r["attached_fact_ids"] == ["calc.Q.ebitda_margin.Sep 2025"]
    assert r["margin_check"] == {"result": "above",
                                 "target": {"period": "Q4 FY26", "value": 16.03, "fact": "calc.Q.ebitda_margin.Mar 2026"},
                                 "base": {"period": "Q2 FY26", "value": 15.72, "fact": "calc.Q.ebitda_margin.Sep 2025"}}
    assert r["verdict"] == "delivered" and "downgraded_from" not in r


def test_production_row_quoted_margins_are_now_in_the_cited_evidence(monkeypatch):
    # validate_memo's soft check: every number in the row's prose must be in the row's own cited evidence
    from finn.grounding import ungrounded
    F = _facts(monkeypatch)
    said = GUIDANCE["statement"] + " " + GUIDANCE["target"]
    before = " ".join(f"{F[f]['value']} {F[f]['label']}" for f in PROD_ROW["fact_ids"])
    assert ungrounded(PROD_ROW["delivered"], said + " " + before) == [15.72]            # the production finding
    r = _guard(PROD_ROW, F)
    after = " ".join(f"{F[f]['value']} {F[f]['label']}" for f in r["fact_ids"])
    assert not ungrounded(f"{r['promise']} {r['delivered']} {r['why']}", said + " " + after)


def test_attached_base_also_corrects_a_wrong_model_verdict(monkeypatch):
    r = _guard({**PROD_ROW, "verdict": "missed"}, _facts(monkeypatch))
    assert r["verdict"] == "delivered" and r["downgraded_from"] == "missed" and "15.72% in Q2 FY26" in r["why"]


def test_base_quarter_without_an_exact_margin_is_unverifiable_never_rounded(monkeypatch):
    F = _facts(monkeypatch)
    del F["calc.Q.ebitda_margin.Sep 2025"]          # only screener's rounded 16% remains for Q2 FY26
    assert F["Q.OPM %.Sep 2025"]["value"] == 16.0
    r = _guard(PROD_ROW, F)
    assert r["verdict"] == "unverifiable" and r["downgraded_from"] == "delivered"
    assert r["margin_check"] == {"result": "base_missing", "target": "Q4 FY26", "base": "Q2 FY26"}
    assert r["why"] == ("No exact margin for Q2 FY26 in the sources, so 16.03% in Q4 FY26 can't be compared with the "
                        "Q2 FY26 level.")
    assert r["fact_ids"] == ["calc.Q.ebitda_margin.Mar 2026"] and "Q.OPM %.Sep 2025" not in r["fact_ids"]


def test_base_missing_still_shows_the_exact_target_when_the_model_cited_a_rounded_one(monkeypatch):
    F = _facts(monkeypatch)
    del F["calc.Q.ebitda_margin.Sep 2025"]
    r = _guard({**PROD_ROW, "fact_ids": ["Q.OPM %.Mar 2026"]}, F)
    assert r["verdict"] == "unverifiable" and r["fact_ids"] == ["calc.Q.ebitda_margin.Mar 2026"]
    assert r["replaced_fact_ids"] == ["Q.OPM %.Mar 2026"]


def test_base_in_a_different_source_family_is_not_mixed_in(monkeypatch):
    # Q4 FY26 exact only from FINN's own calculation, Q2 FY26 only from the exchange filing: no one source covers both
    F = _facts(monkeypatch)
    del F["calc.Q.ebitda_margin.Sep 2025"]
    F["X.EBITDA margin.Q2 FY26"] = {"id": "X.EBITDA margin.Q2 FY26", "label": "EBITDA margin (exchange filing)",
                                    "value": 15.7, "unit": "%", "period": "Q2 FY26"}
    r = _guard(PROD_ROW, F)
    assert r["verdict"] == "unverifiable" and r["margin_check"]["result"] == "base_missing"


def test_explicitly_labelled_base_quarter_is_used(monkeypatch):
    g = {**GUIDANCE, "target": "margin above the Q2 FY26 level", "statement": "We expect Q4 margins above the Q2 FY26 level."}
    r = copy.deepcopy({**PROD_ROW, "promise": "Q4 FY26 margin above the Q2 FY26 level"})
    ledger._margin_guard(r, {"G2.2": g}, _facts(monkeypatch))
    assert r["attached_fact_ids"] == ["calc.Q.ebitda_margin.Sep 2025"] and r["margin_check"]["result"] == "above"


def test_sequential_promise_uses_the_previous_quarter_as_base(monkeypatch):
    g = {**GUIDANCE, "target": "sequential EBITDA margin improvement", "statement": "We expect sequential margin improvement in Q4."}
    r = copy.deepcopy({**PROD_ROW, "promise": "sequential EBITDA margin improvement in Q4 FY26"})
    ledger._margin_guard(r, {"G2.2": g}, _facts(monkeypatch))
    assert r["attached_fact_ids"] == ["calc.Q.ebitda_margin.Dec 2025"]                       # Q3 FY26: 193 / 1,366
    assert r["margin_check"]["base"] == {"period": "Q3 FY26", "value": 14.13, "fact": "calc.Q.ebitda_margin.Dec 2025"}
    assert r["verdict"] == "delivered"


def test_two_different_base_quarters_named_is_unverifiable(monkeypatch):
    g = {**GUIDANCE, "target": "exceed the Q2 and Q3 run-rates"}
    r = copy.deepcopy(PROD_ROW)
    ledger._margin_guard(r, {"G2.2": g}, _facts(monkeypatch))
    assert r["verdict"] == "unverifiable" and r["margin_check"] == {"result": "base_ambiguous", "target": "Q4 FY26"}
    assert "Q2 FY26, Q3 FY26" in r["why"]


# ---------- code-review probes: only an explicit comparison names a base ----------

LEVEL = {"id": "G1", "call": "Q3 FY26", "subject": "EBITDA margin", "target": "above 18%", "low": 18.0, "high": None,
         "unit": "%", "horizon": "Q4", "period": "Q4 FY26",
         "statement": "Q3 was soft at 14%; for Q4 we expect EBITDA margin above 18%."}
LEVEL_ROW = {"subject": "Q4 FY26 EBITDA margin", "promise": "EBITDA margin above 18% in Q4 FY26", "verdict": "missed",
             "guidance_ids": ["G1"], "fact_ids": ["calc.Q.ebitda_margin.Mar 2026"], "why": "16.03% is below 18%",
             "delivered": "16.03%"}


def _level(row, g, facts):
    r = copy.deepcopy(row)
    ledger._margin_guard(r, {"G1": g}, facts)
    ledger._range_check(r, {"G1": g}, facts)
    return r


def test_b1_quarter_mentioned_in_a_level_promise_is_not_a_base(monkeypatch):
    # Review probe B1: "Q3 was soft" attached Q3 FY26 (14.13%), flipped missed → delivered and disabled the range check.
    r = _level(LEVEL_ROW, LEVEL, _facts(monkeypatch))
    assert r["verdict"] == "missed" and "downgraded_from" not in r
    assert r["fact_ids"] == ["calc.Q.ebitda_margin.Mar 2026"] and "attached_fact_ids" not in r and "margin_check" not in r
    assert r["check"]["result"] == "below" and r["check"]["actual"] == 16.03 and r["check"]["low"] == 18.0


def test_b2_level_promise_without_another_quarter_is_judged_by_the_range_check(monkeypatch):
    r = _level(LEVEL_ROW, {**LEVEL, "statement": "For Q4 we expect EBITDA margin above 18%."}, _facts(monkeypatch))
    assert r["verdict"] == "missed" and r["check"]["result"] == "below" and "attached_fact_ids" not in r


def test_numeric_target_skips_base_detection_even_with_an_explicit_comparison(monkeypatch):
    g = {**LEVEL, "target": "above 18%, ahead of the Q2 run-rate"}
    r = _level(LEVEL_ROW, g, _facts(monkeypatch))
    assert r["verdict"] == "missed" and "attached_fact_ids" not in r and r["check"]["result"] == "below"


def test_b3_future_deadline_quarter_is_not_a_base(monkeypatch):
    # Review probe B3: "recover fully by Q4" on a Q2 FY27 promise was read as base Q4 FY26.
    g = {"id": "G1", "call": "Q1 FY27", "subject": "EBITDA margin", "target": "improve margins", "horizon": "Q2", "period": "Q2 FY27",
         "statement": "We expect margins to improve in Q2 and recover fully by Q4."}
    row = {"subject": "Q2 FY27 EBITDA margin", "promise": "margin improvement in Q2 FY27", "verdict": "delivered",
           "guidance_ids": ["G1"], "fact_ids": ["calc.Q.ebitda_margin.Sep 2026"], "why": "", "delivered": ""}
    assert ledger._base_quarter(row, {"G1": g}, periods.quarter(periods.FQ(27, 2))) == (None, None)
    r = copy.deepcopy(row)
    ledger._margin_guard(r, {"G1": g}, _facts(monkeypatch, TATATECH_Q_FY27))
    assert r["verdict"] == "delivered" and r["fact_ids"] == ["calc.Q.ebitda_margin.Sep 2026"] and "attached_fact_ids" not in r


@pytest.mark.parametrize("statement,base", [
    ("Despite labour codes, we will deliver EBITDA margins that exceed our Q2 run-rate.", "Q2 FY26"),  # explicit: used
    ("Q2 was a soft quarter; in Q4 we expect strong EBITDA margins.", None),                          # mentioned: not
    ("We expect EBITDA margins to stay strong until Q1.", None),                                       # deadline: not
])
def test_statement_counts_only_for_an_explicit_comparison(statement, base):
    g = {**GUIDANCE, "target": "strong EBITDA margins", "statement": statement}
    row = {**PROD_ROW, "subject": "Q4 FY26 EBITDA margin", "promise": "strong EBITDA margin in Q4 FY26"}
    q, _ = ledger._base_quarter(row, {"G2.2": g}, periods.quarter(periods.FQ(26, 4)))
    assert (q.label if q else None) == base


def test_later_quarter_named_in_a_comparison_is_not_a_base():
    g = {**GUIDANCE, "target": "margins above the Q1 FY27 level", "statement": "Q4 margins above the Q1 FY27 level."}
    row = {**PROD_ROW, "promise": "strong EBITDA margin in Q4 FY26"}  # the row's own text names no base either
    assert ledger._base_quarter(row, {"G2.2": g}, periods.quarter(periods.FQ(26, 4))) == (None, None)


def test_ambiguous_base_shows_the_exact_target_not_a_rounded_one(monkeypatch):
    g = {**GUIDANCE, "target": "exceed the Q2 and Q3 run-rates"}
    r = copy.deepcopy({**PROD_ROW, "fact_ids": ["Q.OPM %.Mar 2026"]})
    ledger._margin_guard(r, {"G2.2": g}, _facts(monkeypatch))
    assert r["verdict"] == "unverifiable" and r["margin_check"]["result"] == "base_ambiguous"
    assert r["fact_ids"] == ["calc.Q.ebitda_margin.Mar 2026"] and r["replaced_fact_ids"] == ["Q.OPM %.Mar 2026"]


def test_ambiguous_base_with_no_exact_target_keeps_what_was_cited(monkeypatch):
    F = _facts(monkeypatch)
    del F["calc.Q.ebitda_margin.Mar 2026"]               # nothing exact for Q4 FY26: nothing is invented
    g = {**GUIDANCE, "target": "exceed the Q2 and Q3 run-rates"}
    r = copy.deepcopy({**PROD_ROW, "fact_ids": ["Q.OPM %.Mar 2026"]})
    ledger._margin_guard(r, {"G2.2": g}, F)
    assert r["verdict"] == "unverifiable" and r["fact_ids"] == ["Q.OPM %.Mar 2026"] and "replaced_fact_ids" not in r


def test_bare_mention_of_the_promised_quarter_is_not_a_base(monkeypatch):
    g = {**GUIDANCE, "target": "deliver strong margins", "statement": "For Q4, we expect strong margins."}
    r = copy.deepcopy({**PROD_ROW, "promise": "strong EBITDA margin in Q4 FY26", "verdict": "on_track"})
    ledger._margin_guard(r, {"G2.2": g}, _facts(monkeypatch))
    assert "attached_fact_ids" not in r and r["verdict"] == "on_track"


def test_ledger_build_end_to_end_on_both_production_rows(monkeypatch):
    """Both production findings through ledger.build: the base is attached, and the H2 FY27 row is retitled with its
    too_early verdict kept."""
    F = _facts(monkeypatch, TATATECH_Q_FY27)
    g52 = {"id": "G5.2", "call": "Q2 FY27", "subject": "operating EBITDA margin", "target": "sequential margin improvement",
           "horizon": "H2 FY27", "period": "H2 FY27",
           "statement": "Against this backdrop, we expect to deliver sequential margin improvement through disciplined "
                        "execution and productivity initiatives."}
    h2 = {"subject": "Q2 FY27 sequential EBITDA margin improvement", "promise": "sequential margin improvement in H2 FY27",
          "verdict": "delivered", "guidance_ids": ["G5.2"],
          "fact_ids": ["calc.Q.ebitda_margin.Sep 2026", "calc.Q.ebitda_margin.Jun 2026"],
          "why": "Margins rose sequentially", "delivered": "Margins rose sequentially"}
    calls = [{"call": "Q2 FY27", "guidance": [g52]}, {"call": "Q3 FY26", "guidance": [GUIDANCE]}]
    monkeypatch.setattr(ledger, "chat_json", lambda *a, **k: {"rows": [copy.deepcopy(PROD_ROW), copy.deepcopy(h2)],
                                                               "credibility": "Management delivered on Q4 FY26 margins."})
    out = ledger.build(calls, F, "Sep 2026")
    rows = {r["subject"]: r for r in out["rows"]}
    m = rows["Q4 FY26 EBITDA margin"]
    assert m["verdict"] == "delivered" and [f["value"] for f in m["facts"]] == [16.03, 15.72]
    h = rows["H2 FY27 sequential EBITDA margin improvement"]
    assert h["verdict"] == "too_early" and h["downgraded_from"] == "delivered"
    assert h["subject_corrected_from"] == "Q2 FY27 sequential EBITDA margin improvement"
