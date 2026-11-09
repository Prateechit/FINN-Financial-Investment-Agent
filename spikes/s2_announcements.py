"""Spike 2: corporate announcements from BSE and NSE."""
import datetime as dt
import json

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# --- BSE ---
s = requests.Session()
s.headers.update({"User-Agent": UA, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com",
                  "Accept": "application/json, text/plain, */*"})
to = dt.date.today()
fr = to - dt.timedelta(days=3)
url = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
       f"?pageno=1&strCat=-1&strPrevDate={fr:%Y%m%d}&strScrip=500325&strSearch=P&strToDate={to:%Y%m%d}&strType=C&subcategory=-1")
r = s.get(url, timeout=20)
print("BSE scrip", r.status_code, r.headers.get("content-type"), len(r.content))
try:
    j = r.json()
    rows = j.get("Table", [])
    print("rows", len(rows))
    if rows:
        print(json.dumps(rows[0], indent=1)[:1500])
except Exception as e:
    print("json err", e, r.text[:300])

# all companies, single day
url2 = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
        f"?pageno=1&strCat=-1&strPrevDate={fr:%Y%m%d}&strScrip=&strSearch=P&strToDate={to:%Y%m%d}&strType=C&subcategory=-1")
r = s.get(url2, timeout=20)
try:
    j = r.json()
    print("BSE all rows page1", len(j.get("Table", [])), "total", j.get("Table1"))
    cats = {}
    for row in j.get("Table", []):
        cats[row.get("CATEGORYNAME")] = cats.get(row.get("CATEGORYNAME"), 0) + 1
    print(cats)
except Exception as e:
    print("json err", e, r.status_code, r.text[:200])

# --- NSE ---
n = requests.Session()
n.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"})
r0 = n.get("https://www.nseindia.com/", timeout=20)
print("NSE home", r0.status_code, list(n.cookies.keys()))
r = n.get("https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=RELIANCE", timeout=20)
print("NSE ann", r.status_code, len(r.content))
try:
    j = r.json()
    print(len(j), json.dumps(j[0], indent=1)[:1200])
except Exception as e:
    print("json err", e, r.text[:200])
r = n.get("https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=RELIANCE&period=Quarterly", timeout=20)
print("NSE fin results", r.status_code, len(r.content))
try:
    j = r.json()
    print(len(j), json.dumps(j[0], indent=1)[:1500])
except Exception as e:
    print("json err", e, r.text[:200])
