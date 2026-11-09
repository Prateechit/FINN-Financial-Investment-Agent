"""Spike 3: NSE results XBRL parse + NSE windowed announcements + screener.in page."""
import collections
import re

import requests
from bs4 import BeautifulSoup
from lxml import etree

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
n = requests.Session()
n.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"})
n.get("https://www.nseindia.com/", timeout=20)

for sym in ["RELIANCE", "HDFCBANK"]:
    res = n.get(f"https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={sym}&period=Quarterly", timeout=20).json()
    res.sort(key=lambda x: x["toDate"][-4:] + {"Mar": "03", "Jun": "06", "Sep": "09", "Dec": "12"}[x["toDate"][3:6]] + x["consolidated"], reverse=True)
    for x in res[:4]:
        print(sym, x["toDate"], x["consolidated"], x["bank"], x["filingDate"], x["xbrl"][-40:])
    latest = next(x for x in res if x["consolidated"] == "Consolidated")
    xml = n.get(latest["xbrl"], timeout=30).content
    root = etree.fromstring(xml)
    ctx = {}
    for c in root.iter("{*}context"):
        start = c.find(".//{*}startDate")
        end = c.find(".//{*}endDate")
        inst = c.find(".//{*}instant")
        dims = [m.text for m in c.iter("{*}explicitMember")]
        ctx[c.get("id")] = (start.text if start is not None else None, end.text if end is not None else (inst.text if inst is not None else None), dims)
    facts = collections.defaultdict(dict)
    for el in root:
        if not isinstance(el.tag, str) or el.get("contextRef") is None:
            continue
        name = etree.QName(el).localname
        s, e, dims = ctx.get(el.get("contextRef"), (None, None, None))
        if dims:
            continue
        facts[name][f"{s}..{e}"] = el.text
    print(sym, "fact names:", len(facts))
    for k in ["RevenueFromOperations", "OtherIncome", "Income", "Expenses", "FinanceCosts", "DepreciationDepletionAndAmortisationExpense",
              "ProfitBeforeTax", "TaxExpense", "ProfitLossForPeriod", "ProfitLossForPeriodFromContinuingOperations",
              "InterestEarned", "OperatingProfitBeforeProvisionAndContingencies", "ProvisionsOtherThanTaxAndContingencies",
              "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "DateOfStartOfReportingPeriod", "WhetherResultsAreAuditedOrUnaudited"]:
        if k in facts:
            print("   ", k, dict(facts[k]))
    print("   sample names:", sorted(facts)[:60])

# windowed announcements across all companies
r = n.get("https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=07-11-2026&to_date=09-11-2026", timeout=30)
j = r.json()
print("NSE window all:", r.status_code, len(j))
print(collections.Counter(x["desc"] for x in j).most_common(40))

# screener
s = requests.get("https://www.screener.in/company/DIXON/consolidated/", headers={"User-Agent": UA}, timeout=30)
print("screener", s.status_code, len(s.text))
soup = BeautifulSoup(s.text, "lxml")
for sec in ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios"]:
    t = soup.select_one(f"section#{sec} table")
    if t:
        hdr = [th.get_text(strip=True) for th in t.select("thead th")]
        rows = [[td.get_text(strip=True) for td in tr.select("td")] for tr in t.select("tbody tr")]
        print(sec, hdr[-4:], [r[0] for r in rows])
docs = soup.select_one("section#documents")
if docs:
    for blk in docs.select("div.documents"):
        h = blk.select_one("h3")
        links = blk.select("a")
        print("DOCS", h.get_text(strip=True) if h else None, len(links))
        for a in links[:6]:
            print("    ", re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:80], a.get("href")[:120])
    for li in docs.select(".concalls li")[:5]:
        print("  CONCALL", re.sub(r"\s+", " ", li.get_text(" ", strip=True))[:100], [a.get("href") for a in li.select("a")])
