"""Unit tests for the deterministic layer: the code that decides what the user sees regardless of any model."""
import datetime as dt
import json
import pathlib

import pytest

from finn.grounding import numbers, ungrounded
from finn.llm import _parse_json
from finn.pull import ledger
from finn.pull.transcripts import FORWARD, quarter_discussed
from finn.push import classify, score
from finn.push.enrich import _expected_qe
from finn.push.results import fy_label
from finn.sources.docs import find_quote, subject

HERE = pathlib.Path(__file__).parent


# ---------- classification ----------

def test_rule_coverage_on_two_weeks_of_market_filings():
    rows = json.loads((HERE / "nse_2w.json").read_text())
    covered = sum(classify.rule_classify(r["desc"], r["attchmntText"] or "")[0] is not None for r in rows)
    assert covered / len(rows) > 0.88, covered / len(rows)


@pytest.mark.parametrize("desc,text,expected", [
    ("Outcome of Board Meeting", "submitted the financial results for the period ended September 30, 2026", "results"),
    ("General Updates", "Q2 & H1 FY2027 Results Presentation", "results"),
    ("General Updates", "Name change of wholly owned Subsidiary", "unclassified"),
    ("Updates", "Intimation under Regulation 8(2) of the SEBI (Prohibition of Insider Trading)", "unclassified"),
    ("Allotment of Securities", "allotment of 37750 securities pursuant to ESOP", "unclassified"),
    ("Allotment of Securities", "allotment pursuant to Qualified Institution Placement", "fund_raise"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript of the earnings call", "earnings_call"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "participating in CLSA India Forum", "investor_meetings"),
    ("Resignation", "Resignation of CFO", "management_change"),
])
def test_rules(desc, text, expected):
    assert classify.rule_classify(desc, text)[0] == expected


# ---------- materiality ----------

def test_penalty_sized_against_revenue():
    s, reasons = score.score("litigation", "Action(s) taken or orders passed",
                             "Notice imposing a penalty of Rs. 1,07,000 for alleged violation", annual_revenue_cr=200_000)
    assert s < 45 and any("immaterial" in r for r in reasons)


def test_positive_adjustments_do_not_stack():
    s, _ = score.score("press_release", "News Verification", "clarification on news; order contract; fire at plant")
    assert s == score.BASE["press_release"] + 30  # only the strongest positive reason counts


def test_ceo_change_outranks_independent_director():
    ceo, _ = score.score("management_change", "Appointment", "Appointment of Managing Director and Chief Executive Officer")
    ind, _ = score.score("management_change", "Appointment", "Appointment of Independent Director")
    assert ceo >= 75 > ind


# ---------- grounding ----------

def test_number_parser_handles_currency_prefixes():
    assert numbers("INR48873.0 Cr vs ₹1,500 crore and Rs. 2,14,000; FY27 growth 46.7%") == [48873.0, 1500.0, 214000.0, 46.7]


def test_ungrounded_flags_invented_figures():
    assert ungrounded("Revenue rose 12.4% to ₹5,100 Cr", "revenue 12.4% ... 5,100") == []
    assert ungrounded("Revenue rose 15% to ₹5,100 Cr", "revenue 12.4% ... 5,100") == [15.0]


def test_json_parser_ignores_trailing_text():
    assert _parse_json('{"rows": [1]}\n{"extra": 2}') == {"rows": [1]}


# ---------- documents ----------

def test_find_quote_tolerates_ellipsis_and_page_breaks():
    doc = {"pages": ["We have expanded capacity from 80 million to 120 million annually and",
                     "we will further expand to 180 to 190 million units by next fiscal."]}
    assert find_quote(doc, "expanded capacity from 80 million to 120 million annually and we will further expand") == 1
    assert find_quote(doc, "expanded capacity from 80 million... to 180 to 190 million units by next fiscal") == 1
    assert find_quote(doc, "something management never said at all") is None


def test_subject_line():
    doc = {"pages": ["BSE Limited\nSub: Listing of Equity Shares of Jio Platforms Limited\nDear Sir/Madam,"]}
    assert subject(doc) == "Listing of Equity Shares of Jio Platforms Limited"


def test_forward_looking_filter():
    assert FORWARD.search("We expect margins to expand by 50 bps in FY28")
    assert not FORWARD.search("Revenues for the quarter was INR 21,806 crores.")
    assert not FORWARD.search("Willingness to pay improved")


# ---------- calendar ----------

@pytest.mark.parametrize("d,label", [(dt.date(2026, 9, 30), "Q2 FY27"), (dt.date(2026, 3, 31), "Q4 FY26"), (dt.date(2025, 12, 31), "Q3 FY26")])
def test_fy_label(d, label):
    assert fy_label(d) == label


def test_quarter_discussed_and_expected_quarter():
    assert quarter_discussed(dt.date(2026, 11, 1)) == "Q2 FY27"
    assert quarter_discussed(dt.date(2026, 2, 1)) == "Q3 FY26"
    assert _expected_qe(dt.datetime(2026, 10, 30, 19, 40)) == dt.date(2026, 9, 30)
    assert _expected_qe(dt.datetime(2026, 1, 25, 16, 0)) == dt.date(2025, 12, 31)


# ---------- Promise Ledger guards ----------

FACTS = {
    "calc.capex.Mar 2026": {"id": "calc.capex.Mar 2026", "label": "Capex (CFO − FCF)", "value": 1058.0, "unit": "₹ Cr", "period": "Mar 2026"},
    "A.Sales.TTM": {"id": "A.Sales.TTM", "label": "Sales", "value": 58523.0, "unit": "₹ Cr", "period": "TTM"},
    "X.PAT margin.Q2 FY27": {"id": "X.PAT margin.Q2 FY27", "label": "PAT margin (exchange filing)", "value": 16.0, "unit": "%", "period": "Q2 FY27"},
}
GUIDE = {"G1.1": {"id": "G1.1", "low": 1100, "high": 1200, "unit": "Cr", "call": "Q3 FY26"},
         "G1.2": {"id": "G1.2", "low": 100000, "high": None, "unit": "Cr", "call": "Q2 FY26"}}


def test_range_check_turns_lenient_delivered_into_missed():
    row = {"verdict": "delivered", "guidance_ids": ["G1.1"], "fact_ids": ["calc.capex.Mar 2026"], "why": "close to"}
    ledger._range_check(row, GUIDE, FACTS)
    assert row["verdict"] == "missed" and row["downgraded_from"] == "delivered"


def test_range_check_leaves_running_level_targets_alone():
    row = {"verdict": "on_track", "guidance_ids": ["G1.2"], "fact_ids": ["A.Sales.TTM"], "why": "3-4 year target"}
    ledger._range_check(row, GUIDE, FACTS)
    assert row["verdict"] == "on_track"


def test_metric_guard_blocks_proxy_for_nim():
    row = {"subject": "NIM trajectory", "promise": "net interest margin to rise", "verdict": "at_risk",
           "fact_ids": ["X.PAT margin.Q2 FY27"], "why": "", "delivered": ""}
    ledger._metric_guard(row, FACTS)
    assert row["verdict"] == "unverifiable" and row["fact_ids"] == []


def test_readable_ids_and_double_negative():
    out = ledger.readable_ids("A.Sales.TTM was up; profit fell -44.9%", FACTS)
    assert "A.Sales" not in out and "fell 44.9%" in out


def test_ledger_summary_keeps_rupee_numbers_parseable():
    c = ledger.compact({"rows": [{"subject": "Telecom", "verdict": "goalposts_moved", "why": "cut to ₹6,700-7,000 crore"}]})
    assert ungrounded("lowered to ₹6,700-7,000 crore", c) == []


def test_analyst_questions_are_not_guidance():
    from finn.pull.transcripts import _INTRODUCED, _person, speaker_at
    full = ("\nModerator: \nThe next question is from the line of Nitin Kaushik with Afin Capital. \nNitin Kaushik: \n"
            "Sir, you reiterated that the company is targeting over INR1 lakh crore revenue. \nAtul Lall: \n"
            "Yes, we will reach it in 3 to 4 years. \nNitin Kaushik: \nThanks. \nAtul Lall: \nWelcome. \n"
            "Home Appliances: \nWe expect 20% growth in washing machines next year.\n")
    analysts = frozenset(_person(n) for n in _INTRODUCED.findall(full))
    assert speaker_at(full, "you reiterated that the company is targeting over INR1 lakh crore", analysts) == "Nitin Kaushik"
    assert speaker_at(full, "we will reach it in 3 to 4 years", analysts) == "Atul Lall"
    assert speaker_at(full, "We expect 20% growth in washing machines next year", analysts) == "Atul Lall"  # heading skipped


def test_missed_requires_an_ended_horizon():
    g = {"G1": {"id": "G1", "horizon": "next 1, 2, 3 years", "call": "Q4 FY26"}, "G2": {"id": "G2", "horizon": "FY26", "call": "Q2 FY26"}}
    open_row = {"verdict": "missed", "guidance_ids": ["G1"], "why": ""}
    ledger._horizon_guard(open_row, g, "Sep 2026")
    assert open_row["verdict"] == "at_risk"
    ended_row = {"verdict": "missed", "guidance_ids": ["G2"], "why": ""}
    ledger._horizon_guard(ended_row, g, "Sep 2026")
    assert ended_row["verdict"] == "missed"  # FY26 ended before the Sep 2026 (FY27) quarter
