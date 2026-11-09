"""How a filing is named wherever it appears (feed, alerts, company page)."""
from .enrich import clean_text


def title(a) -> str:
    e = a.enrichment or {}
    if a.category == "results" and e.get("status") == "ok":
        return f"{e['card']['quarter']['label']} results · {e['card']['headline']}"
    if a.category == "results" and e.get("status") == "pending":
        return f"{e['expected_quarter']} results — numbers awaiting exchange XBRL"
    if a.category == "management_change" and e.get("changes"):
        c = e["changes"][0]
        return f"{c.get('person')} — {c.get('change')} as {c.get('role')}"
    if a.summary:
        return a.summary
    t = a.subject if a.subject and len(clean_text(a.text)) < 80 else (clean_text(a.text) or a.exch_category or "")
    return t if len(t) <= 140 else t[:137].rsplit(" ", 1)[0] + "…"


def short_title(a) -> str:
    """Feed headline: results cards carry their numbers in the body, so keep the headline short."""
    t = title(a)
    return t.split(" · ")[0] if a.category == "results" else t
