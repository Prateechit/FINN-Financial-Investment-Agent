"""Transcript guidance extraction: verbatim-quote matching across page breaks, and wrong-shaped model output.

HDFCBANK's transcripts repeat a running header on every page ("HDFC Bank Limited / July 18, 2026 / Page 3 of 16 /
Classification - Internal"). find_quote joins a page with the next so a quote may span the break, but the header sat
between the two halves, so a verbatim quote crossing any of the 31 mid-sentence breaks in the five calls could never
match. Its Q4 FY26 call was lost entirely to "'str' object has no attribute 'get'" from a wrong-shaped model answer.
No database, network or model: docs.pages and chat_json are replaced.
"""
import pytest

from finn.pull import transcripts
from finn.sources import docs

HEADER = "HDFC Bank Limited \nJuly 18, 2026 \nPage {n} of 16 \nClassification - Internal"


def _doc(*bodies):
    pages = [HEADER.format(n=i + 1) + "\n" + b for i, b in enumerate(bodies)]
    return {"url": "u", "sha": "s", "n": len(pages), "pages": pages}


DOC = _doc(
    "Sashidhar Jagdishan:\nWe have spent a large part of the month of June in completing the documentation",
    "and approvals necessary from our side. We expect deposit growth to stay ahead of loans over the next year.",
    "Moderator:\nThe next question is from the line of Mr. Rahul Jain from Goldman Sachs.\nRahul Jain:\n"
    "Will margins expand next year?\nSrinivasan Vaidyanathan:\nMargins should improve as deposits reprice",
    "Moderator:\nThank you. We will now take the next question and the trajectory will be upward",
)


# ---------- page breaks ----------

def test_a_verbatim_quote_across_a_page_break_matches_without_the_running_header():
    quote = "completing the documentation and approvals necessary from our side"
    assert docs.find_quote(DOC, quote) == 1


def test_the_header_lines_are_found_from_the_document_and_speaker_labels_are_not_header():
    furniture = docs._furniture(DOC["pages"])
    assert {"HDFC Bank Limited", "July 18, 2026", "Classification - Internal"} <= furniture
    assert "Moderator:" not in furniture


def test_only_the_lines_at_the_break_are_dropped():
    w = docs.window(DOC, 0)
    assert w.startswith("HDFC Bank Limited")                       # page 1's own header is untouched
    assert "the documentation\nand approvals" in w                    # page 2's header is gone at the join
    assert docs.window(DOC, 3) == DOC["pages"][3]                     # the last page has nothing to join


@pytest.mark.parametrize("quote", [
    "completing the paperwork and approvals necessary from our side",   # a word changed
    "the documentation HDFC Bank Limited and approvals",                # not what was said
    "Margins should improve as deposits reprice the trajectory will be upward",   # skips the next speaker's label
])
def test_quotes_that_are_not_verbatim_still_fail(quote):
    assert docs.find_quote(DOC, quote) is None


def test_a_bare_number_at_a_page_edge_is_text_not_a_page_number():
    doc = _doc("Deposits grew by a further\n15", "per cent this quarter and we expect the same next year.", "x", "y")
    assert docs.find_quote(doc, "Deposits grew by a further 15 per cent this quarter") == 1
    assert docs.find_quote(doc, "Deposits grew by a further per cent this quarter") is None


def test_quotes_within_one_page_are_unaffected():
    assert docs.find_quote(DOC, "We expect deposit growth to stay ahead of loans over the next year.", 2) == 2


# ---------- extraction ----------

CALL = {"quarter": "Q1 FY27", "label": "Jul 2026", "transcript": "u"}
GOOD = {"metric": "other", "statement": "We expect deposit growth to stay ahead of loans over the next year.", "page": "2"}


def _extract(monkeypatch, raw):
    monkeypatch.setattr(transcripts.docs, "pages", lambda url: DOC)
    monkeypatch.setattr(transcripts, "chat_json", lambda *a, **k: raw)
    return transcripts.extract(CALL, 4)


def test_wrong_shaped_items_are_skipped_and_recorded_not_fatal(monkeypatch):
    out = _extract(monkeypatch, {
        "guidance": ["deposit growth will improve",                                        # a bare string
                     dict(GOOD),
                     {"statement": "We expect deposits to double over the next year.", "page": 2},   # not in the text
                     {"statement": "We have spent a large part of the month of June in completing", "page": 1}],  # past
        "business": "A private-sector bank.",
        "analyst_focus": ["margins", {"topic": "margins", "quote": "Will margins expand next year?", "page": 3}]})
    assert [g["id"] for g in out["guidance"]] == ["G4.2"] and out["guidance"][0]["page"] == 2
    assert [(r["id"], r["reason"]) for r in out["rejected"]] == [
        ("G4.1", "malformed"), ("G4.3", "not_verbatim"), ("G4.4", "not_forward_looking")]
    assert out["dropped_unverified"] == 3
    assert out["business"] == {"summary": "A private-sector bank.", "segments": []}
    assert [f["quote"] for f in out["analyst_focus"]] == ["Will margins expand next year?"]


