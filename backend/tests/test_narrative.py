"""Narrative consistency: the memo's prose must agree with the figures it cites and with the final ledger verdicts.

Regression cases from the production TATATECH memo rebuilt on 2026-11-09 (edc3910), kept in narrative_fixture.json
together with the DIXON and HDFCBANK memos (public data):
  - bull 2 "EBITDA margin improved sequentially to 16.1% in Q2 FY27, validating the promise of sequential margin
    improvement" — the cited pair is Q2 FY27 vs Q2 FY26 (year-on-year), and the promise (H2 FY27) is too_early;
  - credibility "… but missed the FY27 operating-margin goal" — that row is at_risk.
"""
import copy
import json
import pathlib

import pytest

from finn.pull import ledger, narrative, periods, research, thesis, verify

HERE = pathlib.Path(__file__).parent
FIX = json.loads((HERE / "narrative_fixture.json").read_text(encoding="utf-8"))
TT = FIX["TATATECH"]
LATEST = periods.from_calendar(TT["latest_quarter"])  # Q2 FY27
LED = {f"L{i + 1}": r for i, r in enumerate(TT["ledger_rows"])}
BULL2 = TT["thesis"]["bull"][1]


def _fact(fid, value, period, label="EBITDA margin"):
    return {"type": "fact", "id": fid, "label": label, "value": value, "unit": "%", "period": period}


YOY_PAIR = [_fact("X.EBITDA margin.Q2 FY27", 16.1, "Q2 FY27"), _fact("X.EBITDA margin.Q2 FY26", 15.7, "Q2 FY26")]
SEQ_PAIR = [_fact("calc.Q.ebitda_margin.Jun 2026", 16.04, "Jun 2026"), _fact("calc.Q.ebitda_margin.Sep 2026", 16.07, "Sep 2026")]


# ---------- 1. the TATATECH bull point ----------

def test_production_bull_point_is_the_regression_case():
    assert BULL2["point"] == ("EBITDA margin improved sequentially to 16.1% in Q2 FY27, validating the promise of "
                              "sequential margin improvement.")
    assert BULL2["refs"] == ["L3", "X.EBITDA margin.Q2 FY27", "G5.2", "X.EBITDA margin.Q2 FY26"]


def test_year_apart_pair_called_sequential_is_flagged():
    assert narrative.comparison_issue(BULL2["point"], BULL2["evidence"]) == \
        "Calls a Q2 FY27 vs Q2 FY26 comparison sequential; the same quarter a year apart is year-on-year."


def test_validating_an_unstarted_promise_is_flagged():
    issue = narrative.promise_issue(BULL2["point"], BULL2["refs"], BULL2["evidence"], LED, LATEST)
    assert issue == ("Says a promise is met, but the ledger marks 'H2 FY27 EBITDA margin improvement' too early to judge "
                     "(H2 FY27 hasn't started).")


def test_both_reasons_reach_the_rewrite():
    issues = narrative.thesis_issues(TT["thesis"], {"rows": TT["ledger_rows"]}, LATEST)
    assert list(issues) == ["bull2"]  # the other five TATATECH points pass
    assert "year-on-year" in issues["bull2"]["issue"] and "too early to judge" in issues["bull2"]["issue"]


@pytest.mark.parametrize("point,evidence", [
    ("EBITDA margin rose to 16.1% in Q2 FY27 from 15.7% a year earlier.", YOY_PAIR),
    ("EBITDA margin rose year-on-year to 16.1% in Q2 FY27.", YOY_PAIR),
    ("EBITDA margin improved sequentially to 16.07% in Q2 FY27 from 16.04% in Q1 FY27.", SEQ_PAIR),
])
def test_correctly_labelled_comparisons_pass(point, evidence):
    assert narrative.comparison_issue(point, evidence) is None


def test_adjacent_quarters_called_year_on_year_are_flagged():
    assert "sequential" in narrative.comparison_issue("Margin rose 3 bps year-on-year to 16.07%.", SEQ_PAIR)


# The two false positives from the PR #1 review: "sequential" names management's promise, not the cited comparison.
@pytest.mark.parametrize("point", [
    "EBITDA margin rose to 16.1% in Q2 FY27 from 15.7% a year earlier; the H2 FY27 sequential improvement promise is still untested.",
    "EBITDA margin rose year-on-year to 16.1%, consistent with guidance for sequential margin improvement in H2 FY27.",
])
def test_sequential_naming_a_future_promise_is_not_flagged(point):
    assert narrative.comparison_issue(point, YOY_PAIR) is None
    assert narrative.promise_issue(point, BULL2["refs"], BULL2["evidence"], LED, LATEST) is None


@pytest.mark.parametrize("point", [
    "EBITDA margin improved sequentially to 16.1% in Q2 FY27.",                           # the original claim
    "EBITDA margin improved sequentially to 16.1% in Q2 FY27, validating the promise of sequential margin improvement.",
    "Margin improved sequentially as guided, to 16.1% in Q2 FY27.",                       # "as guided" is not a promise noun
    "Management expects sequential improvement; margin already rose 16.1% sequentially.",  # second clause is the claim
])
def test_sequential_describing_a_year_apart_pair_is_still_flagged(point):
    assert "is year-on-year" in narrative.comparison_issue(point, YOY_PAIR)


# ---------- growth facts that are themselves a comparison (local TATATECH rebuild on 016a6d6, 2026-11-10) ----------
# bear 3 was correct but flagged: its sequential claim rests on calc.Q.pat_qoq (one figure, already quarter-on-quarter),
# and the only quarterly pair it cites is the year-apart PAT margin — which it correctly calls year-on-year.

BEAR3 = {"point": "Sequential PAT dropped 5.5% in Sep 2026 (Q2 FY27) versus Jun 2026 (Q1 FY27), with PAT margin declining "
                  "year-on-year to 10.1% in Q2 FY27 from 12.5% in Q2 FY26.",
         "refs": ["calc.Q.pat_qoq.Sep 2026", "X.PAT margin.Q2 FY27", "X.PAT margin.Q2 FY26"],
         "evidence": [_fact("calc.Q.pat_qoq.Sep 2026", -5.5, "Sep 2026", "PAT growth QoQ (sequential)"),
                      _fact("X.PAT margin.Q2 FY27", 10.1, "Q2 FY27", "PAT margin (exchange filing)"),
                      _fact("X.PAT margin.Q2 FY26", 12.5, "Q2 FY26", "PAT margin (exchange filing)")]}
BEAR3_DRAFT = ("PAT margin declined from 12.5% (Q2 FY26) to 10.1% (Q2 FY27), with sequential PAT dropping -5.5% in Sep 2026 "
               "(Q2 FY27) versus Jun 2026 (Q1 FY27).")
REV_YOY = _fact("X.revenue_yoy.Q2 FY27", 28.4, "Q2 FY27", "Revenue growth YoY (exchange filing)")
REV_QOQ = _fact("calc.Q.revenue_qoq.Sep 2026", 2.0, "Sep 2026", "Revenue growth QoQ (sequential)")


@pytest.mark.parametrize("point", [BEAR3["point"], BEAR3_DRAFT])
def test_tatatech_bear3_quarter_on_quarter_fact_is_sequential_evidence(point):
    assert narrative.comparison_issue(point, BEAR3["evidence"]) is None


def test_tatatech_bear3_passes_every_thesis_check_and_bull2_is_still_caught():
    th = copy.deepcopy(TT["thesis"])
    th["bear"][2] = copy.deepcopy(BEAR3)
    issues = narrative.thesis_issues(th, {"rows": TT["ledger_rows"]}, LATEST)
    assert list(issues) == ["bull2"] and "year-on-year" in issues["bull2"]["issue"]


