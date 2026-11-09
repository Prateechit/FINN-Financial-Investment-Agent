"""Bull vs bear, written only from computed signals, the Promise Ledger and verified transcript quotes."""
import re

from ..grounding import ungrounded
from ..llm import chat_json
from .ledger import compact, fmt, readable_ids

SYSTEM = """You write the tightest possible bull and bear case on a listed company for a portfolio manager.
You may use ONLY the EVIDENCE provided (computed signals S*, promise-ledger rows L*, management guidance G*,
analyst questions A*, facts by id). No outside knowledge, no news, no valuation opinions beyond the facts given.
Quote numbers exactly as given; do not compute new ones.
Do not append causes or implications the evidence does not state ("indicating weaker demand", "suggesting a
recovery"). An interpretation is allowed only if it follows necessarily from the cited numbers — e.g. revenue growing
faster than profit means margins are compressing; it never means they are recovering.
Analyst questions (A*) are claims, not facts — attribute them ("analysts pressed on …"). Weigh the most recent
quarter's profit and margin signals heavily: a bull case that ignores a sharp profit fall is not credible.

Return JSON:
{"bull":[{"point":"max 28 words","refs":["S1","L2","G4.3","calc.cfo_pat_5y"]}],
 "bear":[{"point":"max 28 words","refs":[...]}],
 "watch":{"point":"max 25 words: the one thing in next quarter's numbers that would settle the debate","refs":[...]}}
Exactly 3 bull and 3 bear points; every point must cite at least one ref."""


def build(fin: dict, calls: list[dict], ledger: dict, feedback: list[str] | None = None) -> dict:
    sig = {f"S{i + 1}": s for i, s in enumerate(fin["signals"])}
    focus = {f"A{i + 1}": f for i, f in enumerate([f for c in calls for f in c.get("analyst_focus", [])][:8])}
    latest = next((c for c in calls if c.get("guidance")), None)
    guid = {g["id"]: g for g in (latest or {}).get("guidance", [])}
    led = {f"L{i + 1}": r for i, r in enumerate(ledger.get("rows", []))}
    key_facts = {k: v for k, v in fin["facts"].items() if k.startswith(("calc.", "X.")) and not k.startswith("calc.Q.")}
    ev = ["SIGNALS:"] + [f"{k}: [{s['tone']}] {s['text']}" for k, s in sig.items()]
    ev += ["PROMISE LEDGER:", compact(ledger)]
    ev += ["LATEST GUIDANCE:"] + [f"{k}: {g.get('subject')} — {g.get('target')} ({g.get('horizon')}): \"{g['statement']}\"" for k, g in guid.items()]
    ev += ["ANALYST QUESTIONS:"] + [f"{k}: {f['topic']} — \"{f['quote']}\"" for k, f in focus.items()]
    ev += ["FACTS:"] + [f"{k} = {fmt(v['value'], v['unit'])} ({v['label']}, {v['period']})" for k, v in key_facts.items()]
    evidence = "\n".join(ev)
    prompt = evidence if not feedback else (evidence + "\n\nA reviewer checked your previous draft against the evidence and "
                                            "found these claims unsupported. Do not repeat them:\n- " + "\n- ".join(feedback))
    out = chat_json("thesis" if not feedback else "thesis_revise", "reason", SYSTEM, prompt, max_tokens=12000)
    valid = set(sig) | set(focus) | set(guid) | set(led) | set(key_facts)
    lookup = {**{k: {"type": "signal", **v} for k, v in sig.items()}, **{k: {"type": "analyst", **v} for k, v in focus.items()},
              **{k: {"type": "guidance", **v} for k, v in guid.items()},
              **{k: {"type": "ledger", "subject": v["subject"], "verdict": v["verdict"], "promise": v.get("promise"),
                     "why": v.get("why")} for k, v in led.items()},
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
        # A year-on-year comparison needs both sides: citing "X.PAT margin.Q2 FY27" also cites the same metric a year earlier.
        for r in list(refs):
            if r.startswith("X."):
                base, period = r.rsplit(".", 1)
                refs += [k for k in key_facts if k.rsplit(".", 1)[0] == base and k != r and k not in refs]
        # Something only an analyst said is a claim; if the sentence doesn't attribute it, attribute it.
        if any(r.startswith("A") and r[1:].isdigit() for r in refs) and not re.search(r"analyst", point, re.I):
            point = point.rstrip(".") + " (raised by analysts on the call)."
        # A caveat carried by a cited figure must survive into the sentence, whatever the model wrote.
        for r in refs:
            label = str(lookup[r].get("label", ""))
            if "likely inorganic" in label and not re.search(r"merger|inorganic|acqui|step", point, re.I):
                point = point.rstrip(".") + f" — {label[label.index('(') + 1:].rstrip(')')}."
                break
        return {"point": point, "refs": refs, "evidence": [lookup[r] for r in refs],
                "grounded": not ungrounded(point, evidence) and bool(refs)}

    return {"bull": [clean(p) for p in (out.get("bull") or [])[:3]],
            "bear": [clean(p) for p in (out.get("bear") or [])[:3]],
            "watch": clean(out["watch"]) if isinstance(out.get("watch"), dict) else None}
