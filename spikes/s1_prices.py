"""Spike 1: EOD price/volume availability (yfinance primary, NSE bhavcopy fallback)."""
import datetime as dt
import io
import zipfile

import requests
import yfinance as yf

TICKERS = ["RELIANCE", "HDFCBANK", "DIXON", "SUZLON", "PAYTM"]

df = yf.download([t + ".NS" for t in TICKERS], period="1mo", interval="1d",
                 group_by="ticker", auto_adjust=False, progress=False)
for t in TICKERS:
    sub = df[t + ".NS"].dropna()
    print(f"yf {t:10s} rows={len(sub)} last={sub.index[-1].date()} close={sub['Close'].iloc[-1]:.2f} vol={int(sub['Volume'].iloc[-1])}")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
d = dt.date.today()
for _ in range(7):
    d -= dt.timedelta(days=1)
    url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    r = requests.get(url, headers=UA, timeout=20)
    print("bhav", d, r.status_code, len(r.content))
    if r.status_code == 200:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        txt = z.read(z.namelist()[0]).decode()
        print(txt.splitlines()[0][:300])
        print(next(l for l in txt.splitlines() if ",RELIANCE," in l)[:300])
        break
