"""Announcement classification: exchange category → reference category, refined by keyword rules.

The LLM is only consulted for the catch-all buckets ("General Updates", "Updates", "Others") when no rule
matches — measured on two weeks of market-wide NSE filings, rules alone cover the vast majority (see tests).
"""
import re

CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading", "earnings_call",
              "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex", "press_release",
              "postal_ballot", "agm_egm", "pledging", "unclassified"]

DIRECT = {
    "Integrated Filing- Financial": "results",
    "Financial Result Updates": "results",
    "Investor Presentation": "results",
    "Reply to Clarification- Financial results": "results",
    "Clarification - Financial Results": "results",
    "Reasons for Delayed/Non-submission of Financial Results": "results",
    "Appointment": "management_change", "Change in Management": "management_change",
    "Resignation of Director/KMP/SMP": "management_change", "Resignation": "management_change",
    "Change in Director(s)": "management_change", "Cessation": "management_change", "Retirement": "management_change",
    "Demise": "management_change", "Change in Company Secretary/Compliance Officer": "management_change",
    "Re-appointment": "management_change",
    "Acquisition": "M&A", "Amalgamation/Merger": "M&A", "Scheme of Arrangement": "M&A", "Demerger": "M&A",
    "Sale or disposal": "M&A", "Diversification/Disinvestment": "M&A", "Other Restructuring": "M&A",
    "Open Offer": "M&A", "Public Announcement-Open Offer": "M&A",
    "Buyback": "fund_raise", "Public Announcement - Buyback of Shares": "fund_raise",
    "Post Buyback Public Announcement": "fund_raise", "Closure of Buy Back": "fund_raise", "Rights Issue": "fund_raise",
    "Preferential issue": "fund_raise", "Issue of Securities": "fund_raise", "Qualified Institutional Placement": "fund_raise",
    "Credit Rating": "credit_rating", "Credit Rating- Revision": "credit_rating", "Credit Rating- New": "credit_rating",
    "Credit Rating- Others": "credit_rating",
    "Corporate Insolvency Resolution Process": "litigation", "Action(s) taken or orders passed": "litigation",
    "Action(s) initiated or orders passed": "litigation",
    "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company": "litigation",
    "Fraud/Default/Arrest": "litigation", "Defaults on Payment of Interest/Principal": "litigation",
    "Initiation of Forensic Audit": "litigation", "Final  forensic  audit  report": "litigation",
    "Delay/default in the payment of fines/penalties/dues etc. to authority": "litigation",
    "Dividend": "dividend", "Bonus": "bonus_split", "Stock split": "bonus_split",
    "Capacity addition": "capex", "Adoption of new line(s) of business": "capex",
    "Commencement of commercial production/operations": "capex",
    "Postponement of commercial production/operations": "capex",
    "Bagging/Receiving of orders/contracts": "press_release", "Awarding of order(s)/contract(s)": "press_release",
    "Product launch": "press_release", "Agreements": "press_release", "Memorandum of Understanding/Agreements": "press_release",
    "Arrangements for strategic, technical, manufacturing, or marketing tie up": "press_release",
    "Monthly Business Updates": "press_release", "News Verification": "press_release",
    "Rumour Verification - Regulation 30(11)": "press_release", "Spurt in Volume": "press_release",
    "Price movement": "press_release", "Disruption of Operations": "press_release",
    "Strikes/Lockouts/Disturbances": "press_release", "Closure of operations": "press_release",
    "Granting/withdrawal/surrender/cancellation/suspension of key licenses/ regulatory approvals": "press_release",
    "Effect(s) on listed entity due to changed regulatory  framework applicable": "press_release",
    "Rescission/termination(s)": "press_release",
    "Disclosure under SEBI Takeover Regulations": "insider_trading", "Offer for sale": "insider_trading",
    "Insider Trading": "insider_trading",
}

ROUTINE = {"Copy of Newspaper Publication", "Trading Window", "ESOP/ESOS/ESPS", "Options to purchase securities",
           "Monitoring Agency Report", "Statement of deviation(s) or variation(s) under Reg. 32", "Utilisation of Funds",
           "Certificate under SEBI (Depositories and Participants) Regulations, 2018", "Loss of Share Certificates",
           "Address Change", "Registrar & Share Transfer Agent Update", "Structural Digital Database",
           "Amendment to AOA/MOA", "Committee Meeting Updates", "Name Change", "Name and Symbol Change", "Corrigendum",
           "Addendum", "Integrated Filing- Governance", "Extension  of Financial Year", "Change in Auditors",
           "Resignation of Statutory Auditor", "Related Party Transactions", "Increase in Authorised Capital",
           "Giving guarantees/indemnity/ becoming a surety for third party", "Alteration/revision(s)", "Amendment(s)",
           "Conversion", "Disclosure of material issue"}

