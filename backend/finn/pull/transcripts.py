"""Concall transcripts → structured, quote-verified guidance (one long-context call per transcript, cached)."""
import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor

from ..llm import chat_json
from ..push.results import fy_label
from ..sources import docs

MAX_CHARS = 90_000

# A guidance statement must look forward; this rejects historical results a model mislabels as guidance.
FORWARD = re.compile(r"\b(expect|will\b|would\b|shall\b|target|guid|aim|plan|going forward|anticipat|should|outlook|next|"
                     r"intend|envisag|confident|likely|looking (at|to)|on track|trajectory|by (fy|20)|over the (next|coming)|"
                     r"medium[- ]term|long[- ]term|aspir|ambition|endeavou?r|hope|estimate|project|"
                     r"see (a|the|this|it|that|growth|margin)|going to|in the range|upcoming|future|ahead)", re.I)

SYSTEM = """You are an equity analyst reading an Indian listed company's earnings-call transcript.
Extract only what MANAGEMENT said about the FUTURE: explicit targets, ranges, expectations and plans.
Ignore historical results, analyst opinions, and safe-harbour boilerplate. Use only this transcript.

Return JSON:
{"guidance":[{
  "metric":"revenue_growth|revenue|margin|ebitda|profit|volume|order_book|order_inflow|capex|capacity|debt|working_capital|market_share|segment|cost|return_ratio|launch|other",
  "subject":"what exactly, e.g. 'consolidated revenue', 'EBITDA margin', 'mobile segment volume'",
  "statement":"management's words copied EXACTLY from the transcript (one or two sentences, max 280 chars)",
  "target":"the target as stated, e.g. '15-17%', '₹1,000 crore', 'double-digit', 'margin expansion'",
  "low":number or null,"high":number or null,"unit":"%|Cr|units|x|other",
  "horizon":"period it applies to, e.g. 'FY27', 'H2 FY27', 'Q3 FY27', 'by FY28', 'next 2-3 years', 'medium term'",
  "kind":"quantitative|directional",
  "speaker":"name or role",
  "page":page number from the [[p.N]] marker}],
 "business":{"summary":"max 60 words: what the company does and how it makes money, in management's framing",
             "segments":[{"name":"segment","detail":"max 20 words, include any revenue-share figure management stated"}]},
 "analyst_focus":[{"topic":"max 8 words","quote":"analyst's words copied exactly, max 200 chars","page":number}]}

Rules: at most 14 guidance items, headline numbers first (growth, margins, profit, capex, orders).
analyst_focus: at most 4 — the issues analysts pressed hardest on. Copy text exactly; never paraphrase inside "statement" or "quote"."""


def quarter_discussed(call_date: dt.date) -> str:
    """A call in Nov discusses the Sep quarter; Feb → Dec; May → Mar; Aug → Jun."""
    m = call_date.month
    qe_month = {1: 12, 2: 12, 3: 12, 4: 3, 5: 3, 6: 3, 7: 6, 8: 6, 9: 6, 10: 9, 11: 9, 12: 9}[m]
    year = call_date.year - (1 if qe_month == 12 and m <= 3 else 0)
    day = 31 if qe_month in (3, 12) else 30
    return fy_label(dt.date(year, qe_month, day))


def pick(concalls: list[dict], n: int = 5) -> list[dict]:
    out, seen = [], set()
    for c in concalls:
        if not c.get("transcript") or not c.get("date"):
            continue
        q = quarter_discussed(dt.date.fromisoformat(c["date"]))
        if q in seen:
            continue
        seen.add(q)
        out.append({**c, "quarter": q})
        if len(out) == n:
            break
    return out


def extract(call: dict, idx: int) -> dict:
    doc = docs.pages(call["transcript"])
    body = "".join(f"\n[[p.{i + 1}]]\n{t}" for i, t in enumerate(doc["pages"]))[:MAX_CHARS]
    raw = chat_json(f"transcript:{call['quarter']}", "long", SYSTEM,
                    f"Transcript of the earnings call discussing {call['quarter']}:\n{body}", max_tokens=6000)
    kept, dropped = [], 0
    for j, g in enumerate(raw.get("guidance") or []):
        page = docs.find_quote(doc, g.get("statement") or "", g.get("page"))
        if page is None or not FORWARD.search(g.get("statement") or ""):
            dropped += 1
            continue
        g.update({"id": f"G{idx}.{j + 1}", "page": page, "call": call["quarter"], "call_label": call["label"],
                  "url": call["transcript"]})
        kept.append(g)
    focus = []
    for f in raw.get("analyst_focus") or []:
        page = docs.find_quote(doc, f.get("quote") or "", f.get("page"))
        if page:
            focus.append({**f, "page": page, "url": call["transcript"], "call": call["quarter"]})
    return {"call": call["quarter"], "label": call["label"], "url": call["transcript"], "pages": doc["n"],
            "guidance": kept, "dropped_unverified": dropped, "business": raw.get("business"), "analyst_focus": focus}


def extract_all(concalls: list[dict], n: int = 5) -> list[dict]:
    calls = pick(concalls, n)
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(extract, c, len(calls) - i) for i, c in enumerate(calls)]  # G1 = oldest
        out = []
        for c, f in zip(calls, futs):
            try:
                out.append(f.result())
            except Exception as e:  # noqa: BLE001 — one unreadable transcript should not sink the memo
                out.append({"call": c["quarter"], "label": c["label"], "url": c["transcript"], "error": str(e)[:200],
                            "guidance": [], "analyst_focus": []})
    return out
