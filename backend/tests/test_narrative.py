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
