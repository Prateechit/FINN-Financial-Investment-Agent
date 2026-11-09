"""Spike 7: enumerate NSE announcement categories (desc) over 2 weeks with a sample each."""
import collections, json, requests
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
n = requests.Session(); n.headers.update({"User-Agent": UA, "Referer": "https://www.nseindia.com/"}); n.get("https://www.nseindia.com/", timeout=20)
rows = []
for fr, to in [("26-10-2026", "01-11-2026"), ("02-11-2026", "09-11-2026")]:
    rows += n.get(f"https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={fr}&to_date={to}", timeout=60).json()
c = collections.Counter(r["desc"] for r in rows)
sample = {}
for r in rows: sample.setdefault(r["desc"], (r["attchmntText"] or "")[:140])
print(len(rows))
for d, k in c.most_common():
    print(f"{k:5d} | {d} | {sample[d]}")
json.dump(rows, open("spikes/nse_2w.json", "w"))
