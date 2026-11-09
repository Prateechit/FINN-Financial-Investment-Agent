"""Spike 4: NSE integrated-filing endpoint discovery + BSE transcript PDF text extraction."""
import io
import json

import fitz
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
n = requests.Session()
n.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"})
n.get("https://www.nseindia.com/", timeout=20)

for path in [
    "/api/integrated-filing-results?index=equities&symbol=DIXON",
    "/api/integrated-filing-results?index=equities&symbol=DIXON&period_ended=all&type=Integrated%20Filing-%20Financials",
    "/api/integrated-filing?index=equities&symbol=DIXON",
    "/api/corporate-announcements?index=equities&symbol=DIXON&from_date=01-10-2026&to_date=09-11-2026",
]:
    r = n.get("https://www.nseindia.com" + path, timeout=30)
    body = r.text
    print(path, r.status_code, len(body))
    try:
        j = r.json()
        data = j.get("data", j) if isinstance(j, dict) else j
        print("   n=", len(data) if hasattr(data, "__len__") else "?")
        if data:
            print("   ", json.dumps(data[0] if isinstance(data, list) else data)[:900])
    except Exception as e:
        print("   not json", body[:150])

B = {"User-Agent": UA, "Referer": "https://www.bseindia.com/"}
url = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=995a3a71-4a1e-4c1f-a29a-6c6747e4ca10.pdf"
r = requests.get(url, headers=B, timeout=60)
print("BSE pdf", r.status_code, r.headers.get("content-type"), len(r.content))
doc = fitz.open(stream=r.content, filetype="pdf")
text = [p.get_text() for p in doc]
print("pages", len(text), "chars", sum(map(len, text)))
print(text[3][:1500])
