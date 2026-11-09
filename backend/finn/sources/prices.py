"""EOD prices: yfinance primary, NSE bhavcopy fallback for the latest session."""
import datetime as dt
import io
import zipfile

import requests
import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from ..config import UA
from ..db import PriceEOD, session


def _upsert(rows: list[dict]):
    with session() as s:
        for r in rows:
            s.merge(PriceEOD(**r))


def from_yfinance(symbols: list[str], period: str = "6mo") -> int:
    df = yf.download([f"{x}.NS" for x in symbols], period=period, interval="1d", group_by="ticker",
                     auto_adjust=False, progress=False, threads=True)
    rows = []
    for sym in symbols:
        try:
            sub = df[f"{sym}.NS"].dropna(subset=["Close"])
        except KeyError:
            continue
        for idx, r in sub.iterrows():
            rows.append({"symbol": sym, "date": idx.date(), "open": float(r["Open"]), "high": float(r["High"]),
                         "low": float(r["Low"]), "close": float(r["Close"]), "volume": float(r["Volume"])})
    _upsert(rows)
    return len(rows)


def from_bhavcopy(symbols: list[str], day: dt.date) -> int:
    url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    if r.status_code != 200:
        return 0
    z = zipfile.ZipFile(io.BytesIO(r.content))
    lines = z.read(z.namelist()[0]).decode().splitlines()
    hdr = lines[0].split(",")
    ix = {k: hdr.index(k) for k in ("TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol")}
    want, rows = set(symbols), []
    for line in lines[1:]:
        f = line.split(",")
        if f[ix["TckrSymb"]] in want and f[ix["SctySrs"]] == "EQ":
            rows.append({"symbol": f[ix["TckrSymb"]], "date": day, "open": float(f[ix["OpnPric"]]),
                         "high": float(f[ix["HghPric"]]), "low": float(f[ix["LwPric"]]),
                         "close": float(f[ix["ClsPric"]]), "volume": float(f[ix["TtlTradgVol"]])})
    _upsert(rows)
    return len(rows)


def update(symbols: list[str]) -> dict:
    try:
        n = from_yfinance(symbols)
        return {"source": "yfinance", "rows": n}
    except Exception as e:  # noqa: BLE001
        day, n = dt.date.today(), 0
        for _ in range(5):
            n = from_bhavcopy(symbols, day)
            if n:
                break
            day -= dt.timedelta(days=1)
        return {"source": "bhavcopy", "rows": n, "yfinance_error": str(e)[:200]}


def history_many(symbols, days: int = 90) -> dict[str, list[PriceEOD]]:
    """history() for many symbols in ONE query — a remote database makes per-symbol queries expensive.

    Same semantics as history(): the last `days` rows per symbol whatever their dates (so stale data still renders),
    via ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC). Works on SQLite and Postgres.
    """
    symbols = sorted(set(symbols))
    if not symbols:
        return {}
    rn = func.row_number().over(partition_by=PriceEOD.symbol, order_by=PriceEOD.date.desc()).label("rn")
    ranked = select(PriceEOD, rn).where(PriceEOD.symbol.in_(symbols)).subquery()
    latest = aliased(PriceEOD, ranked)
    out: dict[str, list[PriceEOD]] = {s: [] for s in symbols}
    with session() as s:
        for r in s.scalars(select(latest).where(ranked.c.rn <= days).order_by(latest.symbol, latest.date)):
            out[r.symbol].append(r)
    return out


def history(symbol: str, days: int = 90) -> list[PriceEOD]:
    with session() as s:
        rows = s.scalars(select(PriceEOD).where(PriceEOD.symbol == symbol).order_by(PriceEOD.date.desc()).limit(days))
        return list(reversed(list(rows)))
