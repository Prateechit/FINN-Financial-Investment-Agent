"""Triggered alerts, evaluated on read against the user's current thresholds.

Price: |daily return| ≥ X%  (also reports the move in σ of the stock's own recent volatility)
Volume: volume ≥ k × trailing N-day average
Announcement: category in the user's watch-list and materiality ≥ threshold
Price/volume alerts are linked to a same-session filing when one exists — "volume 3× · results filed 15:42".
"""
import datetime as dt
import statistics

from sqlalchemy import select

from ..db import Announcement, Company, session
from ..sources.prices import history

MARKET_CLOSE = dt.time(15, 30)


def _session_date(ts: dt.datetime, trading_days: list[dt.date]) -> dt.date | None:
    """The trading session in which the market could first react to a filing made at `ts`."""
    d = ts.date() if ts.time() < MARKET_CLOSE else ts.date() + dt.timedelta(days=1)
    for t in trading_days:
        if t >= d:
            return t
    return None


def eod_moves(symbol: str, settings: dict, days: int = 7) -> list[dict]:
    override = (settings.get("overrides") or {}).get(symbol, {})
    pct_th = override.get("price_move_pct", settings["price_move_pct"])
    vol_th = override.get("volume_multiple", settings["volume_multiple"])
    look = settings["volume_lookback_days"]
    rows = history(symbol, look + days + 5)
    out = []
    for i in range(max(look + 1, len(rows) - days), len(rows)):
        cur, prev = rows[i], rows[i - 1]
        window = rows[i - look:i]
        rets = [window[j].close / window[j - 1].close - 1 for j in range(1, len(window))]
        sigma = statistics.pstdev(rets) if len(rets) > 5 else None
        ret = cur.close / prev.close - 1
        avg_vol = statistics.fmean([w.volume for w in window if w.volume]) if window else None
        mult = cur.volume / avg_vol if avg_vol and cur.volume else None
        z = ret / sigma if sigma else None
        base = {"symbol": symbol, "date": cur.date.isoformat(), "close": round(cur.close, 2),
                "ret_pct": round(ret * 100, 2), "sigma": round(z, 1) if z is not None else None,
                "vol_mult": round(mult, 2) if mult else None, "volume": cur.volume}
        if abs(ret) * 100 >= pct_th:
            out.append({**base, "kind": "price", "threshold": pct_th,
                        "title": f"{symbol} {ret * 100:+.1f}% to ₹{cur.close:,.2f}"
                                 + (f" · {abs(z):.1f}σ move" if z is not None else "")})
        if mult and mult >= vol_th:
            out.append({**base, "kind": "volume", "threshold": vol_th,
                        "title": f"{symbol} volume {mult:.1f}× its {look}-day average"
                                 + f" · price {ret * 100:+.1f}%"})
    return out


def compute(settings: dict, days: int = 7) -> list[dict]:
    with session() as s:
        symbols = list(s.scalars(select(Company.symbol).where(Company.in_portfolio)))
        since = dt.datetime.now() - dt.timedelta(days=days + 3)
        anns = list(s.scalars(select(Announcement).where(Announcement.ts >= since, Announcement.symbol.in_(symbols))))
    alerts = []
    for sym in symbols:
        trading = [r.date for r in history(sym, 40)]
        moves = eod_moves(sym, settings, days)
        sym_anns = [a for a in anns if a.symbol == sym and a.materiality >= 25]
        for m in moves:
            d = dt.date.fromisoformat(m["date"])
            linked = [a for a in sym_anns if _session_date(a.ts, trading) == d]
            linked.sort(key=lambda a: -a.materiality)
            if linked:
                a = linked[0]
                m["linked"] = {"id": a.id, "category": a.category, "ts": a.ts.isoformat(), "text": a.summary or a.text}
            m["id"] = f"{m['kind']}:{sym}:{m['date']}"
            alerts.append(m)
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    seen = set()  # one alert per company/category/day — a results outcome, press release and deck are one event
    for a in sorted(anns, key=lambda a: -a.materiality):
        key = (a.symbol, a.category, a.ts.date())
        if key in seen:
            continue
        if a.ts >= cutoff and a.category in settings["alert_categories"] and a.materiality >= settings["min_alert_materiality"]:
            seen.add(key)
            alerts.append({"id": f"ann:{a.id}", "kind": "announcement", "symbol": a.symbol, "date": a.ts.date().isoformat(),
                           "ts": a.ts.isoformat(), "category": a.category, "materiality": a.materiality,
                           "title": f"{a.symbol} · {a.category.replace('_', ' ')}", "announcement_id": a.id,
                           "text": a.summary or a.subject or a.text})
    alerts.sort(key=lambda x: (x["date"], x.get("ts", "")), reverse=True)
    return alerts