@pytest.mark.parametrize("raw", ["Sorry, I cannot read this transcript.", None, 42])
def test_an_answer_that_is_not_an_object_yields_no_guidance_instead_of_crashing(monkeypatch, raw):
    out = _extract(monkeypatch, raw)
    assert out["guidance"] == [] and out["rejected"] == [] and out["business"] is None


def test_a_bare_list_answer_is_read_as_the_guidance_items(monkeypatch):
    out = _extract(monkeypatch, [dict(GOOD)])
    assert [g["statement"] for g in out["guidance"]] == [GOOD["statement"]]


def test_an_analyst_question_is_recorded_as_not_management(monkeypatch):
    out = _extract(monkeypatch, {"guidance": [{"statement": "Will margins expand next year?", "page": 3}]})
    assert out["guidance"] == [] and out["dropped_not_management"] == 1
    assert out["rejected"][0]["reason"] == "not_management" and out["rejected"][0]["speaker"] == "Rahul Jain"


def test_extract_all_keeps_other_calls_when_one_fails(monkeypatch):
    monkeypatch.setattr(transcripts, "pick", lambda c, n: [{**CALL, "quarter": q} for q in ("Q1 FY27", "Q4 FY26")])

    def extract(call, idx):
        if call["quarter"] == "Q4 FY26":
            raise RuntimeError("unreadable")
        return {"call": call["quarter"], "guidance": [GOOD]}

    monkeypatch.setattr(transcripts, "extract", extract)
    out = transcripts.extract_all([], 2)
    assert [c["call"] for c in out] == ["Q1 FY27", "Q4 FY26"] and out[1]["error"] == "unreadable"


# ---------- speaker labels on their own line, or inline ----------
# HDFCBANK's CFO answers on the label's line ("Srinivasan Vaidyanathan: So first is the LCR question. Yes, we would
# like to operate between 110 and 120…"). Only own-line labels were recognised, so seven of his answers were credited
# to the analyst who asked and dropped as "not management" (G5.2, G4.1, G4.6, G3.2, G1.1, G1.2, G1.4, 10 Nov 2026).

CALLTEXT = """
Moderator:
The next question is from the line of Ankit Bihani from JM Financial.
Ankit Bihani:
And the third is on the PSL front. What are we doing to address the LCR?
Srinivasan Vaidyanathan: So first is the LCR question. Yes, we would like to operate between 110 and 120, which we
have told you over the last few years.
Moderator:
The next question is from the line of Mr. Kunal Shah from ICICI Securities.
Kunal Shah: So what range would we want to sustain the LCR at over the next year?
Srinivasan Vaidyanathan:
Kunal, in the past, we have mentioned that our endeavor for LCR is to be between 110% and 120%.
Sashidhar Jagdishan: The answer is: yes, we will keep investing in technology through the next two years.
Sashidhar Jagdishan:
Thank you.
"""
ANALYSTS = frozenset(transcripts._person(n) for n in transcripts._INTRODUCED.findall(CALLTEXT))


@pytest.mark.parametrize("statement,speaker", [
    ("Yes, we would like to operate between 110 and 120, which we have told you", "Srinivasan Vaidyanathan"),  # inline
    ("Kunal, in the past, we have mentioned that our endeavor for LCR", "Srinivasan Vaidyanathan"),            # own line
    ("And the third is on the PSL front. What are we doing", "Ankit Bihani"),                                   # analyst, own line
    ("So what range would we want to sustain the LCR", "Kunal Shah"),                                           # analyst, inline
    ("we will keep investing in technology through the next two years", "Sashidhar Jagdishan"),                # "is: yes" is no label
], ids=["mgmt-inline", "mgmt-own-line", "analyst-own-line", "analyst-inline", "colon-in-sentence"])
def test_speaker_is_found_for_inline_and_own_line_labels(statement, speaker):
    assert transcripts.speaker_at(CALLTEXT, statement, ANALYSTS) == speaker


def test_a_one_off_heading_is_not_taken_for_a_speaker():
    text = "\nMANAGEMENT: MR. SASHIDHAR JAGDISHAN – MANAGING DIRECTOR\nWe will grow deposits faster than loans next year.\n"
    assert transcripts.speaker_at(text, "We will grow deposits faster than loans next year.", frozenset()) is None


def test_a_management_answer_after_an_inline_label_is_kept_not_rejected(monkeypatch):
    doc = {"url": "u", "sha": "s", "n": 1, "pages": [CALLTEXT.strip()]}
    monkeypatch.setattr(transcripts.docs, "pages", lambda url: doc)
    monkeypatch.setattr(transcripts, "chat_json", lambda *a, **k: {"guidance": [
        {"statement": "Yes, we would like to operate between 110 and 120, which we have told you over the last few years.", "page": 1},
        {"statement": "So what range would we want to sustain the LCR at over the next year?", "page": 1}]})
    out = transcripts.extract(CALL, 5)
    assert [(g["id"], g["speaker"]) for g in out["guidance"]] == [("G5.1", "Srinivasan Vaidyanathan")]
    assert [(r["id"], r["reason"], r["speaker"]) for r in out["rejected"]] == [("G5.2", "not_management", "Kunal Shah")]
