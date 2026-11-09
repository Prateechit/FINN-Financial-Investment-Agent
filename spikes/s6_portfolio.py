"""Spike 6: validate candidate portfolio tickers on yfinance + screener + NSE integrated filings."""
import requests, yfinance as yf, time
from bs4 import BeautifulSoup
T = "RELIANCE HDFCBANK INFY BAJFINANCE SUNPHARMA MARUTI LT ASIANPAINT TITAN BHARTIARTL DIXON POLYCAB PERSISTENT TRENT HAL IRCTC DEEPAKNTR PAYTM SUZLON".split()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
px = yf.download([t + ".NS" for t in T], period="5d", group_by="ticker", progress=False)
n = requests.Session(); n.headers.update({"User-Agent": UA, "Referer": "https://www.nseindia.com/"}); n.get("https://www.nseindia.com/", timeout=20)
for t in T:
    ok_px = not px[t + ".NS"]["Close"].dropna().empty
    s = requests.get(f"https://www.screener.in/company/{t}/consolidated/", headers={"User-Agent": UA}, timeout=30)
    soup = BeautifulSoup(s.text, "lxml")
    name = soup.select_one("h1").get_text(strip=True) if soup.select_one("h1") else None
    nconc = len(soup.select("section#documents .concalls li"))
    q = soup.select_one("section#quarters thead")
    last_q = q.select("th")[-1].get_text(strip=True) if q else None
    try:
        f = n.get(f"https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={t}", timeout=30).json()["data"]
        last_if = f[0]["qe_Date"] if f else None
    except Exception as e:
        last_if = f"ERR {e}"
    print(f"{t:11s} px={ok_px} screener={s.status_code} {name!s:40.40s} concalls={nconc:3d} lastQ={last_q} nseIF={last_if}")
    time.sleep(1)
