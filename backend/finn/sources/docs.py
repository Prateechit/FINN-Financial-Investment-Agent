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


def find_quote(doc: dict, quote: str, hint_page: int | None = None) -> int | None:
    """Return the 1-indexed page containing the quote (normalised), or None if it is not in the document."""
    q = norm(quote)
    if len(q) < 12:
        return None
    order = list(range(len(doc["pages"])))
    if hint_page and 1 <= hint_page <= len(order):
        order.sort(key=lambda i: abs(i - (hint_page - 1)))
    # allow a quote to span a page break
    for i in order:
        hay = norm(doc["pages"][i] + " " + (doc["pages"][i + 1] if i + 1 < len(doc["pages"]) else ""))
        if q in hay:
            return i + 1
    # tolerate the model trimming the middle with an ellipsis
    parts = [p for p in re.split(r"\s*(?:\.\.\.|…)\s*", quote) if len(norm(p)) >= 12]
    if len(parts) > 1:
        for i in order:
            hay = norm(doc["pages"][i] + " " + (doc["pages"][i + 1] if i + 1 < len(doc["pages"]) else ""))
            if all(norm(p) in hay for p in parts):
                return i + 1
    return None
