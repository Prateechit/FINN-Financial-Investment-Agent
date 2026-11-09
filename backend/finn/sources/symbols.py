"""Company name / symbol → NSE ticker. Pure functions over the NSE equity list (no network, no database)."""
import re

_SUFFIX = re.compile(r"\b(LIMITED|LTD|PRIVATE|PVT|CORPORATION|CORP|COMPANY|CO|INC)\b\.?")


def normalize_name(s: str) -> str:
    """'Tata Technologies Ltd.' → 'TATA TECHNOLOGIES' (case, punctuation and corporate suffixes ignored)."""
    s = s.upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = _SUFFIX.sub(" ", s)
    s = re.sub(r"^THE ", "", re.sub(r"\s+", " ", s).strip())
    return s.strip()


def search_rows(q: str, rows: list[dict], limit: int = 12) -> list[dict]:
    """Symbol-prefix matches first, then symbol/name substring matches — the ranking /api/search has always used."""
    q = q.strip().upper()
    starts = [r for r in rows if r["symbol"].startswith(q)]
    contains = [r for r in rows if r not in starts and (q in r["symbol"] or q in r["name"].upper())]
    return (starts + contains)[:limit]


def resolve(raw: str, rows: list[dict]) -> dict:
    """{"symbol": str | None, "matched_by": "symbol" | "name" | "search" | None, "suggestions": [rows]}.

    Order: exact NSE symbol → exact company name (normalised) → the only search match. Anything else is unresolved,
    with up to five suggestions, so a free-text name can never be sent to the data providers as if it were a ticker.
    """
    q = (raw or "").strip().upper()
    if not q:
        return {"symbol": None, "matched_by": None, "suggestions": []}
    for r in rows:
        if r["symbol"] == q:
            return {"symbol": r["symbol"], "matched_by": "symbol", "suggestions": []}
    target = normalize_name(q)
    by_name = [r for r in rows if target and normalize_name(r["name"]) == target]
    if len(by_name) == 1:
        return {"symbol": by_name[0]["symbol"], "matched_by": "name", "suggestions": []}
    hits = search_rows(q, rows)
    if len(hits) == 1:
        return {"symbol": hits[0]["symbol"], "matched_by": "search", "suggestions": []}
    return {"symbol": None, "matched_by": None, "suggestions": hits[:5]}


TICKER = re.compile(r"[A-Z0-9][A-Z0-9&\-]{0,19}")  # shape of an NSE symbol (e.g. M&M, BAJAJ-AUTO)