@pytest.mark.parametrize("point,evidence,expected", [
    # the year-apart PAT margin pair called sequential — a PAT QoQ figure alongside does not excuse it
    ("PAT margin declined sequentially to 10.1% in Q2 FY27 from 12.5% in Q2 FY26.", BEAR3["evidence"],
     "Calls a Q2 FY27 vs Q2 FY26 comparison sequential"),
    ("Sequential PAT margin fell to 10.1%, while PAT dropped 5.5%.", BEAR3["evidence"],
     "Calls a Q2 FY27 vs Q2 FY26 comparison sequential"),
    # a QoQ figure for a different metric does not make an EBITDA-margin year-apart pair sequential (bull 2's error)
    ("EBITDA margin improved sequentially to 16.1% in Q2 FY27.", YOY_PAIR + [BEAR3["evidence"][0]],
     "Calls a Q2 FY27 vs Q2 FY26 comparison sequential"),
    # a single YoY figure called sequential, and a single QoQ figure called year-on-year
    ("Revenue grew 28.4% sequentially in Q2 FY27.", [REV_YOY], "Calls the Q2 FY27 year-on-year revenue change sequential"),
    ("PAT fell 5.5% year-on-year in Q2 FY27.", [BEAR3["evidence"][0]], "Calls the Q2 FY27 quarter-on-quarter pat change year-on-year"),
])
def test_wrong_comparison_words_are_still_flagged(point, evidence, expected):
    assert narrative.comparison_issue(point, evidence).startswith(expected)


@pytest.mark.parametrize("point,evidence", [
    ("Revenue grew 28.4% year-on-year and 2% sequentially in Q2 FY27.", [REV_YOY, REV_QOQ]),
    ("Revenue growth accelerated to 28.4% YoY in Sep 2026 (Q2 FY27).", [REV_YOY]),
    ("EBITDA margin improved sequentially to 16.07% while rising year-on-year to 16.1%.", YOY_PAIR + SEQ_PAIR),
])
def test_growth_facts_and_pairs_support_their_own_comparison_words(point, evidence):
    assert narrative.comparison_issue(point, evidence) is None


@pytest.mark.parametrize("fid,expected", [
    ("calc.Q.pat_qoq.Sep 2026", ("pat", "qoq")), ("calc.Q.revenue_yoy.Mar 2026", ("revenue", "yoy")),
    ("X.pat_yoy.Q2 FY27", ("pat", "yoy")), ("X.PAT margin.Q2 FY27", ("pat margin", None)),
    ("X.EBITDA margin.Q2 FY27", ("ebitda margin", None)), ("calc.Q.ebitda_margin.Sep 2026", ("ebitda margin", None)),
    ("Q.OPM %.Sep 2026", ("ebitda margin", None)), ("Q.Sales.Sep 2026", ("revenue", None)),
])
def test_fact_ids_map_to_one_metric_across_sources(fid, expected):
    assert narrative._metric(fid) == expected


def test_year_on_year_naming_a_promise_is_not_flagged():
    point = "Margin edged up to 16.07% in Q2 FY27 from 16.04%, ahead of the year-on-year improvement target."
    assert narrative.comparison_issue(point, SEQ_PAIR) is None


@pytest.mark.parametrize("point", [
    "EBITDA margin rose to 16.1% in Q2 FY27, consistent with the H2 FY27 margin-improvement guidance, which is untested.",
    "The H2 FY27 margin promise has not yet been validated.",
    "Management has yet to deliver on the H2 FY27 margin target.",
])
def test_untested_promise_described_honestly_passes(point):
    assert narrative.promise_issue(point, BULL2["refs"], BULL2["evidence"], LED, LATEST) is None


def test_validating_a_delivered_promise_passes():
    point = "Q4 FY26 EBITDA margin of 16.03% beat the Q2 run-rate, validating the promise."
    assert narrative.promise_issue(point, ["L3"], [], LED, LATEST) is None  # L3 = Q4 FY26 EBITDA margin, delivered


def test_unstarted_guidance_without_a_ledger_row_is_still_checked():
    g = {"type": "guidance", "id": "G9.9", "call": "Q2 FY27", "horizon": "H2 FY27", "statement": "Margins will improve in H2."}
    assert "H2 FY27, which hasn't started" in narrative.promise_issue("This confirms the margin guidance.", ["G9.9"], [g], {}, LATEST)


# ---------- 2. the credibility summary ----------

def test_production_credibility_contradicting_the_ledger_is_flagged():
    assert "missed the FY27 operating‑margin goal" in TT["credibility"]
    assert narrative.credibility_issue(TT["credibility"], TT["ledger_rows"]) == \
        "Says 'missed' about 'FY27 operating margin run rate', which the ledger marks at_risk."


def test_credibility_guard_replaces_it_with_the_ledger_record():
    result = {"rows": copy.deepcopy(TT["ledger_rows"]), "credibility": TT["credibility"]}
    ledger._credibility_guard(result)
    assert result["credibility"] == (
        "Of 7 promises tracked: 2 delivered (Q4 FY26 sequential revenue growth; Q4 FY26 EBITDA margin), 1 at risk "
        "(FY27 operating margin run rate), 1 on track (FY27 revenue growth), 1 too early to judge (H2 FY27 EBITDA "
        "margin improvement) and 2 not verifiable from the filings.")
    assert result["credibility_check"]["replaced"] == TT["credibility"]
    assert "missed" not in result["credibility"]


@pytest.mark.parametrize("text", [
    "Management reliably hit sequential revenue and margin targets; the FY27 operating-margin goal is at risk.",
    "Management delivered on Q4 FY26 sequential revenue growth and EBITDA margin; FY27 margins are under pressure.",
])
def test_consistent_credibility_is_kept(text):
    result = {"rows": copy.deepcopy(TT["ledger_rows"]), "credibility": text}
    ledger._credibility_guard(result)
    assert result["credibility"] == text and "credibility_check" not in result


@pytest.mark.parametrize("sym", ["DIXON", "HDFCBANK"])
def test_dixon_and_hdfcbank_prose_raises_no_flags(sym):
    m = FIX[sym]
    assert narrative.credibility_issue(m["credibility"], m["ledger_rows"]) is None  # "missing data", "capex … misses"
    assert narrative.thesis_issues(m["thesis"], {"rows": m["ledger_rows"]}, periods.from_calendar(m["latest_quarter"])) == {}


def test_missed_with_no_missed_promise_at_all_is_flagged():
    rows = [{"subject": "FY27 revenue growth", "verdict": "on_track"}]
    assert narrative.credibility_issue("Management missed its guidance.", rows) == \
        "Says 'missed', but no promise in the ledger is missed."


# ---------- the research pipeline acts on the flags ----------

FIN = {"trajectory": {"quarterly": [{"period": "Sep 2026"}]}}
POINTS = ["bull1", "bull2", "bull3", "bear1", "bear2", "bear3"]


def _secs(sym="TATATECH"):
    rows = copy.deepcopy(FIX[sym]["ledger_rows"])
    for r in rows:
        r.setdefault("facts", []), r.setdefault("delivered", ""), r.setdefault("why", "")
    return {"thesis": copy.deepcopy(FIX[sym]["thesis"]), "ledger": {"rows": rows}}


def _all_supported(claims):
    return {c["id"]: {"supported": True, "issue": ""} for c in claims}


def _verifier(*passes):
    """A verifier whose n-th call returns passes[n](claims); {} means the model was unavailable."""
    calls = []

    def check(claims):
        calls.append([c["id"] for c in claims])
        return passes[len(calls) - 1](claims)
    return check, calls


def _verified(secs):
    return {f"{side}{i + 1}": p["verified"] for side in ("bull", "bear") for i, p in enumerate(secs["thesis"][side])}


def _corrected(fin, calls, led, feedback=None):
    th = copy.deepcopy(TT["thesis"])
    th["bull"][1] = {"point": "EBITDA margin rose to 16.1% in Q2 FY27 from 15.7% a year earlier; the H2 FY27 "
                              "sequential improvement promise is still untested.", "refs": BULL2["refs"], "evidence": BULL2["evidence"]}
    return th