# Ordered keyword rules; first match wins. Applied to (exchange category + text) for ambiguous buckets.
RULES = [
    ("pledging", r"\bpledg|encumbranc|regulation 31\b"),
    ("insider_trading", r"regulation 7\(2\)|regulation 29|insider trading|sast\b|acquisition of shares by promoter|inter[- ]se transfer"),
    ("results", r"financial results?|results? for the (quarter|half|year)|quarter (and half year )?ended|unaudited|audited (standalone|consolidated)|earnings release|shareholders'? letter"
                r"|results? presentation|earnings presentation|(q[1-4]|h[12]|fy ?\d{2,4})[^.]{0,30}\bresults\b"),
    ("credit_rating", r"credit rating|\brating\b.*(crisil|icra|care|india ratings|brickwork|acuite)"),
    ("M&A", r"acqui(re|sition)|amalgamat|merger|demerg|joint venture|\bjv\b|stake (sale|in)|wholly[- ]owned subsidiary|share purchase agreement|divest"),
    ("fund_raise", r"buy[- ]?back|rights issue|\bqip\b|qualified institutions? placement|preferential (issue|allotment)|warrants|commercial paper|non[- ]convertible debenture|\bncds?\b|fund rais|raising of funds"),
    ("dividend", r"\bdividend"),
    ("bonus_split", r"\bbonus\b|sub[- ]?division|stock split|\bsplit\b"),
    ("management_change", r"appoint|resign|cessation|retire|chief (executive|financial|operating)|\bceo\b|\bcfo\b|managing director|whole[- ]time director|key managerial|\bkmp\b|\bsmp\b|demise"),
    ("litigation", r"\border\b.*(sebi|court|tribunal|nclt|nclat|tax|gst|authority)|penalt|show cause|litigation|insolvency|\bnclt\b|arbitra|demand notice|income tax|search (and|&) seizure|\bfine\b"),
    ("earnings_call", r"transcript|audio recording|recording of|con(ference)?[ .-]?call|earnings call|investor call"),
    ("investor_meetings", r"analyst|investor meet|institutional investor|investors? conference|one[- ]on[- ]one|non[- ]deal roadshow|\bnon deal\b"),
    ("capex", r"capacity (expansion|addition)|new (plant|facility|unit)|greenfield|brownfield|capital expenditure|\bcapex\b|commission(ed|ing) of"),
    ("postal_ballot", r"postal ballot|e-?voting"),
    ("agm_egm", r"annual general meeting|\bagm\b|extra[- ]?ordinary general meeting|\begm\b|shareholders'? meeting"),
    ("press_release", r"press release|order|contract|launch|partnership|tie[- ]?up|mou|clarification|rumou?r|business update"),
    ("unclassified", r"esop|esos|esps|newspaper|trading window|compliance certificate|regulation 74|loss of share|duplicate share|\besg\b|brsr|auditor"),
]
_RULES = [(c, re.compile(p, re.I)) for c, p in RULES]

# Routine paperwork that keyword rules would otherwise misread (e.g. "name change of a wholly owned subsidiary").
_ROUTINE_RX = re.compile(r"name change|change (in|of) (the )?name|regulation 8\(2\)|code of (practices and procedures for )?fair disclosure"
                         r"|registrar|share transfer agent|change in (the )?(corporate|registered) office|loss of share|duplicate share"
                         r"|trading window|compliance certificate|regulation 74\(5\)|regulation 40\(9\)|esop|esos|esps"
                         r"|structural digital database|newspaper", re.I)

BROAD = {"General Updates", "Updates", "Others", "Outcome of Board Meeting", "Press Release", "Press Release (Revised)",
         "Analysts/Institutional Investor Meet/Con. Call Updates", "Shareholders meeting", "Record Date",
         "Allotment of Securities", "Copy of Newspaper Publication"}


def rule_classify(exch_category: str, text: str) -> tuple[str | None, str]:
    """Return (category, method). category None means 'needs LLM'."""
    cat = (exch_category or "").strip()
    blob = f"{cat} . {text or ''}"
    if cat in DIRECT:
        return DIRECT[cat], "exchange"
    if cat in ROUTINE and cat != "Copy of Newspaper Publication":
        return "unclassified", "exchange"
    if cat == "Analysts/Institutional Investor Meet/Con. Call Updates":
        return ("earnings_call" if _RULES[CATEGORIES_INDEX["earnings_call"]][1].search(text or "") else "investor_meetings"), "rule"
    if cat == "Shareholders meeting":
        return ("postal_ballot" if re.search(r"postal ballot", text or "", re.I) else "agm_egm"), "rule"
    if cat == "Copy of Newspaper Publication":
        for c in ("results", "postal_ballot", "agm_egm", "dividend"):
            if _RULES[CATEGORIES_INDEX[c]][1].search(text or ""):
                return c, "rule"
        return "unclassified", "rule"
    if cat in ("General Updates", "Updates", "Others") and _ROUTINE_RX.search(text or ""):
        return "unclassified", "rule"
    if cat == "Allotment of Securities":
        return ("unclassified" if re.search(r"esop|esos|esps|employee stock", text or "", re.I) else "fund_raise"), "rule"
    for c, rx in _RULES:
        if rx.search(blob):
            return c, "rule"
    if cat == "Record Date":
        return "unclassified", "rule"
    if cat in ("Press Release", "Press Release (Revised)"):
        return "press_release", "rule"
    return None, "none"


CATEGORIES_INDEX = {c: i for i, (c, _) in enumerate(RULES)}

LLM_SYSTEM = """You classify Indian listed-company exchange filings into exactly one category.
Categories: results, M&A, fund_raise, management_change, litigation, insider_trading, earnings_call, investor_meetings,
credit_rating, dividend, bonus_split, capex, press_release, postal_ballot, agm_egm, pledging, unclassified.
Use "unclassified" for routine compliance paperwork that would not move the stock.
Reply as JSON: {"category": "<one category>"}"""


def classify(exch_category: str, text: str, use_llm: bool = True) -> tuple[str, str]:
    cat, how = rule_classify(exch_category, text)
    if cat:
        return cat, how
    if use_llm:
        from ..llm import LLMUnavailable, chat_json
        try:
            out = chat_json("classify", "fast", LLM_SYSTEM, f"Exchange category: {exch_category}\nText: {text[:1200]}", 50)
            if out.get("category") in CATEGORIES:
                return out["category"], "llm"
        except LLMUnavailable:
            pass
    return "unclassified", "default"
