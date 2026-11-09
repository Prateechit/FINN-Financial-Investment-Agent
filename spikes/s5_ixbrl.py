"""Spike 5: parse NSE Integrated Filing XBRL (contexts, tags) for an industrial and a bank."""
import collections, requests
from lxml import etree
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
n = requests.Session(); n.headers.update({"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
n.get("https://www.nseindia.com/", timeout=20)
for sym in ["DIXON", "HDFCBANK"]:
    lst = n.get(f"https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={sym}", timeout=30).json()["data"]
    print(sym, [(x["qe_Date"], str(x["consolidated"])[:4], x["type"][-10:]) for x in lst[:8]])
    x = next(x for x in lst if x.get("consolidated") == "Consolidated" and "Financ" in x["type"])
    root = etree.fromstring(n.get(x["xbrl"], timeout=30).content)
    ctx = {}
    for c in root.iter("{*}context"):
        g = lambda t: (c.find(f".//{{*}}{t}").text if c.find(f".//{{*}}{t}") is not None else None)
        ctx[c.get("id")] = (g("startDate"), g("endDate") or g("instant"), [m.text for m in c.iter("{*}explicitMember")])
    f = collections.defaultdict(dict)
    for el in root:
        if isinstance(el.tag, str) and el.get("contextRef"):
            s, e, d = ctx[el.get("contextRef")]
            if not d: f[etree.QName(el).localname][f"{s}..{e}"] = el.text
    print("  periods:", sorted({k for v in f.values() for k in v})[:10])
    for k in ["RevenueFromOperations","Expenses","FinanceCosts","DepreciationDepletionAndAmortisationExpense","ProfitBeforeTax","ProfitLossForPeriod","InterestEarned","InterestExpended","OperatingProfitBeforeProvisionAndContingencies","ProvisionsOtherThanTaxAndContingencies","ProfitLossFromOrdinaryActivitiesBeforeTax","ProfitLossForThePeriod","LevelOfRoundingUsedInFinancialStatements","NatureOfReportStandaloneConsolidated"]:
        if k in f: print("   ", k, f[k])
