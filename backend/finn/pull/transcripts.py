"""Concall transcripts → structured, quote-verified guidance (one long-context call per transcript, cached)."""
import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor

from ..grounding import ungrounded
from ..llm import chat_json
from ..sources import docs
from . import periods

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
    return periods.quarter_discussed(call_date).label


def attach_period(g: dict, call_quarter: str) -> dict:
    """Store the fiscal period a promise is about next to management's own wording ("Q4" said on the Q3 FY26 call →
    period "Q4 FY26"); horizon keeps the original words."""
    p = periods.resolve(g.get("horizon"), call_quarter)
    g["period"], g["period_kind"] = (p.label, p.kind) if p else (None, None)
    return g


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


_TURN = re.compile(r"\n\s*([A-Z][A-Za-z.'’\- ]{2,60}?)\s*:\s*\n")
_INTRODUCED = re.compile(r"line of\s+(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){0,3}?)\s+(?:from|with|of)\b")


def _person(name: str) -> str:
    return docs.norm(re.sub(r"^(mr|ms|mrs|dr|shri)\.?\s+", "", name.strip(), flags=re.I))


def speaker_at(full: str, statement: str, analysts: frozenset = frozenset()) -> str | None:
    """The speaker label of the turn in which `statement` occurs ("Atul Lall:" on its own line).

    Opening remarks often contain section headings in the same "Heading:" shape. Real speakers take several turns;
    a heading appears once — so one-off labels are skipped unless the moderator introduced that person.
    """
    words = re.findall(r"\w+", statement)[:7]
    m = re.search(r"\W+".join(map(re.escape, words)), full, re.I) if len(words) >= 3 else None
    if not m:
        return None
    counts: dict = {}
    for t in _TURN.finditer(full):
        counts[t.group(1).strip()] = counts.get(t.group(1).strip(), 0) + 1
    for t in reversed(list(_TURN.finditer(full, 0, m.start()))):
        name = t.group(1).strip()
        if counts[name] >= 2 or name.lower() == "moderator" or _person(name) in analysts:
            return name
    return None


def extract(call: dict, idx: int) -> dict:
    doc = docs.pages(call["transcript"])
    body = "".join(f"\n[[p.{i + 1}]]\n{t}" for i, t in enumerate(doc["pages"]))[:MAX_CHARS]
    raw = chat_json(f"transcript:{call['quarter']}", "long", SYSTEM,
                    f"Transcript of the earnings call discussing {call['quarter']}:\n{body}", max_tokens=12000)
    # A model's JSON can be the wrong shape — a bare list of items, a string where an object belongs. Wrong-shaped
    # parts are skipped (and recorded); they must not lose the transcript's other, well-formed items.
    if isinstance(raw, list):
        raw = {"guidance": raw}
    if not isinstance(raw, dict):
        raw = {}
    full = "\n" + "\n".join(doc["pages"])
    analysts = {_person(n) for n in _INTRODUCED.findall(full)}  # the moderator introduces every questioner
    kept, dropped, not_mgmt, rejected = [], 0, 0, []
    items = raw.get("guidance")
    for j, g in enumerate(items if isinstance(items, list) else []):
        gid = f"G{idx}.{j + 1}"
        if not isinstance(g, dict):
            dropped += 1
            rejected.append({"id": gid, "reason": "malformed", "statement": str(g)[:280]})
            continue
        statement = g.get("statement") if isinstance(g.get("statement"), str) else ""
        page = docs.find_quote(doc, statement, _page(g.get("page")))
        if page is None or not FORWARD.search(statement):
            dropped += 1
            rejected.append({"id": gid, "reason": "not_verbatim" if page is None else "not_forward_looking",
                             "page": _page(g.get("page")), "statement": statement[:280]})
            continue
        who = speaker_at(full, statement, frozenset(analysts))
        if who and (who.lower() == "moderator" or _person(who) in analysts):
            not_mgmt += 1  # verbatim, forward-looking — but said by an analyst, so not a promise
            rejected.append({"id": gid, "reason": "not_management", "page": page, "speaker": who, "statement": statement[:280]})
            continue
        if who:
            g["speaker"] = who
        g.update({"id": gid, "page": page, "call": call["quarter"], "call_label": call["label"],
                  "url": call["transcript"]})
        kept.append(attach_period(g, call["quarter"]))
    focus = []
    for f in raw.get("analyst_focus") if isinstance(raw.get("analyst_focus"), list) else []:
        if not isinstance(f, dict) or not isinstance(f.get("quote"), str):
            continue
        page = docs.find_quote(doc, f["quote"], _page(f.get("page")))
        if page:
            focus.append({**f, "page": page, "url": call["transcript"], "call": call["quarter"]})
    return {"call": call["quarter"], "label": call["label"], "url": call["transcript"], "pages": doc["n"],
            "guidance": kept, "dropped_unverified": dropped + not_mgmt, "dropped_not_management": not_mgmt,
            "rejected": rejected, "business": _grounded_business(raw.get("business"), doc),
            "analyst_focus": focus}


def _page(v) -> int | None:
    """The model's page hint as an int ("5" and 5.0 included), else None — it only orders the search."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _strip_unverified(text: str, source: str) -> str:
    """Drop any clause whose figures do not appear in the transcript."""
    if not text or not ungrounded(text, source):
        return text
    clauses = re.split(r"(?<=[;.])\s+|,\s+(?=[A-Z₹\d])", text)
    return " ".join(c for c in clauses if not ungrounded(c, source)).strip(" ;,")


def _grounded_business(biz, doc: dict) -> dict | None:
    if isinstance(biz, str):  # a bare summary instead of {"summary": …}
        biz = {"summary": biz}
    if not isinstance(biz, dict) or not biz:
        return None
    source = " ".join(doc["pages"])
    biz["summary"] = _strip_unverified(biz.get("summary") if isinstance(biz.get("summary"), str) else "", source)
    segments = biz.get("segments") if isinstance(biz.get("segments"), list) else []
    biz["segments"] = [s for s in segments if isinstance(s, dict)]
    for s in biz["segments"]:
        s["detail"] = _strip_unverified(s.get("detail") if isinstance(s.get("detail"), str) else "", source)
    return biz


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
