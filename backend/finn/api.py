import csv
import datetime as dt
import io
import json
import threading

import requests
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import func, select

from .config import CORS_ORIGINS, DEFAULT_SETTINGS, INGEST_TOKEN, UA
from .db import Announcement, Company, LLMCall, get_settings, init_db, kv_get, kv_set, now, session
from .llm import available
from .push import alerts as alerts_mod
from .push import results
from .push.enrich import clean_text
from .push.present import short_title as _title
from .push.score import tier
from .pull import research
from .sources import prices, symbols

app = FastAPI(title="FINN API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.on_event("startup")
def _startup():
    init_db()
    with session() as s:
        empty = s.scalar(select(func.count()).select_from(Company)) == 0
    if empty:
        from .push.ingest import load_portfolio
        threading.Thread(target=load_portfolio, daemon=True).start()


@app.get("/api/health")
def health():
    with session() as s:
        last = s.scalar(select(func.max(Announcement.ts)))
        n = s.scalar(select(func.count()).select_from(Announcement))
    return {"ok": True, "llm": available(), "announcements": n, "latest_filing": last,
            "last_ingest": kv_get("last_ingest"), "server_time": now().isoformat()}


# ---------------- push ----------------

def _story(group: list[Announcement], names: dict, hist: dict | None = None) -> dict:
    group.sort(key=lambda a: (-a.materiality, -(1 if a.enrichment and a.enrichment.get("status") == "ok" else 0), a.ts))
    p = group[0]
    return {"id": p.id, "symbol": p.symbol, "name": names.get(p.symbol, p.symbol), "category": p.category,
            "tier": tier(p.materiality), "materiality": p.materiality, "reasons": p.reasons, "ts": p.ts.isoformat(),
            "title": _title(p), "subject": p.subject, "summary": p.summary, "text": clean_text(p.text), "exch_category": p.exch_category,
            "pdf_url": p.pdf_url, "enrichment": p.enrichment, "reaction": _reaction(p.symbol, p.ts, (hist or {}).get(p.symbol)),
            "related": [{"id": a.id, "ts": a.ts.isoformat(), "exch_category": a.exch_category, "text": clean_text(a.text)[:160],
                         "pdf_url": a.pdf_url} for a in sorted(group[1:], key=lambda a: a.ts)]}


def _cluster(rows: list[Announcement]) -> list[list[Announcement]]:
    """Same company + same category within 36h = one story (e.g. results outcome + press release + deck)."""
    groups: list[list[Announcement]] = []
    for a in sorted(rows, key=lambda a: a.ts):
        for g in groups:
            if g[0].symbol == a.symbol and g[0].category == a.category and a.category != "unclassified" \
                    and abs((a.ts - g[-1].ts).total_seconds()) < 36 * 3600:
                g.append(a)
                break
        else:
            groups.append([a])
    return groups


def _reaction(sym: str, ts: dt.datetime, h: list | None = None) -> dict | None:
    """Price move in the first session that could react to a filing (after 15:30 → next session)."""
    h = h if h is not None else prices.history(sym, 40)
    days = [r.date for r in h]
    d = alerts_mod._session_date(ts, days)
    if d is None:
        return None
    i = days.index(d)
    if i == 0:
        return None
    return {"date": d.isoformat(), "pct": round((h[i].close / h[i - 1].close - 1) * 100, 2)}


@app.get("/api/digest")
def digest(hours: int = Query(24, ge=1, le=24 * 30)):
    since = dt.datetime.now() - dt.timedelta(hours=hours)
    with session() as s:
        names = {c.symbol: c.name or c.symbol for c in s.scalars(select(Company))}
        port = {c.symbol for c in s.scalars(select(Company).where(Company.in_portfolio))}
        rows = list(s.scalars(select(Announcement).where(Announcement.ts >= since, Announcement.symbol.in_(port))))
    hist = prices.history_many({a.symbol for a in rows}, 40)  # one query, not one per story
    stories = [_story(g, names, hist) for g in _cluster(rows)]
    stories.sort(key=lambda x: (-x["materiality"], x["ts"]))
    material = [s for s in stories if s["tier"] != "routine"]
    routine = [s for s in stories if s["tier"] == "routine"]
    by_cat: dict = {}
    for r in routine:
        by_cat.setdefault(r["category"], []).append(r)
    return {"window_hours": hours, "since": since.isoformat(), "generated": dt.datetime.now().isoformat(),
            "counts": {"filings": len(rows), "stories": len(stories), "critical": sum(s["tier"] == "critical" for s in stories),
                       "notable": sum(s["tier"] == "notable" for s in stories), "routine": len(routine)},
            "stories": material,
            "routine": [{"category": k, "count": len(v), "items": v} for k, v in sorted(by_cat.items(), key=lambda kv: -len(kv[1]))]}


@app.get("/api/alerts")
def get_alerts(days: int = Query(7, ge=1, le=30)):
    return {"settings": get_settings(), "alerts": alerts_mod.compute(get_settings(), days)}


@app.get("/api/settings")
def read_settings():
    return get_settings()


@app.put("/api/settings")
def write_settings(body: dict):
    cur = kv_get("settings") or {}
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS and k != "overrides":
            continue
        if k in ("price_move_pct", "price_move_sigma", "volume_multiple") and not (0 < float(v) <= 50):
            raise HTTPException(400, f"{k} out of range")
        cur[k] = v
    kv_set("settings", cur)
    return get_settings()


@app.get("/api/portfolio")
def portfolio():
    with session() as s:
        comps = list(s.scalars(select(Company).where(Company.in_portfolio).order_by(Company.weight.desc())))
        since = dt.datetime.now() - dt.timedelta(days=7)
        counts = dict(s.execute(select(Announcement.symbol, func.count()).where(Announcement.ts >= since, Announcement.materiality >= 45)
                                .group_by(Announcement.symbol)).all())
    hist = prices.history_many([c.symbol for c in comps], 30)
    out = []
    for c in comps:
        h = hist[c.symbol]
        last, prev = (h[-1], h[-2]) if len(h) >= 2 else (None, None)
        out.append({"symbol": c.symbol, "name": c.name, "sector": c.sector, "weight": c.weight,
                    "close": last.close if last else None, "date": last.date.isoformat() if last else None,
                    "change_pct": round((last.close / prev.close - 1) * 100, 2) if last and prev else None,
                    "spark": [round(r.close, 2) for r in h], "material_7d": counts.get(c.symbol, 0)})
    return out


@app.get("/api/company/{symbol}")
def company(symbol: str):
    symbol = symbol.upper()
    with session() as s:
        c = s.get(Company, symbol)
        anns = list(s.scalars(select(Announcement).where(Announcement.symbol == symbol).order_by(Announcement.ts.desc()).limit(40)))
    card = kv_get(f"results_card:{symbol}", dt.timedelta(hours=6))
    if card is None:
        try:
            card = results.results_card(symbol)
            kv_set(f"results_card:{symbol}", card)
        except Exception:  # noqa: BLE001
            card = None
    h = prices.history(symbol, 120)
    return {"symbol": symbol, "name": c.name if c else None, "in_portfolio": bool(c and c.in_portfolio),
            "weight": c.weight if c else None, "results": card,
            "prices": [{"d": r.date.isoformat(), "c": round(r.close, 2), "v": r.volume} for r in h],
            "announcements": [{"id": a.id, "ts": a.ts.isoformat(), "category": a.category, "tier": tier(a.materiality),
                               "materiality": a.materiality, "title": _title(a), "pdf_url": a.pdf_url} for a in anns]}


@app.get("/api/announcement/{aid:path}")
def announcement(aid: str):
    with session() as s:
        a = s.get(Announcement, aid)
        if not a:
            raise HTTPException(404)
        names = {a.symbol: (s.get(Company, a.symbol).name if s.get(Company, a.symbol) else a.symbol)}
    return _story([a], names)


# ---------------- pull ----------------

def _public(state: dict) -> dict:
    out = {k: v for k, v in state.items() if k != "facts"}
    facts = state.get("facts") or {}
    secs = out.get("sections", {})
    for sig in secs.get("signals") or []:
        sig["evidence"] = [facts[f] for f in sig.get("facts", []) if f in facts]
    return out


def _resolve(raw: str) -> dict:
    """Map what the user typed (ticker or company name) to an NSE symbol before any provider is called."""
    try:
        rows = _equity_list()
    except Exception:  # noqa: BLE001 — NSE list unreachable: accept ticker-shaped input as before, nothing else
        q = raw.strip().upper()
        ok = bool(symbols.TICKER.fullmatch(q))
        return {"symbol": q if ok else None, "matched_by": "symbol" if ok else None, "suggestions": [],
                "list_unavailable": True}
    return symbols.resolve(raw, rows)


def _unresolved(raw: str, res: dict) -> dict:
    sugg = res.get("suggestions") or []
    if res.get("list_unavailable"):
        msg = f"“{raw.strip()}” doesn’t look like an NSE symbol, and the NSE symbol list is unreachable right now. Try the ticker."
    elif sugg:
        msg = f"“{raw.strip()}” matches several NSE companies. Did you mean: " + \
            ", ".join(f"{s['symbol']} ({s['name']})" for s in sugg) + "?"
    else:
        msg = f"No NSE-listed company matches “{raw.strip()}”. Try the ticker symbol, e.g. TATATECH."
    return {"symbol": raw.strip().upper(), "status": "error", "stage": "", "errors": [msg], "sections": {},
            "suggestions": sugg}


@app.post("/api/research/{symbol}")
def research_start(symbol: str, force: bool = False):
    res = _resolve(symbol)
    if not res["symbol"]:
        return _unresolved(symbol, res)  # nothing is started or stored
    out = _public(research.start(res["symbol"], force))
    if res["symbol"] != symbol.strip().upper():
        out["resolved_from"] = symbol.strip()
    return out


@app.get("/api/research/{symbol}")
def research_get(symbol: str):
    res = _resolve(symbol)
    # Resolved symbol first, so "Tata Technologies" reads TATATECH's memo; exact key second, for older records.
    st = (research.get(res["symbol"]) if res["symbol"] else None) or research.get(symbol.strip().upper())
    if not st:
        raise HTTPException(404, "not started")
    return _public(st)


@app.get("/api/research")
def research_list():
    with session() as s:
        from .db import KV
        values = list(s.scalars(select(KV.value).where(KV.key.like("research:%"))))  # one query for all memos
    out = []
    for v in values:
        st = json.loads(v) or {}
        snap = (st.get("sections") or {}).get("snapshot") or {}
        out.append({"symbol": st.get("symbol"), "name": snap.get("name"), "status": st.get("status"), "updated": st.get("updated"),
                    "verdicts": ((st.get("sections") or {}).get("ledger") or {}).get("counts")})
    return sorted(out, key=lambda x: x.get("updated") or "", reverse=True)


def _equity_list() -> list[dict]:
    cached = kv_get("nse_equity_list", dt.timedelta(days=7))
    if cached:
        return cached
    r = requests.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    rows = [{"symbol": x["SYMBOL"].strip(), "name": x["NAME OF COMPANY"].strip()} for x in csv.DictReader(io.StringIO(r.text))]
    kv_set("nse_equity_list", rows)
    return rows


@app.get("/api/search")
def search(q: str = Query(..., min_length=1)):
    try:
        rows = _equity_list()
    except Exception:  # noqa: BLE001 — fall back to known companies
        with session() as s:
            rows = [{"symbol": c.symbol, "name": c.name or c.symbol} for c in s.scalars(select(Company))]
    return symbols.search_rows(q, rows)


# ---------------- ops ----------------

@app.post("/api/ingest")
def ingest(bg: BackgroundTasks, x_finn_token: str = Header(default=""), days: int = 2):
    if not INGEST_TOKEN or x_finn_token != INGEST_TOKEN:
        raise HTTPException(401)

    def run():
        from .push import ingest as ing
        out = {"prices": ing.ingest_prices(), "announcements": ing.ingest_announcements(days), "at": now().isoformat()}
        kv_set("last_ingest", out)
    bg.add_task(run)
    return {"started": True}


@app.get("/api/usage")
def usage():
    with session() as s:
        rows = s.execute(select(LLMCall.task, LLMCall.provider, LLMCall.model, LLMCall.cache_hit, func.count(),
                                func.sum(LLMCall.tokens_in), func.sum(LLMCall.tokens_out), func.avg(LLMCall.ms))
                         .where(LLMCall.ok).group_by(LLMCall.task, LLMCall.provider, LLMCall.model, LLMCall.cache_hit)).all()
        by_cls = dict(s.execute(select(Announcement.classified_by, func.count()).group_by(Announcement.classified_by)).all())
    tasks: dict = {}
    for task, p, m, hit, n, ti, to, ms in rows:
        key = task.split(":")[0]
        t = tasks.setdefault(key, {"task": key, "calls": 0, "cache_hits": 0, "tokens_in": 0, "tokens_out": 0, "models": set()})
        t["calls"] += n
        t["cache_hits"] += n if hit else 0
        if not hit:
            t["tokens_in"] += ti or 0
            t["tokens_out"] += to or 0
        t["models"].add(f"{p}:{m}")
    for t in tasks.values():
        t["models"] = sorted(t["models"])
    return {"tasks": sorted(tasks.values(), key=lambda t: -t["tokens_in"]), "classification": by_cls}