def test_flagged_point_is_rewritten_even_when_the_second_model_misses_it(monkeypatch):
    # In production the verifier passed bull 2. FINN's own check must still send it back for a rewrite.
    monkeypatch.setattr(research.verify, "check", lambda claims: {c["id"]: {"supported": True, "issue": ""} for c in claims})
    seen = {}

    def rewrite(fin, calls, led, feedback=None):
        seen["feedback"] = feedback
        th = copy.deepcopy(TT["thesis"])
        th["bull"][1] = {"point": "EBITDA margin rose to 16.1% in Q2 FY27 from 15.7% a year earlier; the H2 FY27 "
                                  "improvement promise is still untested.", "refs": BULL2["refs"], "evidence": BULL2["evidence"]}
        return th

    monkeypatch.setattr(research.thesis, "build", rewrite)
    secs = _secs()
    research._verify({"trajectory": {"quarterly": [{"period": "Sep 2026"}]}}, [], secs)
    assert len(seen["feedback"]) == 1 and seen["feedback"][0].startswith('"EBITDA margin improved sequentially')
    assert secs["verification"]["rewrote_thesis"] is True and secs["verification"]["flagged"] == 0
    assert secs["thesis"]["bull"][1]["verified"] is True
    v = secs["verification"]
    assert (v["status"], v["recheck"], v["unchecked"]) == ("done", "done", 0)


def test_point_still_wrong_after_the_rewrite_stays_flagged(monkeypatch):
    monkeypatch.setattr(research.verify, "check", lambda claims: {c["id"]: {"supported": True, "issue": ""} for c in claims})
    monkeypatch.setattr(research.thesis, "build", lambda fin, calls, led, feedback=None: copy.deepcopy(TT["thesis"]))
    secs = _secs()
    research._verify({"trajectory": {"quarterly": [{"period": "Sep 2026"}]}}, [], secs)
    p = secs["thesis"]["bull"][1]
    assert p["verified"] is False and "year-on-year" in p["issue"] and secs["verification"]["flagged"] == 1


def test_narrative_checks_run_when_no_verifier_model_is_available(monkeypatch):
    monkeypatch.setattr(research.verify, "check", lambda claims: {})
    monkeypatch.setattr(research.thesis, "build", lambda fin, calls, led, feedback=None: copy.deepcopy(TT["thesis"]))
    secs = _secs()
    research._verify({"trajectory": {"quarterly": [{"period": "Sep 2026"}]}}, [], secs)
    assert secs["verification"]["status"] == "narrative_only" and secs["thesis"]["bull"][1]["verified"] is False
    # no model judged the other five: unchecked, not verified
    assert {k: v for k, v in _verified(secs).items() if k != "bull2"} == dict.fromkeys(POINTS[:1] + POINTS[2:])
    assert secs["verification"]["unchecked"] == 5


# ---------- the second (post-rewrite) verifier pass ----------

def test_verifier_unavailable_for_the_rewrite_leaves_every_point_unchecked(monkeypatch):
    check, seen = _verifier(_all_supported, lambda claims: {})  # passes the draft, then quota runs out
    monkeypatch.setattr(research.verify, "check", check)
    monkeypatch.setattr(research.thesis, "build", _corrected)
    secs = _secs()
    research._verify(FIN, [], secs)
    assert len(seen) == 2 and all(k.startswith(("bull", "bear")) for k in seen[1])  # the rewrite was sent for checking
    assert _verified(secs) == dict.fromkeys(POINTS)                                  # none silently "verified"
    v = secs["verification"]
    assert (v["status"], v["recheck"], v["unchecked"], v["flagged"], v["rewrote_thesis"]) == \
        ("rewrite_unverified", "unavailable", 6, 0, True)
    assert all(r["verified"] is True for r in secs["ledger"]["rows"] if r["verdict"] != "unverifiable")  # first pass stands


def test_narrative_flag_survives_an_unavailable_second_pass(monkeypatch):
    check, _ = _verifier(_all_supported, lambda claims: {})
    monkeypatch.setattr(research.verify, "check", check)
    monkeypatch.setattr(research.thesis, "build", lambda fin, calls, led, feedback=None: copy.deepcopy(TT["thesis"]))
    secs = _secs()
    research._verify(FIN, [], secs)
    assert _verified(secs) == {**dict.fromkeys(POINTS), "bull2": False}
    assert "year-on-year" in secs["thesis"]["bull"][1]["issue"]
    v = secs["verification"]
    assert (v["status"], v["flagged"], v["unchecked"]) == ("rewrite_unverified", 1, 5)


def test_points_the_verifier_skipped_in_the_second_pass_are_unchecked(monkeypatch):
    partial = lambda claims: {c["id"]: {"supported": True, "issue": ""} for c in claims if c["id"] not in ("bear2", "bear3")}  # noqa: E731
    check, _ = _verifier(_all_supported, partial)
    monkeypatch.setattr(research.verify, "check", check)
    monkeypatch.setattr(research.thesis, "build", _corrected)
    secs = _secs()
    research._verify(FIN, [], secs)
    assert _verified(secs) == {**dict.fromkeys(POINTS, True), "bear2": None, "bear3": None}
    v = secs["verification"]
    assert (v["status"], v["recheck"], v["unchecked"]) == ("done", "done", 2)


@pytest.mark.parametrize("sym", ["DIXON", "HDFCBANK"])
def test_no_rewrite_when_nothing_is_flagged_and_skipped_points_are_unchecked(monkeypatch, sym):
    skip_last = lambda claims: {c["id"]: {"supported": True, "issue": ""} for c in claims if c["id"] != "bear3"}  # noqa: E731
    check, seen = _verifier(skip_last)
    monkeypatch.setattr(research.verify, "check", check)
    monkeypatch.setattr(research.thesis, "build", lambda *a, **k: pytest.fail("no rewrite expected"))
    secs = _secs(sym)
    research._verify(FIN, [], secs)
    assert len(seen) == 1 and _verified(secs) == {**dict.fromkeys(POINTS, True), "bear3": None}
    v = secs["verification"]
    assert (v["status"], v["recheck"], v["unchecked"], v["rewrote_thesis"]) == ("done", None, 1, False)


# ---------- what the thesis and verifier models are told ----------

def _fin():
    facts = {f["id"]: {k: f[k] for k in ("id", "label", "value", "unit", "period")} for f in YOY_PAIR + SEQ_PAIR}
    facts["calc.Q.revenue_qoq.Sep 2026"] = {"id": "calc.Q.revenue_qoq.Sep 2026", "label": "Revenue growth QoQ (sequential)",
                                            "value": 2.0, "unit": "%", "period": "Sep 2026"}
    return {"signals": [], "facts": facts, "trajectory": {"quarterly": [{"period": "Jun 2026"}, {"period": "Sep 2026"}]}}


def test_thesis_prompt_states_promise_status_and_the_sequential_pair(monkeypatch):
    g52 = next(e for e in BULL2["evidence"] if e["type"] == "guidance")
    calls = [{"call": "Q2 FY27", "guidance": [{k: v for k, v in g52.items() if k != "type"}], "analyst_focus": []}]
    prompts = []

    def fake(tag, tier, system, user, max_tokens):
        prompts.append((system, user))
        return {"bull": [{"point": "EBITDA margin improved sequentially to 16.07% in Q2 FY27.", "refs": ["calc.Q.ebitda_margin.Sep 2026"]}],
                "bear": [], "watch": None}

    monkeypatch.setattr(thesis, "chat_json", fake)
    out = thesis.build(_fin(), calls, {"rows": TT["ledger_rows"]})
    system, user = prompts[0]
    assert "G5.2: operating EBITDA margin" in user and "(period H2 FY27; ledger verdict: too_early)" in user
    assert "calc.Q.ebitda_margin.Sep 2026 = 16.07% (EBITDA margin, Sep 2026 = Q2 FY27)" in user
    assert "calc.Q.ebitda_margin.Jun 2026 = 16.04%" in user and "calc.Q.revenue_qoq.Sep 2026 = 2%" in user
    assert "is \"year-on-year\", never \"sequential\"" in system and "only if its verdict is \"delivered\"" in system
    p = out["bull"][0]
    assert p["refs"] == ["calc.Q.ebitda_margin.Sep 2026", "calc.Q.ebitda_margin.Jun 2026"]  # the pair is cited
    assert narrative.comparison_issue(p["point"], p["evidence"]) is None


def test_verifier_sees_ledger_verdict_on_guidance_and_the_sequential_rule():
    g = {"type": "guidance", "call": "Q2 FY27", "horizon": "H2 FY27", "statement": "…", "ledger_verdict": "too_early"}
    assert verify._evidence_text(g).endswith("[promise-ledger verdict: too_early]")
    assert "(Q2 FY27 vs Q2 FY26) is year-on-year" in verify.SYSTEM
    assert "unless its promise-ledger verdict is \"delivered\"" in verify.SYSTEM


