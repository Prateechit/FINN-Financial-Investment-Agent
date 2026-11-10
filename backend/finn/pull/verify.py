"""Second-model check: is each claim actually supported by the evidence it cites?

Numeric grounding catches invented figures; it cannot catch a claim whose numbers are real but whose conclusion is
reversed ("revenue growth outpacing profit" when profit grew faster). One batched call to a different, cheap model
judges each claim against only its own cited evidence.
"""
from ..llm import LLMUnavailable, chat_json
from . import periods

SYSTEM = """You audit claims in an equity research memo. For each claim you get ONLY the evidence it cites.
A claim is unsupported if the evidence contradicts it (including reversed comparisons, wrong direction of change,
wrong period, or a figure attached to the wrong metric), or if the claim asserts something the evidence does not
contain. Explanations and implications are claims too ("indicating…", "suggesting…", "due to…", "showing…"): they
are unsupported unless the evidence states them or they follow necessarily from the cited numbers — check the logic
(e.g. revenue growing faster than profit implies margin compression, not recovery; a target cut that the evidence
attributes to a reclassification is not evidence of weaker demand). Paraphrase and plain summarising are fine.
Periods: India's fiscal year runs April–March (Q4 FY26 = Jan–Mar 2026; Q2 FY27 = Jul–Sep 2026). Every figure is
tagged with its fiscal period; a claim about one period that rests on figures from another period is unsupported.
"Sequential" / "quarter-on-quarter" means against the immediately preceding quarter; a comparison with the same
quarter a year earlier (Q2 FY27 vs Q2 FY26) is year-on-year, so calling it sequential is unsupported. A claim that a
promise was met / validated / delivered is unsupported unless its promise-ledger verdict is "delivered".
Quotes are verbatim. A "[topic, as FINN extracted it: …]" tag says what the quoted passage was about in the transcript
(e.g. a bank's "margin" in a passage on Net Interest Margin) — the same context the claim's writer had. Use it to know
what a quote refers to; figures and conclusions must still come from the quote or the reported figures.
Do not use outside knowledge.
Return JSON: {"checks":[{"id":"<claim id>","supported":true|false,"issue":"if false: max 20 words on what is wrong"}]}"""


def _evidence_text(e: dict) -> str:
    t = e.get("type")
    if t == "signal":
        return f"Computed signal: {e.get('text')}"
    if t == "fact" or "value" in e:
        fiscal = periods.tag(e.get("id", ""), e.get("period"))
        when = f"{e.get('period')} = {fiscal}" if fiscal else e.get("period")
        return f"Reported figure: {e.get('label')} = {e.get('value')} {e.get('unit')} ({when})"
    if t == "guidance" or "statement" in e:
        p = periods.promise_period(e) if e.get("call") else None
        about = f" about {p.label}" if p else ""
        status = f" [promise-ledger verdict: {e['ledger_verdict']}]" if e.get("ledger_verdict") else ""
        topic = f" [topic, as FINN extracted it: {e['subject']}]" if e.get("subject") else ""
        return f"Management said ({e.get('call')} call){about}{topic}: \"{e.get('statement')}\"{status}"
    if t == "analyst":
        topic = f" [topic, as FINN extracted it: {e['topic']}]" if e.get("topic") else ""
        return f"An analyst asked{topic}: \"{e.get('quote')}\""
    if t == "ledger":
        return (f"Promise-ledger row: {e.get('subject')} — verdict {e.get('verdict')}. Promised: {e.get('promise')}. "
                f"Assessment: {e.get('why')}")
    return str(e)


def claims_for(thesis: dict, ledger: dict) -> list[dict]:
    out = []
    for side in ("bull", "bear"):
        for i, p in enumerate(thesis.get(side, [])):
            out.append({"id": f"{side}{i + 1}", "claim": p["point"], "evidence": [_evidence_text(e) for e in p["evidence"]]})
    for i, r in enumerate(ledger.get("rows", [])):
        if r["verdict"] == "unverifiable":
            continue
        ev = [_evidence_text({"type": "guidance", **g}) for g in r["evidence"]] + [_evidence_text({"type": "fact", **f}) for f in r["facts"]]
        p = next((x for x in (periods.promise_period(g) for g in reversed(r["evidence"])) if x), None)
        period = f" (promise period: {p.label})" if p else ""
        out.append({"id": f"L{i + 1}", "claim": f"Verdict '{r['verdict']}' on '{r['subject']}'{period}. {r['delivered']} {r['why']}",
                    "evidence": ev})
    return out


def check(claims: list[dict]) -> dict[str, dict]:
    """{claim id: {"supported": bool, "issue": str}} — empty if no verifier model is available."""
    if not claims:
        return {}
    body = "\n\n".join(f"CLAIM {c['id']}: {c['claim']}\nEVIDENCE:\n- " + "\n- ".join(c["evidence"] or ["(none)"]) for c in claims)
    try:
        out = chat_json("verify", "verify", SYSTEM, body, max_tokens=3000)
    except LLMUnavailable:
        return {}
    return {c.get("id"): {"supported": bool(c.get("supported")), "issue": c.get("issue") or ""} for c in out.get("checks", [])}
