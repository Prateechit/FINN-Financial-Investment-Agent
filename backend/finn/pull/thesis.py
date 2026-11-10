"""Bull vs bear, written only from computed signals, the Promise Ledger and verified transcript quotes."""
import re

from ..grounding import ungrounded
from ..llm import chat_json
from . import narrative, periods
from .ledger import compact, fmt, readable_ids

SYSTEM = """You write the tightest possible bull and bear case on a listed company for a portfolio manager.
You may use ONLY the EVIDENCE provided (computed signals S*, promise-ledger rows L*, management guidance G*,
analyst questions A*, facts by id). No outside knowledge, no news, no valuation opinions beyond the facts given.
Quote numbers exactly as given; do not compute new ones. Every number in a point must come from a ref that point
cites — cite the fact for any ₹ level or % you quote. A comparison ("outpacing", "ahead of", "lagging") must say
what its figures show — 5.6% does not outpace 20.0% — and compare like with like (a quarter-on-quarter rate is not
set against a year-on-year rate or a multi-year CAGR).
Do not append causes or implications the evidence does not state ("indicating weaker demand", "suggesting a
recovery"). An interpretation is allowed only if it follows necessarily from the cited numbers — e.g. revenue growing
faster than profit means margins are compressing; it never means they are recovering.
Analyst questions (A*) are claims, not facts — attribute them ("analysts pressed on …"). Weigh the most recent
quarter's profit and margin signals heavily: a bull case that ignores a sharp profit fall is not credible.
Comparison periods: India's fiscal year runs April–March (Q2 FY27 = Jul–Sep 2026). "Sequential" / "quarter-on-quarter"
means against the immediately preceding quarter (Q2 FY27 vs Q1 FY27) — cite both quarters' figures. The same quarter a
year earlier (Q2 FY27 vs Q2 FY26) is "year-on-year", never "sequential".
Series: signals (S*) and calc.* facts come from the standardised statements; X.* facts come from the company's exchange
filing. The two can report slightly different figures for the same metric and quarter, so a trend or comparison uses
figures from one series only. Label every figure with its own period as given in FACTS or the signal — an FY26 figure
is "FY26", not a month or a quarter.
Promise status comes only from the ledger verdict shown next to each guidance item and ledger row: say a promise is
met, delivered, kept or validated only if its verdict is "delivered". A "too_early" promise has not been tested (its
period may not have started), and "on_track" / "at_risk" promises are still open — current figures can be described
as consistent with them, never as proof they were kept.

Return JSON:
{"bull":[{"point":"max 28 words","refs":["S1","L2","G4.3","calc.cfo_pat_5y"]}],
 "bear":[{"point":"max 28 words","refs":[...]}],
 "watch":{"point":"max 25 words: the one thing in next quarter's numbers that would settle the debate","refs":[...]}}
Exactly 3 bull and 3 bear points; every point must cite at least one ref."""


def _sequential_facts(fin: dict) -> dict:
    """The latest quarter's quarter-on-quarter figures and the exact margins of the last two quarters, so a
    "sequential" claim has the right pair to cite (exchange-filing X.* figures are mostly year-on-year pairs)."""
    q = (fin.get("trajectory") or {}).get("quarterly") or []
    cols = [r["period"] for r in q[-2:]]
    ids = [f"calc.Q.ebitda_margin.{c}" for c in cols] + [f"calc.Q.{m}.{cols[-1]}" for m in ("revenue_qoq", "pat_qoq") if cols]
    return {k: fin["facts"][k] for k in ids if k in fin["facts"]}