def test_ledger_prompt_ties_credibility_to_the_verdicts():
    assert "say a promise was missed only if its row is \"missed\"" in ledger.SYSTEM


# ---------- final pass: TATATECH bull 2 (production memo 2026-11-10 06:03, built on d41ad7e) ----------
# After its one rewrite the point still said "…, validating sequential margin improvement guidance" — a promise the
# ledger marks too_early (H2 FY27 hasn't started). The year-on-year comparison before the comma is correct.

G52_0603 = {"type": "guidance", "id": "G5.2", "call": "Q2 FY27", "subject": "operating EBITDA margin",
            "statement": "Against this backdrop, we expect to deliver sequential margin improvement through disciplined "
                         "execution and productivity initiatives.",
            "target": "sequential margin improvement", "horizon": "H2 FY27", "period": "H2 FY27", "ledger_verdict": "too_early"}
BULL2_0603 = {"point": "Q2 FY27 EBITDA margin of 16.1% exceeded Q2 FY26's 15.7%, validating sequential margin improvement guidance.",
              "refs": ["X.EBITDA margin.Q2 FY27", "X.EBITDA margin.Q2 FY26", "G5.2"],
              "evidence": [_fact("X.EBITDA margin.Q2 FY27", 16.1, "Q2 FY27", "EBITDA margin (exchange filing)"),
                           _fact("X.EBITDA margin.Q2 FY26", 15.7, "Q2 FY26", "EBITDA margin (exchange filing)"), G52_0603]}
ROWS_0603 = [{"subject": "Q4 FY26 EBITDA margin", "verdict": "delivered", "guidance_ids": ["G2.2"], "evidence": [], "facts": [],
              "delivered": "", "why": ""},
             {"subject": "H2 FY27 sequential EBITDA margin improvement", "verdict": "too_early", "guidance_ids": ["G5.2"],
              "evidence": [{k: v for k, v in G52_0603.items() if k not in ("type", "ledger_verdict")}], "facts": [],
              "delivered": "", "why": ""}]
LED_0603 = {f"L{i + 1}": r for i, r in enumerate(ROWS_0603)}
PLAIN = {"point": "Debt/equity rose from 0.07x in Mar 2025 to 0.29x in Sep 2026.", "refs": ["S5"],
         "evidence": [{"type": "signal", "tone": "neg", "text": "Debt/equity 0.07x → 0.29x"}]}


def test_production_tatatech_bull2_is_still_flagged_as_written():
    assert "too early to judge" in narrative.promise_issue(BULL2_0603["point"], BULL2_0603["refs"], BULL2_0603["evidence"], LED_0603, LATEST)


def test_tatatech_bull2_repair_keeps_the_year_on_year_comparison_and_drops_the_unmet_claim():
    point, refs, evidence = narrative.trim_unmet_promise_claim(BULL2_0603["point"], BULL2_0603["refs"],
                                                               BULL2_0603["evidence"], LED_0603, LATEST)
    assert point == "Q2 FY27 EBITDA margin of 16.1% exceeded Q2 FY26's 15.7%."
    assert refs == ["X.EBITDA margin.Q2 FY27", "X.EBITDA margin.Q2 FY26"]          # G5.2 only served the removed clause
    assert [e["id"] for e in evidence] == refs
    th = {"bull": [{"point": point, "refs": refs, "evidence": evidence}], "bear": []}
    assert narrative.thesis_issues(th, {"rows": ROWS_0603}, LATEST) == {}


@pytest.mark.parametrize("point", [
    "Margin of 16.1% validates the H2 FY27 sequential margin improvement guidance.",   # the claim is the main clause
    "This confirms the guidance, with margin at 16.1%.",
    "Validating the margin guidance, the Q2 FY27 margin rose to 16.1%.",
])
def test_repair_refuses_when_the_unmet_claim_is_the_main_clause(point):
    assert narrative.trim_unmet_promise_claim(point, BULL2_0603["refs"], BULL2_0603["evidence"], LED_0603, LATEST) is None


def test_repair_leaves_sound_points_alone():
    assert narrative.trim_unmet_promise_claim("Q2 FY27 EBITDA margin of 16.1% exceeded Q2 FY26's 15.7%.",
                                              BULL2_0603["refs"], BULL2_0603["evidence"], LED_0603, LATEST) is None
    delivered = "Q4 FY26 EBITDA margin of 16.03% beat the Q2 run-rate, validating the promise."
    assert narrative.trim_unmet_promise_claim(delivered, ["L1"], [], LED_0603, LATEST) is None   # L1 is delivered


def _thesis_0603():
    return {"bull": [copy.deepcopy(PLAIN), copy.deepcopy(BULL2_0603), copy.deepcopy(PLAIN)],
            "bear": [copy.deepcopy(PLAIN) for _ in range(3)], "watch": None}


def _run_0603(monkeypatch, passes):
    check, seen = _verifier(*passes)
    monkeypatch.setattr(research.verify, "check", check)
    monkeypatch.setattr(research.thesis, "build", lambda fin, calls, led, feedback=None: _thesis_0603())  # model repeats it
    secs = {"thesis": _thesis_0603(), "ledger": {"rows": copy.deepcopy(ROWS_0603)}}
    research._verify(FIN, [], secs)
    return secs, seen


def test_pipeline_repairs_the_point_the_rewrite_repeated_and_reverifies_it(monkeypatch):
    secs, seen = _run_0603(monkeypatch, [_all_supported] * 3)
    p, v = secs["thesis"]["bull"][1], secs["verification"]
    assert p["point"] == "Q2 FY27 EBITDA margin of 16.1% exceeded Q2 FY26's 15.7%." and p["trimmed_from"] == BULL2_0603["point"]
    assert p["verified"] is True and p["refs"] == ["X.EBITDA margin.Q2 FY27", "X.EBITDA margin.Q2 FY26"]
    assert len(seen) == 3 and "bull2" in seen[2]                       # the trimmed text went back to the verifier
    assert (v["status"], v["trimmed"], v["trim_recheck"], v["flagged"], v["unchecked"]) == ("done", ["bull2"], "done", 0, 0)


def test_repaired_point_is_unchecked_not_verified_when_the_verifier_is_unavailable(monkeypatch):
    secs, _ = _run_0603(monkeypatch, [_all_supported, _all_supported, lambda claims: {}])
    p, v = secs["thesis"]["bull"][1], secs["verification"]
    assert p["point"].endswith("15.7%.") and p["verified"] is None
    assert (v["status"], v["trim_recheck"]) == ("rewrite_unverified", "unavailable") and v["unchecked"] == 1


def test_repaired_point_the_verifier_still_rejects_stays_flagged(monkeypatch):
    reject = lambda claims: {c["id"]: ({"supported": False, "issue": "verifier objection"} if c["id"] == "bull2"  # noqa: E731
                                       else {"supported": True, "issue": ""}) for c in claims}
    secs, _ = _run_0603(monkeypatch, [_all_supported, _all_supported, reject])
    p = secs["thesis"]["bull"][1]
    assert p["verified"] is False and p["issue"] == "verifier objection" and secs["verification"]["flagged"] == 1


def test_no_repair_without_a_rewrite_and_none_for_comparison_errors(monkeypatch):
    # bull 2 of the original production memo (sequential + validated): the comparison error is not trimmed away
    th = copy.deepcopy(TT["thesis"])
    monkeypatch.setattr(research.verify, "check", _all_supported)
    monkeypatch.setattr(research.thesis, "build", lambda fin, calls, led, feedback=None: copy.deepcopy(th))
    secs = {"thesis": copy.deepcopy(th), "ledger": {"rows": _secs()["ledger"]["rows"]}}
    research._verify(FIN, [], secs)
    assert secs["thesis"]["bull"][1]["verified"] is False and secs["verification"]["trimmed"] == []


# ---------- final pass: HDFCBANK's three disputed points (production memo 2026-11-09 14:47) ----------
HD = FIX["HDFCBANK"]


