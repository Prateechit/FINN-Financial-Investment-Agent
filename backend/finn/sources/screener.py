"""screener.in company page: standardised financial tables + primary-document links (no login needed)."""
import datetime as dt
import re

import requests
from bs4 import BeautifulSoup

from ..config import UA
from ..db import kv_get, kv_set

TABLES = {"quarters": "quarters", "profit-loss": "annual", "balance-sheet": "balance", "cash-flow": "cashflow",
          "ratios": "ratios", "shareholding": "shareholding"}


class NotFound(Exception):
    pass


def _num(s: str):
    s = s.replace(",", "").replace("%", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fetch(symbol: str, consolidated: bool) -> str | None:
    url = f"https://www.screener.in/company/{symbol}/" + ("consolidated/" if consolidated else "")
    for attempt in range(3):
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.status_code == 404:
            return None
        if r.status_code == 200:
            return r.text
        if r.status_code == 429:
            import time
            time.sleep(3 * (attempt + 1))
            continue
        r.raise_for_status()
    raise RuntimeError(f"screener {symbol}: HTTP {r.status_code}")


def _table(soup, sec_id):
    t = soup.select_one(f"section#{sec_id} table.data-table")
    if not t:
        return None
    cols = [th.get_text(strip=True) for th in t.select("thead th")][1:]
    rows = {}
    for tr in t.select("tbody tr"):
        tds = tr.select("td")
        if not tds:
            continue
        label = re.sub(r"\s*\+$", "", tds[0].get_text(" ", strip=True)).strip()
        if label.lower().startswith("raw pdf"):
            rows["_pdf"] = [a.get("href") if (a := td.select_one("a")) else None for td in tds[1:]]
            continue
        rows[label] = [_num(td.get_text(strip=True)) for td in tds[1:]]
    return {"cols": cols, "rows": rows}


def _has_data(tbl) -> bool:
    return bool(tbl) and any(v is not None for k, vs in tbl["rows"].items() if not k.startswith("_") for v in vs)


def company(symbol: str, max_age_hours: int = 12) -> dict:
    symbol = symbol.upper().strip()
    key = f"screener:{symbol}"
    if (hit := kv_get(key, dt.timedelta(hours=max_age_hours))) is not None:
        return hit
    basis, html = "consolidated", _fetch(symbol, True)
    soup = BeautifulSoup(html, "lxml") if html else None
    if soup is None or not _has_data(_table(soup, "quarters")):
        basis, html = "standalone", _fetch(symbol, False)
        if html is None:
            raise NotFound(symbol)
        soup = BeautifulSoup(html, "lxml")

    name = soup.select_one("h1")
    top = {}
    for li in soup.select("#top-ratios li"):
        k = li.select_one(".name")
        v = li.select_one(".value")
        if k and v:
            top[k.get_text(strip=True)] = v.get_text(" ", strip=True)
    about = soup.select_one(".company-profile .about p") or soup.select_one(".about p")
    bse = None
    for a in soup.select("a[href*='bseindia.com']"):
        if m := re.search(r"/(\d{6})/?", a.get("href", "")):
            bse = m.group(1)
            break
    sector = None
    for a in soup.select("#peers a[href*='/market/']"):
        sector = a.get_text(strip=True)
    tables = {name_: _table(soup, sec) for sec, name_ in TABLES.items()}

    docs = soup.select_one("section#documents")
    annual_reports, concalls = [], []
    if docs:
        for blk in docs.select("div.documents"):
            h = (blk.select_one("h3") or blk).get_text(" ", strip=True).lower()
            if "annual" in h:
                for a in blk.select("a"):
                    txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
                    if m := re.search(r"(\d{4})", txt):
                        annual_reports.append({"year": int(m.group(1)), "url": a.get("href")})
        for li in docs.select(".concalls li"):
            date_el = li.select_one(".ink-600") or li
            date_txt = date_el.get_text(" ", strip=True)[:8]
            entry = {"label": date_txt, "transcript": None, "ppt": None}
            for a in li.select("a"):
                kind = a.get_text(strip=True).lower()
                if kind.startswith("transcript"):
                    entry["transcript"] = a.get("href")
                elif kind == "ppt":
                    entry["ppt"] = a.get("href")
            try:
                entry["date"] = dt.datetime.strptime(date_txt.strip(), "%b %Y").date().isoformat()
            except ValueError:
                entry["date"] = None
            concalls.append(entry)

    out = {
        "symbol": symbol, "basis": basis, "name": name.get_text(strip=True) if name else symbol,
        "about": about.get_text(" ", strip=True) if about else None, "bse_code": bse, "sector": sector,
        "top": top, "tables": tables, "annual_reports": annual_reports, "concalls": concalls,
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "url": f"https://www.screener.in/company/{symbol}/" + ("consolidated/" if basis == "consolidated" else ""),
    }
    kv_set(key, out)
    return out


def is_lender(c: dict) -> bool:
    rows = (c["tables"].get("quarters") or {}).get("rows", {})
    return "Revenue" in rows and "Financing Profit" in rows or "Financing Margin %" in rows
