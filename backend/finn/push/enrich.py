"""Per-announcement enrichment, chosen by category and materiality.

results            -> deterministic results card (XBRL / screener), no LLM
management_change  -> who/role/change + profile, extracted from the filing itself (SEBI requires a brief profile)
other material     -> one-line "why it matters", number-grounded against the filing text
"""
import datetime as dt
import re

from ..grounding import ungrounded
from ..llm import LLMUnavailable, chat_json
from ..sources import docs
from . import results

_BOILER = re.compile(r"^.*?has (informed|submitted to) the Exchange (regarding|about|that|,)?\s*", re.I)


def clean_text(text: str) -> str:
    t = _BOILER.sub("", text or "").strip(" .:-")
    return (t[:1].upper() + t[1:]) if t else ""


def _expected_qe(ts: dt.datetime) -> dt.date:
    """Quarter a results filing on `ts` most plausibly reports (latest quarter-end ≥ 10 days before)."""
    d = ts.date() - dt.timedelta(days=10)
    m = ((d.month - 1) // 3) * 3  # quarter start month - 1
    if m == 0:
        return dt.date(d.year - 1, 12, 31)
    return results._shift(dt.date(d.year, m, 1), 0)


def enrich_results(a) -> dict:
    card = results.results_card(a.symbol)
    if not card:
        return {"type": "results", "status": "unavailable"}
    exp = _expected_qe(a.ts).isoformat()
    if card["quarter"]["end"] < exp:
        return {"type": "results", "status": "pending", "expected_quarter": results.fy_label(dt.date.fromisoformat(exp)),
                "note": "Structured numbers for this quarter are not yet published on the exchange; will refresh automatically."}
    return {"type": "results", "status": "ok", "card": card}


MGMT_SYSTEM = """You extract management changes from an Indian listed company's exchange filing.
Use ONLY the filing text. Never add outside knowledge. Copy the profile wording from the filing.
Return JSON:
{"changes":[{"person":"full name as written","role":"designation","change":"appointed|resigned|retired|ceased|re-appointed|demise|redesignated",
"effective_date":"as written or null","reason":"as written or null",
"profile":"the brief profile / background text from the filing, verbatim, max 700 chars, or null",
"highlights":["up to 3 short phrases taken from the profile: prior employers, years of experience, qualifications"]}]}
If there is no change of a person, return {"changes":[]}."""


def enrich_management(a) -> dict:
    if not a.pdf_url:
        return {"type": "management_change", "status": "no_document"}
    doc = docs.pages(a.pdf_url, max_pages=6)
    body = "\n\n".join(f"[page {i + 1}]\n{t}" for i, t in enumerate(doc["pages"]))[:14000]
    try:
        out = chat_json("mgmt_profile", "fast", MGMT_SYSTEM, f"Exchange summary: {a.text}\n\nFiling:\n{body}", 1200)
    except LLMUnavailable as e:
        return {"type": "management_change", "status": "llm_unavailable", "detail": str(e)[:200]}
    flat = docs.norm(" ".join(doc["pages"]))
    changes = []
    for c in out.get("changes", [])[:4]:
        name = (c.get("person") or "").strip()
        surname = docs.norm(name.split()[-1]) if name else ""
        if not surname or surname not in flat:  # reject names the filing does not contain
            continue
        prof = c.get("profile")
        page = docs.find_quote(doc, prof[:160]) if prof else None
        c["profile_verified"] = page is not None
        c["page"] = page
        changes.append(c)
    return {"type": "management_change", "status": "ok" if changes else "empty", "changes": changes,
            "source": {"url": a.pdf_url, "pages": doc["n"]}}


ONE_LINER_SYSTEM = """You write the single most decision-relevant line about an exchange filing for a portfolio manager.
Rules: max 22 words; state the concrete fact (what, how much, when) then the implication in a few words;
use only facts and numbers present in the filing text; no hype, no advice; if the filing is routine say so plainly.
Return JSON: {"line": "..."}"""


def enrich_one_liner(a) -> dict:
    evidence = a.text or ""
    if a.pdf_url:
        try:
            evidence += "\n" + "\n".join(docs.pages(a.pdf_url, max_pages=3)["pages"])
        except Exception:  # noqa: BLE001 — a missing PDF should not block the summary
            pass
    try:
        out = chat_json("one_liner", "fast", ONE_LINER_SYSTEM,
                        f"Company: {a.symbol}\nCategory: {a.category}\nFiling text:\n{evidence[:9000]}", 120)
        line = (out.get("line") or "").strip()
    except LLMUnavailable:
        line = ""
    if not line or ungrounded(line, evidence):
        return {"type": "summary", "status": "fallback", "line": clean_text(a.text)[:220]}
    return {"type": "summary", "status": "ok", "line": line}


def enrich(a) -> dict | None:
    if a.category == "results" and a.materiality >= 60:
        return enrich_results(a)
    if a.category == "management_change" and a.materiality >= 45:
        return enrich_management(a)
    if a.materiality >= 45:
        return enrich_one_liner(a)
    return None