def test_hdfcbank_bull2_and_bear2_verifier_now_sees_the_topic_the_writer_saw():
    # The quotes say "the trajectory" / "our margin decline"; FINN's extraction tied them to Net Interest Margin. The
    # thesis writer saw that topic, the verifier did not — so it rejected "Net Interest Margin" as not in the evidence.
    bull2, bear2 = HD["thesis"]["bull"][1], HD["thesis"]["bear"][1]
    assert "Net Interest Margin" in bull2["point"] and "net interest margins" in bear2["point"]
    g = verify._evidence_text(bull2["evidence"][0])
    a = verify._evidence_text(bear2["evidence"][0])
    assert g == ('Management said (Q2 FY27 call) about Q3 FY27 [topic, as FINN extracted it: Net Interest Margin (NIM)]: '
                 '"The trajectory will be upward from the next quarter onwards."')
    assert a.startswith("An analyst asked [topic, as FINN extracted it: Net Interest Margin (NIM) compression]: \"why still our margin")
    assert "figures and conclusions must still come from the quote" in verify.SYSTEM


def _hd_fin():
    roa = {f"calc.roa.Mar {y}": v for y, v in ((2023, 1.98), (2024, 2.0), (2025, 1.74), (2026, 1.7))}
    facts = {k: {"id": k, "label": "Return on average assets", "value": v, "unit": "%", "period": f"FY{k[-2:]}"} for k, v in roa.items()}
    return {"signals": [], "facts": facts, "trajectory": {"quarterly": [{"period": "Jun 2026"}, {"period": "Sep 2026"}]}}


def _thesis_with(monkeypatch, point, refs):
    monkeypatch.setattr(thesis, "chat_json", lambda *a, **k: {"bull": [], "bear": [{"point": point, "refs": refs}], "watch": None})
    return thesis.build(_hd_fin(), [], {"rows": []})["bear"][0]


def test_hdfcbank_bear1_quoted_fy24_figure_is_attached_from_the_same_metric(monkeypatch):
    point = HD["thesis"]["bear"][0]["point"]
    assert point.startswith("Return on average assets declined from 2% in FY24 to 1.7% in FY26")
    p = _thesis_with(monkeypatch, point, ["calc.roa.Mar 2026"])
    assert p["refs"] == ["calc.roa.Mar 2026", "calc.roa.Mar 2024"]          # not FY23's 1.98% or FY25's 1.74%
    assert [e["value"] for e in p["evidence"]] == [1.7, 2.0]


@pytest.mark.parametrize("point", [
    "Return on average assets fell to 1.7% in FY26, from about 2% earlier.",       # value without its period
    "Return on average assets fell to 1.7% in FY26, below FY24.",                   # period without its value
    "Return on average assets fell to 1.7% in FY26 from 2.1% in FY24.",             # a value the FY24 fact does not have
])
def test_quoted_figure_is_attached_only_with_both_its_value_and_its_period(monkeypatch, point):
    assert _thesis_with(monkeypatch, point, ["calc.roa.Mar 2026"])["refs"] == ["calc.roa.Mar 2026"]


def test_hdfcbank_and_dixon_prose_still_raise_no_narrative_flags():
    for sym in ("DIXON", "HDFCBANK"):
        m = FIX[sym]
        assert narrative.thesis_issues(m["thesis"], {"rows": m["ledger_rows"]}, periods.from_calendar(m["latest_quarter"])) == {}


# ---------- HDFCBANK production memo 2026-11-10 07:34 (built on 3408129) ----------
# bull 1 pairs the exchange filing's revenue growth (9.1%, Q2 FY27) with the standardised statements' (2.4%, Dec 2025),
# whose own Q2 FY27 figure is 9.4%. bear 2 says the ROA promise is "failing", but the ledger marks it at_risk.

def _yoy(fid, value, period, label="Revenue growth YoY"):
    return {"id": fid, "label": label, "value": value, "unit": "%", "period": period}


S3_HD = {"type": "signal", "tone": "good", "text": "Revenue growth accelerating: 2.4% YoY (Dec 2025) → 9.4% (Sep 2026).",
         "facts": ["calc.Q.revenue_yoy.Dec 2025", "calc.Q.revenue_yoy.Sep 2026"],
         "figures": [_yoy("calc.Q.revenue_yoy.Dec 2025", 2.4, "Dec 2025"), _yoy("calc.Q.revenue_yoy.Sep 2026", 9.4, "Sep 2026")]}
X_REV_HD = {"type": "fact", **_yoy("X.revenue_yoy.Q2 FY27", 9.1, "Q2 FY27", "Revenue growth YoY (exchange filing)")}
BULL1_HD = {"point": "Revenue growth accelerated to 9.1% YoY in Q2 FY27, up from 2.4% in Dec 2025.",
            "refs": ["S3", "X.revenue_yoy.Q2 FY27"], "evidence": [S3_HD, X_REV_HD]}
ROA_ROW = {"subject": "Return on Assets", "verdict": "at_risk", "downgraded_from": "missed", "guidance_ids": ["G1.5", "G3.2"],
           "evidence": [{"id": "G1.5", "call": "Q2 FY26", "horizon": "medium to long term"},
                        {"id": "G3.2", "call": "Q4 FY26", "horizon": "next 1-3 years"}], "facts": [], "delivered": "", "why": ""}
CAPEX_MISSED = {"subject": "FY26 capex", "verdict": "missed", "guidance_ids": ["G9.1"],
                "evidence": [{"id": "G9.1", "call": "Q2 FY26", "horizon": "FY26"}], "facts": [], "delivered": "", "why": ""}
LED_HD = {"L1": ROA_ROW, "L2": CAPEX_MISSED}
ROA = [{"type": "fact", "id": f"calc.roa.Mar {y}", "label": "Return on average assets", "value": v, "unit": "%", "period": f"FY{y % 100}"}
       for y, v in ((2026, 1.7), (2024, 2.0))]
BEAR2_HD = {"point": "ROA declined to 1.7% in FY26 from 2.0% in FY24, failing stability targets.",
            "refs": ["L1", "calc.roa.Mar 2026", "calc.roa.Mar 2024"],
            "evidence": [{"type": "ledger", "subject": "Return on Assets", "verdict": "at_risk"}, *ROA]}


def test_hdfcbank_bull1_mixed_revenue_series_is_flagged_without_substituting_a_figure():
    issue = narrative.series_issue(BULL1_HD["point"], BULL1_HD["evidence"])
    assert issue == ("Mixes two revenue growth (YOY) series: 9.1% (Q2 FY27, exchange filing) and 2.4% (Q3 FY26, "
                     "standardised statements). Compare figures from one series — the standardised statements give "
                     "9.4% for Q2 FY27.")
    th = {"bull": [copy.deepcopy(BULL1_HD)], "bear": []}
    assert "Mixes two revenue growth" in narrative.thesis_issues(th, {"rows": []}, LATEST)["bull1"]["issue"]
    assert narrative.trim_unmet_promise_claim(BULL1_HD["point"], BULL1_HD["refs"], BULL1_HD["evidence"], {}, LATEST) is None


@pytest.mark.parametrize("point,evidence", [
    ("Revenue growth accelerated to 9.4% YoY in Sep 2026 from 2.4% in Dec 2025.", [S3_HD, X_REV_HD]),     # one series
    ("Revenue grew 9.1% YoY in Q2 FY27, per the exchange filing.", [S3_HD, X_REV_HD]),                     # one figure
    # HDFCBANK 14:47 bull 1: the trend is one series (2.4% → 9.4%); the filing's 9.1% is the same quarter, side by side
    ("Revenue growth has accelerated from 2.4% YoY in Dec 2025 to 9.4% in Sep 2026, alongside a 9.1% total income "
     "growth in Q2 FY27.", [S3_HD, X_REV_HD]),
    ("Revenue growth accelerated to 28.4% YoY in Q2 FY27 from 3.7% in Dec 2025.",                          # TATATECH:
     [{**S3_HD, "figures": [_yoy("calc.Q.revenue_yoy.Dec 2025", 3.7, "Dec 2025"), _yoy("calc.Q.revenue_yoy.Sep 2026", 28.4, "Sep 2026")]},
      {**X_REV_HD, "value": 28.4}]),                                                                        # series agree
    ("Net interest income grew 10.5% YoY, outpacing total income growth of 9.1%.",                         # two metrics
     [{"type": "fact", **_yoy("X.nii_yoy.Q2 FY27", 10.5, "Q2 FY27", "NII growth YoY (exchange filing)")}, X_REV_HD]),
    ("PAT fell 5.5% QoQ and grew 3.6% YoY in Q2 FY27.",                                                     # QoQ vs YoY
     [_fact("calc.Q.pat_qoq.Sep 2026", -5.5, "Sep 2026"), _fact("X.pat_yoy.Q2 FY27", 3.6, "Q2 FY27")]),
])
def test_consistent_comparisons_are_not_flagged(point, evidence):
    assert narrative.series_issue(point, evidence) is None