def _quotes(point: str, fid: str, fact: dict) -> bool:
    """Does the sentence state this fact — its value and its period (e.g. "2% in FY24" for calc.roa.Mar 2024)?"""
    value = fact.get("value")
    if not isinstance(value, (int, float)):
        return False
    numbers = {round(float(x.replace(",", "")), 2) for x in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", point)}
    if round(float(value), 2) not in numbers:
        return False
    labels = {str(fact.get("period") or ""), periods.tag(fid, fact.get("period")) or ""} - {""}
    return any(re.search(rf"\b{re.escape(lbl)}\b", point, re.I) for lbl in labels)


def _guidance_line(k: str, g: dict, verdict: str | None) -> str:
    p = periods.promise_period(g)
    about = f"period {p.label}" if p else f"horizon {g.get('horizon')}"
    status = f"; ledger verdict: {verdict}" if verdict else ""
    return f"{k}: {g.get('subject')} — {g.get('target')} ({about}{status}): \"{g['statement']}\""


def build(fin: dict, calls: list[dict], ledger: dict, feedback: list[str] | None = None) -> dict:
    sig = {f"S{i + 1}": s for i, s in enumerate(fin["signals"])}
    focus = {f"A{i + 1}": f for i, f in enumerate([f for c in calls for f in c.get("analyst_focus", [])][:8])}
    latest = next((c for c in calls if c.get("guidance")), None)
    guid = {g["id"]: g for g in (latest or {}).get("guidance", [])}
    led = {f"L{i + 1}": r for i, r in enumerate(ledger.get("rows", []))}
    # Ledger verdict on each guidance item, so the prose can't call an untested promise kept.
    verdict_of = {g: r["verdict"] for r in ledger.get("rows", []) for g in r.get("guidance_ids") or []}
    key_facts = {k: v for k, v in fin["facts"].items() if k.startswith(("calc.", "X.")) and not k.startswith("calc.Q.")}
    key_facts.update(_sequential_facts(fin))
    ev = ["SIGNALS:"] + [f"{k}: [{s['tone']}] {s['text']}" for k, s in sig.items()]
    ev += ["PROMISE LEDGER:", compact(ledger)]
    ev += ["LATEST GUIDANCE:"] + [_guidance_line(k, g, verdict_of.get(k)) for k, g in guid.items()]
    ev += ["ANALYST QUESTIONS:"] + [f"{k}: {f['topic']} — \"{f['quote']}\"" for k, f in focus.items()]
    ev += ["FACTS:"] + [f"{k} = {fmt(v['value'], v['unit'])} ({v['label']}, {v['period']}"
                        + (f" = {t}" if (t := periods.tag(k, v["period"])) else "") + ")" for k, v in key_facts.items()]
    evidence = "\n".join(ev)
    prompt = evidence if not feedback else (evidence + "\n\nA reviewer checked your previous draft against the evidence and "
                                            "found these claims unsupported. Do not repeat them:\n- " + "\n- ".join(feedback))
    out = chat_json("thesis" if not feedback else "thesis_revise", "reason", SYSTEM, prompt, max_tokens=12000)
    valid = set(sig) | set(focus) | set(guid) | set(led) | set(key_facts)
    # A signal carries the figures it is computed from, so the narrative checks can tell which series a quoted value
    # belongs to ("2.4% → 9.4%" is the standardised-statements revenue series).
    lookup = {**{k: {"type": "signal", **v, "figures": [fin["facts"][f] for f in v.get("facts", []) if f in fin["facts"]]}
                 for k, v in sig.items()},
              **{k: {"type": "analyst", **v} for k, v in focus.items()},
              **{k: {"type": "guidance", **v, **({"ledger_verdict": verdict_of[k]} if k in verdict_of else {})}
                 for k, v in guid.items()},
              **{k: {"type": "ledger", "subject": v["subject"], "verdict": v["verdict"], "promise": v.get("promise"),
                     "delivered": v.get("delivered"), "why": v.get("why")} for k, v in led.items()},
              **{k: {"type": "fact", **v} for k, v in key_facts.items()}}

    def clean(p):
        point = p.get("point", "")
        refs = [r for r in p.get("refs") or [] if r in valid]
        if not refs:  # some models write "(refs: S1, L2)" into the prose instead of the field
            refs = [r for r in re.findall(r"[A-Za-z]+[\w.%\- ]*?(?=[,\]\)]|$)", " ".join(re.findall(r"\[([^\]]+)\]", point)))
                    if r.strip() in valid]
            refs = [r.strip() for r in refs]
        # inline tags like "(S2)" or "(L1, calc.cfo_pat_5y)": harvest as refs if the field was empty, then remove
        inline = re.findall(r"\(((?:[SLGA]\d+(?:\.\d+)?|calc\.[^,()]+|X\.[^,()]+)(?:,\s*(?:[SLGA]\d+(?:\.\d+)?|calc\.[^,()]+|X\.[^,()]+))*)\)", point)
        for group in inline:
            refs += [x.strip() for x in group.split(",") if x.strip() in valid and x.strip() not in refs]
        point = re.sub(r"\s*\((?:[SLGA]\d+(?:\.\d+)?|calc\.[^,()]+|X\.[^,()]+)(?:,\s*(?:[SLGA]\d+(?:\.\d+)?|calc\.[^,()]+|X\.[^,()]+))*\)", "", point)
        point = readable_ids(re.sub(r"\s*\(?refs?:?\s*\[[^\]]*\]\)?", "", point).strip(), fin["facts"])
        # A comparison needs both sides: citing "X.PAT margin.Q2 FY27" also cites the same metric a year earlier, and
        # citing one exact quarterly margin also cites the adjacent quarter's (the sequential pair).
        for r in list(refs):
            if r.startswith(("X.", "calc.Q.ebitda_margin.")):
                base, period = r.rsplit(".", 1)
                refs += [k for k in key_facts if k.rsplit(".", 1)[0] == base and k != r and k not in refs]
        # A figure the sentence quotes must be among its evidence: "ROA declined from 2% in FY24 to 1.7% in FY26" citing
        # only the FY26 fact also cites the FY24 one — the same metric, only when the sentence names both its value
        # and its period. Nothing is looked up by value alone.
        for r in list(refs):
            if r in key_facts and "." in r:
                base = r.rsplit(".", 1)[0]
                refs += [k for k, v in key_facts.items() if k not in refs and k.rsplit(".", 1)[0] == base and _quotes(point, k, v)]
        # Something only an analyst said is a claim; if the sentence doesn't attribute it, attribute it.
        if any(r.startswith("A") and r[1:].isdigit() for r in refs) and not re.search(r"analyst", point, re.I):
            point = point.rstrip(".") + " (raised by analysts on the call)."
        # A caveat carried by a cited figure must survive into the sentence, whatever the model wrote.
        for r in refs:
            label = str(lookup[r].get("label", ""))
            if "likely inorganic" in label and not re.search(r"merger|inorganic|acqui|step", point, re.I):
                point = point.rstrip(".") + f" — {label[label.index('(') + 1:].rstrip(')')}."
                break
        cited = [lookup[r] for r in refs]
        # every number must be in this point's own cited evidence — a figure elsewhere in the prompt does not count
        return {"point": point, "refs": refs, "evidence": cited,
                "grounded": bool(refs) and not ungrounded(point, evidence) and narrative.cited_grounded(point, cited)}

    return {"bull": [clean(p) for p in (out.get("bull") or [])[:3]],
            "bear": [clean(p) for p in (out.get("bear") or [])[:3]],
            "watch": clean(out["watch"]) if isinstance(out.get("watch"), dict) else None}
