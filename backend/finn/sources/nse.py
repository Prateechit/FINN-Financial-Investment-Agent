"""NSE India: announcements, integrated-filing results and XBRL parsing.

NSE sits behind Akamai; a GET on the home page sets the cookies the JSON API needs.
"""
import collections
import datetime as dt
import threading
import time

import requests
from lxml import etree

from ..config import UA

BASE = "https://www.nseindia.com"
_lock = threading.Lock()
_session: requests.Session | None = None
_warmed_at = 0.0


def _get_session(force: bool = False) -> requests.Session:
    global _session, _warmed_at
    with _lock:
        if _session is None or force or time.time() - _warmed_at > 600:
            s = requests.Session()
            s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
                              "Referer": BASE + "/"})
            s.get(BASE + "/", timeout=20)
            _session, _warmed_at = s, time.time()
        return _session


def get_json(path: str, params: dict | None = None):
    for attempt in range(3):
        s = _get_session(force=attempt > 0)
        r = s.get(BASE + path, params=params, timeout=40)
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                pass
        time.sleep(1 + attempt)
    raise RuntimeError(f"NSE {path} failed: HTTP {r.status_code}")


def get_bytes(url: str) -> bytes:
    r = _get_session().get(url, timeout=60)
    r.raise_for_status()
    return r.content


def announcements(symbol: str, frm: dt.date, to: dt.date) -> list[dict]:
    rows = get_json("/api/corporate-announcements", {
        "index": "equities", "symbol": symbol,
        "from_date": frm.strftime("%d-%m-%Y"), "to_date": to.strftime("%d-%m-%Y")})
    out = []
    for r in rows or []:
        out.append({
            "id": f"NSE:{r['seq_id']}",
            "symbol": r["symbol"],
            "ts": dt.datetime.strptime(r["sort_date"], "%Y-%m-%d %H:%M:%S"),
            "exch_category": (r.get("desc") or "").strip(),
            "text": (r.get("attchmntText") or "").strip(),
            "pdf_url": r.get("attchmntFile") or None,
        })
    return out


# ---------- results (XBRL) ----------

def _qe(s: str) -> dt.date:
    return dt.datetime.strptime(s.title(), "%d-%b-%Y").date()


def results_filings(symbol: str) -> list[dict]:
    """All quarterly financial-results XBRL filings, newest first: integrated (2025+) and legacy."""
    out = []
    try:
        data = get_json("/api/integrated-filing-results", {"index": "equities", "symbol": symbol}).get("data") or []
        for x in data:
            if "Financ" in (x.get("type") or "") and x.get("xbrl"):
                out.append({"qe": _qe(x["qe_Date"]), "consolidated": x.get("consolidated") == "Consolidated",
                            "xbrl": x["xbrl"], "filed": x.get("broadcast_Date"), "revised": x.get("type_Sub") != "Original"})
    except Exception:
        pass
    try:
        for x in get_json("/api/corporates-financial-results",
                          {"index": "equities", "symbol": symbol, "period": "Quarterly"}) or []:
            if x.get("xbrl") and x["xbrl"].endswith(".xml"):
                out.append({"qe": _qe(x["toDate"]), "consolidated": x.get("consolidated") == "Consolidated",
                            "xbrl": x["xbrl"], "filed": x.get("filingDate"), "revised": False, "bank": x.get("bank") == "B"})
    except Exception:
        pass
    # Keep one filing per (quarter, basis); prefer the most recent revision.
    seen, uniq = set(), []
    for x in sorted(out, key=lambda x: (x["qe"], x["consolidated"], x["revised"]), reverse=True):
        k = (x["qe"], x["consolidated"])
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq


def xbrl_facts(xml: bytes) -> dict[str, dict[tuple, str]]:
    """{concept: {(start, end): value}} for dimensionless contexts only."""
    root = etree.fromstring(xml)
    ctx = {}
    for c in root.iter("{*}context"):
        def g(tag):
            el = c.find(f".//{{*}}{tag}")
            return el.text.strip() if el is not None and el.text else None
        dims = list(c.iter("{*}explicitMember")) + list(c.iter("{*}typedMember"))
        ctx[c.get("id")] = (g("startDate"), g("endDate") or g("instant"), bool(dims))
    facts: dict = collections.defaultdict(dict)
    for el in root:
        if not isinstance(el.tag, str) or el.get("contextRef") not in ctx:
            continue
        s, e, has_dims = ctx[el.get("contextRef")]
        if has_dims or el.text is None:
            continue
        facts[etree.QName(el).localname][(s, e)] = el.text.strip()
    return facts