def test_exact_margin_mixed_with_a_filing_margin_is_flagged():
    ev = [_fact("calc.Q.ebitda_margin.Mar 2026", 16.03, "Mar 2026"), _fact("X.EBITDA margin.Q2 FY26", 15.7, "Q2 FY26")]
    assert narrative.series_issue("EBITDA margin rose to 16.03% from 15.7%.", ev).startswith("Mixes two ebitda margin series")


def test_thesis_gives_a_signal_the_figures_it_is_computed_from(monkeypatch):
    facts = {f["id"]: f for f in S3_HD["figures"]} | {"X.revenue_yoy.Q2 FY27": {k: v for k, v in X_REV_HD.items() if k != "type"}}
    fin = {"signals": [{"tone": "neutral", "text": "x", "facts": []}, {"tone": "neutral", "text": "y", "facts": []},
                       {k: S3_HD[k] for k in ("tone", "text", "facts")}], "facts": facts,
           "trajectory": {"quarterly": [{"period": "Jun 2026"}, {"period": "Sep 2026"}]}}
    monkeypatch.setattr(thesis, "chat_json", lambda *a, **k: {"bull": [{"point": BULL1_HD["point"], "refs": BULL1_HD["refs"]}],
                                                               "bear": [], "watch": None})
    p = thesis.build(fin, [], {"rows": []})["bull"][0]
    assert [f["value"] for f in p["evidence"][0]["figures"]] == [2.4, 9.4]
    assert narrative.series_issue(p["point"], p["evidence"]).startswith("Mixes two revenue growth")


def test_hdfcbank_bear2_failure_claim_on_an_at_risk_promise_is_flagged():
    assert narrative.promise_issue(BEAR2_HD["point"], BEAR2_HD["refs"], BEAR2_HD["evidence"], LED_HD, LATEST) == \
        "Says a promise failed or was missed, but the ledger marks 'Return on Assets' at risk."


def test_hdfcbank_bear2_repair_keeps_the_roa_comparison_and_drops_the_failure_claim():
    point, refs, evidence = narrative.trim_unmet_promise_claim(BEAR2_HD["point"], BEAR2_HD["refs"], BEAR2_HD["evidence"], LED_HD, LATEST)
    assert point == "ROA declined to 1.7% in FY26 from 2.0% in FY24."
    assert refs == ["calc.roa.Mar 2026", "calc.roa.Mar 2024"] and [e["value"] for e in evidence] == [1.7, 2.0]
    th = {"bull": [], "bear": [{"point": point, "refs": refs, "evidence": evidence}]}
    assert narrative.thesis_issues(th, {"rows": list(LED_HD.values())}, LATEST) == {}


@pytest.mark.parametrize("point", [
    "Return on Assets is failing its stability targets.",
    "ROA fell short of the stability target.",
    "ROA guidance was not achieved.",
    "The ROA target remains unmet at 1.7%.",
    "ROA missed management's 1-3 year target.",
])
def test_failure_wording_variants_on_an_at_risk_promise_are_flagged(point):
    assert "failed or was missed" in narrative.promise_issue(point, ["L1"], [], LED_HD, LATEST)


@pytest.mark.parametrize("point,refs", [
    ("FY26 capex of ₹1,058 Cr missed the capex target.", ["L2"]),                    # genuinely missed
    ("Capex missed the target while ROA declined.", ["L1", "L2"]),                    # the claim is about the missed one
    ("ROA has not missed its targets yet, at 1.7%.", ["L1"]),                         # negated
    ("Many targets remain unverifiable due to missing data.", ["L1"]),               # "missing data" is no failure claim
    ("ROA declined to 1.7% in FY26 from 2.0% in FY24.", ["L1"]),                      # the historical comparison
])
def test_legitimate_failure_wording_and_comparisons_pass(point, refs):
    assert narrative.promise_issue(point, refs, [], LED_HD, LATEST) is None


def test_failure_claim_about_an_unstarted_period_is_flagged():
    g = {"type": "guidance", "id": "G9.9", "call": "Q2 FY27", "horizon": "H2 FY27", "statement": "Margins will improve in H2."}
    assert "H2 FY27, which hasn't started" in narrative.promise_issue("Margins are failing the H2 target.", ["G9.9"], [g], {}, LATEST)


def _run_hd(monkeypatch, thesis_points):
    def thesis_now():
        return {"bull": [copy.deepcopy(PLAIN), copy.deepcopy(thesis_points["bull"]), copy.deepcopy(PLAIN)],
                "bear": [copy.deepcopy(PLAIN), copy.deepcopy(thesis_points["bear"]), copy.deepcopy(PLAIN)], "watch": None}
    monkeypatch.setattr(research.verify, "check", _all_supported)
    monkeypatch.setattr(research.thesis, "build", lambda fin, calls, led, feedback=None: thesis_now())  # model repeats it
    rows = [copy.deepcopy(ROA_ROW), copy.deepcopy(CAPEX_MISSED)]
    secs = {"thesis": thesis_now(), "ledger": {"rows": rows}}
    research._verify(FIN, [], secs)
    return secs


def test_pipeline_hdfcbank_bear2_and_bull1_are_both_repaired(monkeypatch):
    # PR #5 left bull 1 disputed; the series repair now moves its trend onto the one series that covers it.
    secs = _run_hd(monkeypatch, {"bull": BULL1_HD, "bear": BEAR2_HD})
    b1, b2, v = secs["thesis"]["bull"][1], secs["thesis"]["bear"][1], secs["verification"]
    assert b2["point"] == "ROA declined to 1.7% in FY26 from 2.0% in FY24." and b2["verified"] is True
    assert b2["trimmed_from"] == BEAR2_HD["point"]
    assert b1["point"] == "Revenue growth accelerated to 9.4% YoY in Q2 FY27, up from 2.4% in Dec 2025."
    assert b1["verified"] is True and b1["trimmed_from"] == BULL1_HD["point"] and b1["refs"] == ["S3"]
    assert v["trimmed"] == ["bull2", "bear2"] and v["flagged"] == 0


# ---------- HDFCBANK production memo 2026-11-10 07:51 (built on d253e69) ----------
# bull 1 still mixed the filing's 9.1% with the statements' 2.4% after its rewrite; bear 2 labelled the FY26 ROA
# (calc.roa.Mar 2026 = 1.7%) "Sep 2026". Both are now repaired deterministically from cited figures, then re-verified.

REV_QOQ_HD = {"type": "fact", "id": "calc.Q.revenue_qoq.Sep 2026", "label": "Revenue growth QoQ (sequential)", "value": 5.0,
              "unit": "%", "period": "Sep 2026"}
BULL1_0751 = {"point": "Revenue growth accelerating, YoY 9.1% and QoQ 5% in Q2 FY27, up from 2.4% YoY earlier.",
              "refs": ["S3", "X.revenue_yoy.Q2 FY27", "calc.Q.revenue_qoq.Sep 2026"], "evidence": [S3_HD, X_REV_HD, REV_QOQ_HD]}
ROA_FY = [{"type": "fact", "id": "calc.roa.Mar 2026", "label": "Return on average assets", "value": 1.7, "unit": "%", "period": "FY26"},
          {"type": "fact", "id": "calc.roa.Mar 2024", "label": "Return on average assets", "value": 2.0, "unit": "%", "period": "FY24"}]
BEAR2_0751 = {"point": "ROA declined to 1.7% in Sep 2026 after peaking at 2% in FY24, with ROA promise at risk.",
              "refs": ["calc.roa.Mar 2026", "calc.roa.Mar 2024", "L1"],
              "evidence": [*ROA_FY, {"type": "ledger", "subject": "Return on Assets", "verdict": "at_risk"}]}


