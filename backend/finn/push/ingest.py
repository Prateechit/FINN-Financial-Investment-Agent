"""Push pipeline: fetch → classify → score → enrich. Idempotent; safe to run on a schedule."""
import datetime as dt
import json

from sqlalchemy import select

from ..config import BACKEND
from ..db import Announcement, Company, get_settings, now, portfolio_symbols, session
from ..sources import docs, nse, prices, screener
from . import classify, enrich, score
from .alerts import _session_date

PORTFOLIO_FILE = BACKEND / "portfolio.json"


def load_portfolio() -> list[str]:
    spec = json.loads(PORTFOLIO_FILE.read_text())
    with session() as s:
        for row in s.scalars(select(Company)):
            row.in_portfolio = False
        for p in spec["holdings"]:
            c = s.get(Company, p["symbol"]) or Company(symbol=p["symbol"])
            c.in_portfolio, c.weight = True, p["weight"]
            c.sector = p.get("sector") or c.sector
            s.merge(c)
    for p in spec["holdings"]:
        with session() as s:
            c = s.get(Company, p["symbol"])
            if not c.name:
                try:
                    sc = screener.company(p["symbol"])
                    c.name, c.bse_code = sc["name"], sc["bse_code"]
                except Exception as e:  # noqa: BLE001
                    print("screener meta failed", p["symbol"], e)
    return [p["symbol"] for p in spec["holdings"]]


def _price_move(symbol: str, ts: dt.datetime) -> float | None:
    rows = prices.history(symbol, 60)
    days = [r.date for r in rows]
    d = _session_date(ts, days)
    if d is None:
        return None
    i = days.index(d)
    return (rows[i].close / rows[i - 1].close - 1) * 100 if i > 0 else None


def annual_revenue_cr(symbol: str) -> float | None:
    try:
        t = screener.company(symbol)["tables"]["annual"]
        row = t["rows"].get("Sales") or t["rows"].get("Revenue")
        return next((v for v in reversed(row) if v), None)
    except Exception:  # noqa: BLE001
        return None


def process(a: Announcement, weight: float, settings: dict, use_llm: bool = True):
    cat, how = classify.rule_classify(a.exch_category, a.text)
    # Exchange summaries are often just "<company> has informed the Exchange about <category>".
    # When the summary is thin, read the document itself (plain text, no LLM) for the title, category and score.
    doc_text = ""
    generic = len(enrich.clean_text(a.text)) < 80
    if a.pdf_url and (cat is None or (generic and score.BASE.get(cat, 0) >= 30)):
        try:
            doc = docs.pages(a.pdf_url, max_pages=3)
            a.subject = docs.subject(doc)
            doc_text = " ".join(doc["pages"])[:9000]
        except Exception:  # noqa: BLE001
            pass
    # Keyword rules only see the head of a document; whole bodies are full of incidental words
    # ("customer acquisition", "disruptive technology") that would misfire.
    head = f"{a.subject or ''} {a.text or ''} {_body_start(doc_text)}"
    if cat is None and doc_text:
        cat, how = classify.rule_classify(a.exch_category, head)
        how = "rule+pdf" if cat else how
    if cat is None:
        cat, how = classify.classify(a.exch_category, f"{a.subject or ''} {a.text}", use_llm=use_llm)
    a.category, a.classified_by = cat, how
    a.materiality, a.reasons = score.score(cat, a.exch_category, head, weight, _price_move(a.symbol, a.ts),
                                           settings["price_move_pct"], annual_revenue_cr(a.symbol), full_text=doc_text)


def _body_start(doc_text: str, n: int = 1200) -> str:
    """Opening of the letter after the exchange address block ('Dear Sir/Madam' onwards)."""
    i = doc_text.lower().find("dear ")
    return doc_text[i:i + n] if i >= 0 else doc_text[:n]


def ingest_announcements(days: int = 3, symbols: list[str] | None = None, use_llm: bool = True) -> dict:
    settings = get_settings()
    symbols = symbols or portfolio_symbols()
    to, frm = dt.date.today(), dt.date.today() - dt.timedelta(days=days)
    stats = {"fetched": 0, "new": 0, "enriched": 0, "errors": []}
    for sym in symbols:
        try:
            rows = nse.announcements(sym, frm, to)
        except Exception as e:  # noqa: BLE001
            stats["errors"].append(f"{sym}: {e}")
            continue
        stats["fetched"] += len(rows)
        with session() as s:
            weight = (s.get(Company, sym).weight if s.get(Company, sym) else 0) or 0
            for r in rows:
                if s.get(Announcement, r["id"]):
                    continue
                a = Announcement(**r)
                process(a, weight, settings, use_llm)
                s.add(a)
                stats["new"] += 1
    stats["enriched"] = enrich_pending(use_llm=use_llm)
    return stats


def enrich_pending(limit: int = 250, use_llm: bool = True) -> int:
    """Enrich material announcements that have no enrichment yet, or whose results numbers were pending."""
    with session() as s:
        cands = list(s.scalars(select(Announcement).where(Announcement.materiality >= 45)
                               .order_by(Announcement.ts.desc()).limit(400)))
    n = 0
    for a in cands:
        e = a.enrichment or {}
        needs = (a.enriched_at is None or e.get("status") in ("pending", "llm_unavailable", "fallback")
                 and (now() - a.enriched_at) > dt.timedelta(minutes=30))
        if not needs or (not use_llm and a.category != "results"):
            continue
        try:
            out = enrich.enrich(a)
        except Exception as ex:  # noqa: BLE001
            out = {"type": "error", "status": "error", "detail": str(ex)[:200]}
        with session() as s:
            row = s.get(Announcement, a.id)
            row.enrichment, row.enriched_at = out, now()
            if out and out.get("type") == "summary":
                row.summary = out.get("line")
        n += 1
        if n >= limit:
            break
    return n


def reprocess(use_llm: bool = True) -> int:
    """Re-run classification + scoring over stored announcements (after rule changes)."""
    settings = get_settings()
    with session() as s:
        weights = {c.symbol: c.weight for c in s.scalars(select(Company))}
        rows = list(s.scalars(select(Announcement)))
        for a in rows:
            process(a, weights.get(a.symbol, 0), settings, use_llm)
    return len(rows)


def ingest_prices() -> dict:
    return prices.update(portfolio_symbols())
