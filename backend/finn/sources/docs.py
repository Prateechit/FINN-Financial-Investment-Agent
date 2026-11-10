"""Primary-document fetch + page-level text, cached by URL (text survives in the DB, bytes on local disk)."""
import hashlib
import re

import pymupdf
import requests

from ..config import CACHE_DIR, UA
from ..db import kv_get, kv_set


def _headers(url: str) -> dict:
    h = {"User-Agent": UA}
    if "bseindia.com" in url:
        h["Referer"] = "https://www.bseindia.com/"
    return h


def fetch_pdf(url: str) -> bytes:
    path = CACHE_DIR / ("pdf_" + hashlib.sha1(url.encode()).hexdigest() + ".pdf")
    if path.exists():
        return path.read_bytes()
    if "nseindia.com" in url:
        from .nse import get_bytes
        data = get_bytes(url)
    else:
        r = requests.get(url, headers=_headers(url), timeout=90)
        r.raise_for_status()
        data = r.content
    if not data.startswith(b"%PDF"):
        raise ValueError(f"not a PDF: {url}")
    path.write_bytes(data)
    return data


def pages(url: str, max_pages: int | None = None) -> dict:
    """{"url","sha","pages":[text,...]} — page i is 1-indexed as pages[i-1]."""
    key = f"pdftext:{hashlib.sha1(url.encode()).hexdigest()}"
    if (hit := kv_get(key)) is not None and (max_pages is None or len(hit["pages"]) >= min(max_pages, hit["n"])):
        if max_pages:
            hit = {**hit, "pages": hit["pages"][:max_pages]}
        return hit
    data = fetch_pdf(url)
    doc = pymupdf.open(stream=data, filetype="pdf")
    n = doc.page_count
    limit = n if max_pages is None else min(n, max_pages)
    texts = [_clean(doc[i].get_text()) for i in range(limit)]
    out = {"url": url, "sha": hashlib.sha256(data).hexdigest()[:16], "n": n, "pages": texts}
    kv_set(key, out)
    return out


def _clean(t: str) -> str:
    t = t.replace(" ", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def norm(s: str) -> str:
    """Normalisation used for verbatim-quote verification."""
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9%.]+", " ", s).strip()


_PAGE_NO = re.compile(r"^page\s+\d{1,4}(?:\s+of\s+\d{1,4})?$", re.I)   # "Page 3 of 16"; a bare number may be text


def _furniture(pages: list[str]) -> set[str]:
    """Running header / footer lines: the same line on at least half the pages (and at least 3) — the company name,
    the call date, "Classification - Internal". Speaker labels ("Moderator:") repeat as well but are transcript
    text, so a line ending in ":" never counts."""
    seen: dict[str, int] = {}
    for p in pages:
        for line in {x.strip() for x in p.splitlines() if x.strip()}:
            seen[line] = seen.get(line, 0) + 1
    need = max(3, len(pages) // 2)
    return {line for line, n in seen.items() if n >= need and not line.endswith(":")}


def _trim_edge(text: str, furniture: set[str], top: bool) -> str:
    """Drop the run of header / footer / page-number lines at one edge of a page; the rest is untouched."""
    lines = text.splitlines()
    idx = range(len(lines)) if top else range(len(lines) - 1, -1, -1)
    cut = 0
    for i in idx:
        line = lines[i].strip()
        if line and line not in furniture and not _PAGE_NO.match(line):
            break
        cut += 1
    return "\n".join(lines[cut:] if top else lines[:len(lines) - cut])


def window(doc: dict, i: int, furniture: set[str] | None = None) -> str:
    """The text a quote starting on page i (0-indexed) may cover: page i, then page i+1 — joined without the running
    header / footer at the break ("…the documentation | HDFC Bank Limited / July 18, 2026 / Page 3 of 16 | and
    approvals…"), which no spoken sentence contains. Only the lines at the break are dropped."""
    pages = doc["pages"]
    if i + 1 >= len(pages):
        return pages[i]
    furniture = _furniture(pages) if furniture is None else furniture
    return _trim_edge(pages[i], furniture, top=False) + "\n" + _trim_edge(pages[i + 1], furniture, top=True)


def find_quote(doc: dict, quote: str, hint_page: int | None = None) -> int | None:
    """Return the 1-indexed page containing the quote (normalised), or None if it is not in the document."""
    q = norm(quote)
    if len(q) < 12:
        return None
    order = list(range(len(doc["pages"])))
    if hint_page and 1 <= hint_page <= len(order):
        order.sort(key=lambda i: abs(i - (hint_page - 1)))
    furniture = _furniture(doc["pages"])
    # allow a quote to span a page break
    for i in order:
        if q in norm(window(doc, i, furniture)):
            return i + 1
    # tolerate the model trimming the middle with an ellipsis
    parts = [p for p in re.split(r"\s*(?:\.\.\.|…)\s*", quote) if len(norm(p)) >= 12]
    if len(parts) > 1:
        for i in order:
            hay = norm(window(doc, i, furniture))
            if all(norm(p) in hay for p in parts):
                return i + 1
    return None


_SUBJECT = re.compile(r"\b(?:sub(?:ject)?|re)\s*[:.\-–]\s*(.{8,260}?)"
                      r"(?:\n\s*(?:dear|ref|respected|sir|madam|with reference|pursuant|in terms|this is)|\n\s*\n|$)",
                      re.I | re.S)


def subject(doc: dict) -> str | None:
    """The 'Sub:' line Indian filings open with — a free, accurate title."""
    for page in doc["pages"][:2]:
        if m := _SUBJECT.search(page):
            t = re.sub(r"\s+", " ", m.group(1)).strip(" .:-")
            if q := re.search(r"titled\s*[“\"'](.+?)[”\"']", t):
                t = q.group(1)
            t = re.split(r"\s+(?:please find|this information|we wish to|we would like to)\b", t, flags=re.I)[0].strip(" .:-")
            if len(t) >= 8:
                return t[:240]
    return None