def test_0751_bull1_is_moved_onto_the_one_series_that_covers_it():
    point, refs, evidence = narrative.repair_point(BULL1_0751["point"], BULL1_0751["refs"], BULL1_0751["evidence"], LED_HD, LATEST)
    assert point == "Revenue growth accelerating, YoY 9.4% and QoQ 5% in Q2 FY27, up from 2.4% YoY earlier."
    assert refs == ["S3", "calc.Q.revenue_qoq.Sep 2026"]                     # the filing's 9.1% is no longer cited
    th = {"bull": [{"point": point, "refs": refs, "evidence": evidence}], "bear": []}
    assert narrative.thesis_issues(th, {"rows": list(LED_HD.values())}, LATEST) == {}


def test_0751_bear2_mislabelled_fy26_roa_is_flagged_and_named_by_its_own_period():
    assert narrative.period_label_issue(BEAR2_0751["point"], BEAR2_0751["evidence"]) == \
        "Labels the FY26 figure 1.7% (calc.roa.Mar 2026) as Sep 2026; use its own period, FY26."
    point, refs, _ = narrative.repair_point(BEAR2_0751["point"], BEAR2_0751["refs"], BEAR2_0751["evidence"], LED_HD, LATEST)
    assert point == "ROA declined to 1.7% in FY26 after peaking at 2% in FY24, with ROA promise at risk."
    assert refs == BEAR2_0751["refs"]
    assert narrative.promise_issue(point, refs, BEAR2_0751["evidence"], LED_HD, LATEST) is None   # "at risk" is right


@pytest.mark.parametrize("point,evidence", [
    ("Revenue growth accelerated to 9.4% YoY in Q2 FY27 from 2.4% in Q3 FY26.", [S3_HD]),         # the intended wording
    ("ROA declined to 1.7% in FY26 from 2.0% in FY24, with the ROA promise still at risk.", ROA_FY),
    ("ROA was 1.7% in Mar 2026.", ROA_FY),                                    # an FY figure by its year-end quarter
    ("Revenue growth was 2.4% YoY (Dec 2025) and 9.4% (Sep 2026).", [S3_HD]),
    ("Q2 FY27 EBITDA margin of 16.1% exceeded Q2 FY26's 15.7%.",              # a label after a verb is not the figure's
     [_fact("X.EBITDA margin.Q2 FY27", 16.1, "Q2 FY27"), _fact("X.EBITDA margin.Q2 FY26", 15.7, "Q2 FY26")]),
    ("FY27 YTD revenue growth reached 31% in FY27.", [{"type": "fact", "id": "calc.ytd_revenue_growth", "label": "Revenue growth",
                                                        "value": 31.0, "unit": "%", "period": "FY27 YTD (2Q)"}]),
    ("Margin rose to 16.07% in Q2 FY27 from 16.04% in Q1 FY27.", SEQ_PAIR),
])
def test_correctly_labelled_figures_pass(point, evidence):
    assert narrative.period_label_issue(point, evidence) is None
    assert narrative.series_issue(point, evidence) is None


@pytest.mark.parametrize("point,evidence,label", [
    ("ROA fell to 1.7% in Q2 FY27.", ROA_FY, "Q2 FY27"),                       # an annual figure given a quarter
    ("Revenue growth hit 9.4% in Q3 FY26.", [S3_HD], "Q3 FY26"),               # the wrong quarter
    ("ROA was 2.0% in FY25.", ROA_FY, "FY25"),                                 # the wrong year
])
def test_mislabelled_figures_are_flagged(point, evidence, label):
    assert f"as {label}" in narrative.period_label_issue(point, evidence)


def test_ambiguous_mislabel_is_flagged_but_not_repaired():
    twin = [*ROA_FY, {"type": "fact", "id": "calc.roa.Mar 2019", "label": "Return on average assets", "value": 1.7, "unit": "%", "period": "FY19"}]
    point = "ROA was 1.7% in Sep 2026."          # 1.7% is both FY26 and FY19: which period is meant is not knowable
    assert narrative.period_label_issue(point, twin)
    assert narrative.repair_point(point, [f["id"] for f in twin], twin, {}, LATEST) is None
    assert narrative._relabel_periods(point, twin) == point


def test_series_repair_skips_when_no_single_series_covers_the_trend():
    s3_partial = {**S3_HD, "figures": [S3_HD["figures"][0]]}               # the statements lack a Q2 FY27 figure
    point = BULL1_HD["point"]
    assert narrative.series_issue(point, [s3_partial, X_REV_HD])
    assert narrative.repair_point(point, ["S3", "X.revenue_yoy.Q2 FY27"], [s3_partial, X_REV_HD], {}, LATEST) is None


def test_repair_leaves_a_genuinely_missed_promise_and_sound_points_alone():
    assert narrative.repair_point("FY26 capex of ₹1,058 Cr missed the capex target.", ["L2"], [], LED_HD, LATEST) is None
    assert narrative.repair_point("ROA declined to 1.7% in FY26 from 2.0% in FY24.", ["calc.roa.Mar 2026", "calc.roa.Mar 2024"],
                                  ROA_FY, LED_HD, LATEST) is None


def test_pipeline_repairs_both_0751_points_and_verifies_them(monkeypatch):
    secs = _run_hd(monkeypatch, {"bull": BULL1_0751, "bear": BEAR2_0751})
    b1, b2, v = secs["thesis"]["bull"][1], secs["thesis"]["bear"][1], secs["verification"]
    assert b1["point"] == "Revenue growth accelerating, YoY 9.4% and QoQ 5% in Q2 FY27, up from 2.4% YoY earlier."
    assert b2["point"] == "ROA declined to 1.7% in FY26 after peaking at 2% in FY24, with ROA promise at risk."
    assert b1["verified"] is True and b2["verified"] is True
    assert (v["trimmed"], v["trim_recheck"], v["flagged"]) == (["bull2", "bear2"], "done", 0)


def test_pipeline_repaired_0751_points_are_unchecked_when_the_verifier_is_down(monkeypatch):
    calls = []

    def check(claims):
        calls.append(1)
        return {c["id"]: {"supported": True, "issue": ""} for c in claims} if len(calls) < 3 else {}

    monkeypatch.setattr(research.verify, "check", check)
    monkeypatch.setattr(research.thesis, "build", lambda fin, calls_, led, feedback=None: {
        "bull": [copy.deepcopy(PLAIN), copy.deepcopy(BULL1_0751), copy.deepcopy(PLAIN)],
        "bear": [copy.deepcopy(PLAIN), copy.deepcopy(BEAR2_0751), copy.deepcopy(PLAIN)], "watch": None})
    secs = {"thesis": research.thesis.build(None, None, None), "ledger": {"rows": [copy.deepcopy(ROA_ROW), copy.deepcopy(CAPEX_MISSED)]}}
    research._verify(FIN, [], secs)
    assert secs["thesis"]["bull"][1]["verified"] is None and secs["thesis"]["bear"][1]["verified"] is None
    assert secs["verification"]["status"] == "rewrite_unverified"


def test_generator_and_verifier_prompts_state_the_series_and_period_rules():
    assert "a trend or comparison uses\nfigures from one series only" in thesis.SYSTEM
    assert "an FY26 figure\nis \"FY26\", not a month or a quarter" in thesis.SYSTEM
    assert "labelled with a period other than its own" in verify.SYSTEM
    assert verify._evidence_text({"type": "signal", "text": "x"}) == "Computed signal (standardised statements): x"


# ---------- one metric cited both as a level and as a growth rate ----------
# Production rebuild of HDFCBANK (10 Nov 2026, 18:55 UTC) failed with "TypeError: '<' not supported between instances of
# 'NoneType' and 'str'": X.PAT.Q2 FY27 is keyed ("pat", None) and X.pat_yoy.Q2 FY27 ("pat", "yoy"), and the series check
# sorted those keys. A point may cite both; the check must neither crash nor flag a single series.

def _level(fid, value, period, label):
    return {"type": "fact", "id": fid, "label": label, "value": value, "unit": "₹ Cr", "period": period}


PAT_LEVEL = _level("X.PAT.Q2 FY27", 18641.3, "Q2 FY27", "PAT (exchange filing)")
REV_LEVEL = _level("X.Revenue.Q2 FY27", 87460.0, "Q2 FY27", "Total income (exchange filing)")
PAT_MARGINS = [_fact("X.PAT margin.Q2 FY27", 16.0, "Q2 FY27", "PAT margin (exchange filing)"),
               _fact("X.PAT margin.Q2 FY26", 16.5, "Q2 FY26", "PAT margin (exchange filing)")]


@pytest.mark.parametrize("point,growth", [
    ("PAT rose 5.6% YoY to ₹18,641 Cr in Q2 FY27, while PAT margin slipped to 16.0% from 16.5%.",
     _fact("X.pat_yoy.Q2 FY27", 5.6, "Q2 FY27", "PAT growth YoY (exchange filing)")),
    ("PAT rose 5.7% QoQ to ₹18,641 Cr in Q2 FY27, while PAT margin slipped to 16.0% from 16.5%.",
     _fact("calc.Q.pat_qoq.Sep 2026", 5.7, "Sep 2026", "PAT growth QoQ (sequential)")),
], ids=["level+yoy", "level+qoq"])
def test_a_metric_cited_as_a_level_and_a_growth_rate_does_not_crash_the_checks(point, growth):
    evidence = [PAT_LEVEL, growth, *PAT_MARGINS]
    refs = [e["id"] for e in evidence]
    assert narrative._metric(PAT_LEVEL["id"]) == ("pat", None) and narrative._metric(growth["id"])[0] == "pat"
    assert narrative.series_issue(point, evidence) is None
    assert narrative._use_one_series(point, refs, evidence) is None
    assert narrative.repair_point(point, refs, evidence, {}, LATEST) is None          # nothing to repair
    th = {"bull": [{"point": point, "refs": refs, "evidence": evidence, "grounded": True}], "bear": []}
    assert narrative.thesis_issues(th, {"rows": []}, LATEST) == {}


def test_a_level_figure_beside_a_cross_series_trend_still_flags_and_repairs_it():
    """Negative control: adding the same metric's level figure must not hide or change a genuine cross-series trend."""
    evidence = [*BULL1_0751["evidence"], REV_LEVEL]
    refs = [*BULL1_0751["refs"], REV_LEVEL["id"]]
    assert narrative._metric(REV_LEVEL["id"]) == ("revenue", None)
    assert narrative.series_issue(BULL1_0751["point"], evidence) == \
        narrative.series_issue(BULL1_0751["point"], BULL1_0751["evidence"])
    assert narrative.series_issue(BULL1_0751["point"], evidence).startswith("Mixes two revenue growth (YOY) series")
    point, new_refs, _ = narrative.repair_point(BULL1_0751["point"], refs, evidence, LED_HD, LATEST)
    assert point == "Revenue growth accelerating, YoY 9.4% and QoQ 5% in Q2 FY27, up from 2.4% YoY earlier."
    assert "X.revenue_yoy.Q2 FY27" not in new_refs and REV_LEVEL["id"] in new_refs


# ---------- every quoted number is a cited figure ----------
# HDFCBANK 10 Nov 2026 19:10 bull 2: "pre-provision margin stayed above 25%" cites 25.4% and 26.1%. True, but 25 is not a
# reported figure: the thesis builder marked it grounded=False (shown as "⚠ unverified"), yet nothing sent it to the
# rewrite or the repair, so the second-model check passed it as verified.

PPM = [_fact("X.Pre-provision margin.Q2 FY27", 25.4, "Q2 FY27", "Pre-provision margin (exchange filing)"),
       _fact("X.Pre-provision margin.Q2 FY26", 26.1, "Q2 FY26", "Pre-provision margin (exchange filing)")]
PAT_GROWTH = [_fact("calc.Q.pat_qoq.Sep 2026", 5.7, "Sep 2026", "PAT growth QoQ (sequential)"),
              _fact("X.pat_yoy.Q2 FY27", 5.6, "Q2 FY27", "PAT growth YoY (exchange filing)")]
BULL2_1910 = {"point": "PAT rose 5.7% QoQ and 5.6% YoY, while pre‑provision margin stayed above 25%.",
              "refs": [f["id"] for f in PAT_GROWTH + PPM], "evidence": PAT_GROWTH + PPM, "grounded": False}


def test_1910_bull2_ungrounded_threshold_is_flagged_with_the_figure_it_invented():
    th = {"bull": [copy.deepcopy(BULL2_1910)], "bear": []}
    assert narrative.thesis_issues(th, {"rows": []}, LATEST) == {"bull1": {"supported": False, "issue":
        "Quotes 25, which is not among its cited figures (5.6, 5.7, 25.4, 26.1); quote a cited figure or drop that claim."}}


def test_1910_bull2_repair_drops_only_the_uncited_clause_and_the_facts_it_alone_used():
    point, refs, evidence = narrative.repair_point(BULL2_1910["point"], BULL2_1910["refs"], BULL2_1910["evidence"], {},
                                                   LATEST, grounded=False)
    assert point == "PAT rose 5.7% QoQ and 5.6% YoY."
    assert refs == ["calc.Q.pat_qoq.Sep 2026", "X.pat_yoy.Q2 FY27"] and [e["id"] for e in evidence] == refs
    assert narrative.cited_grounded(point, evidence)
    th = {"bull": [{"point": point, "refs": refs, "evidence": evidence, "grounded": True}], "bear": []}
    assert narrative.thesis_issues(th, {"rows": []}, LATEST) == {}


def test_grounded_and_legacy_points_are_not_flagged_or_trimmed():
    for p in ({**BULL2_1910, "grounded": True}, {k: v for k, v in BULL2_1910.items() if k != "grounded"}):
        assert narrative.grounding_issue(p) is None
    # the pipeline's own grounded flag decides; a point it judged grounded is never cut for an uncited number
    assert narrative.repair_point(BULL2_1910["point"], BULL2_1910["refs"], BULL2_1910["evidence"], {}, LATEST) is None


@pytest.mark.parametrize("point", [
    "Pre‑provision margin stayed above 25%, with PAT up 5.6% YoY.",       # the uncited number is the main claim
    "PAT grew strongly, while pre‑provision margin stayed above 25%.",    # nothing figure-based would remain
    "PAT rose 5.7% QoQ to ₹19,000 Cr, while margin stayed above 25%.",    # the main clause has its own uncited number
])
def test_ungrounded_repair_never_rewrites_the_main_claim(point):
    assert narrative.trim_ungrounded_clause(point, BULL2_1910["refs"], BULL2_1910["evidence"]) is None
    assert narrative.repair_point(point, BULL2_1910["refs"], BULL2_1910["evidence"], {}, LATEST, grounded=False) is None


def test_ungrounded_repair_keeps_cited_clauses_after_the_dropped_one():
    point = "PAT rose 5.6% YoY, pre‑provision margin stayed above 25%, and pre‑provision margin was 25.4% in Q2 FY27."
    kept, refs, _ = narrative.trim_ungrounded_clause(point, BULL2_1910["refs"], BULL2_1910["evidence"])
    assert kept == "PAT rose 5.6% YoY, and pre‑provision margin was 25.4% in Q2 FY27."
    assert refs == ["X.pat_yoy.Q2 FY27", "X.Pre-provision margin.Q2 FY27"]


def test_pipeline_rewrites_then_repairs_the_1910_bull2_and_marks_it_grounded(monkeypatch):
    secs = _run_hd(monkeypatch, {"bull": BULL2_1910, "bear": PLAIN})     # the rewrite repeats the same wording
    b2, v = secs["thesis"]["bull"][1], secs["verification"]
    assert v["rewrote_thesis"] is True and v["trimmed"] == ["bull2"] and v["trim_recheck"] == "done"
    assert b2["point"] == "PAT rose 5.7% QoQ and 5.6% YoY." and b2["trimmed_from"] == BULL2_1910["point"]
    assert b2["grounded"] is True and b2["verified"] is True and v["flagged"] == 0
    assert any("Quotes 25" in x for x in v["initially_unsupported"])
