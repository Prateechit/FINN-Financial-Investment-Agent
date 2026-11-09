"""Research memo orchestration for any NSE symbol.

Stage 1 (seconds, free): deterministic sections from standardised statements.
Stage 2 (one-time per transcript, cached): quote-verified guidance extraction.
Stage 3 (two reasoning calls): Promise Ledger + bull/bear.
State is persisted after each stage so the UI renders progressively by polling.
"""
import datetime as dt
import threading
import traceback

from sqlalchemy import func, select

from ..db import LLMCall, kv_get, kv_set, now, session
from ..llm import LLMUnavailable, available
from . import financials, ledger, thesis, transcripts

_running: set[str] = set()
_lock = threading.Lock()


def _key(sym: str) -> str:
    return f"research:{sym}"


def get(sym: str) -> dict | None:
    return kv_get(_key(sym))


def _usage(since: dt.datetime) -> dict:
    with session() as s:
        rows = s.execute(select(LLMCall.provider, LLMCall.model, LLMCall.cache_hit, func.count(), func.sum(LLMCall.tokens_in),
                                func.sum(LLMCall.tokens_out)).where(LLMCall.ts >= since, LLMCall.ok)
                         .group_by(LLMCall.provider, LLMCall.model, LLMCall.cache_hit)).all()
    out = {"calls": 0, "cache_hits": 0, "tokens_in": 0, "tokens_out": 0, "models": []}
    for p, m, hit, n, ti, to in rows:
        out["calls"] += n
        if hit:
            out["cache_hits"] += n
        else:
            out["tokens_in"] += ti or 0
            out["tokens_out"] += to or 0
        if f"{p}:{m}" not in out["models"]:
            out["models"].append(f"{p}:{m}")
    return out


def build(sym: str, force: bool = False) -> dict:
    sym = sym.upper().strip()
    prev = get(sym)
    if prev and not force and prev.get("status") in ("done", "partial"):
        age = now() - dt.datetime.fromisoformat(prev["updated"])
        if age < dt.timedelta(hours=24):
            return prev
    started = now()
    state = {"symbol": sym, "status": "running", "stage": "Reading financial statements", "started": started.isoformat(),
             "updated": started.isoformat(), "sections": {}, "errors": []}

    def save(**kw):
        state.update(kw)
        state["updated"] = now().isoformat()
        state["usage"] = _usage(started)
        kv_set(_key(sym), state)

    try:
        fin = financials.build(sym)
    except Exception as e:  # noqa: BLE001
        save(status="error", stage="", errors=[f"Could not load financial statements for {sym}: {e}"])
        return state
    secs = state["sections"]
    secs.update({k: fin[k] for k in ("snapshot", "trajectory", "balance_sheet", "cash", "signals")})
    state["facts"] = fin["facts"]
    secs["sources"] = {"statements": fin["snapshot"]["url"], "annual_reports": fin["annual_reports"][:3],
                       "concalls": [c for c in fin["concalls"] if c.get("transcript")][:5]}
    if not any(available().values()):
        save(status="partial", stage="", errors=["AI sections need an LLM API key (GEMINI_API_KEY or GROQ_API_KEY)."])
        return state
    save(stage="Reading the last 5 earnings-call transcripts")

    try:
        calls = transcripts.extract_all(fin["concalls"], 5)
        good = [c for c in calls if c.get("guidance")]
        secs["guidance"] = {"calls": [{k: c.get(k) for k in ("call", "label", "url", "pages", "dropped_unverified", "error")}
                                      | {"n": len(c.get("guidance", []))} for c in calls],
                            "items": [g for c in calls for g in c.get("guidance", [])]}
        latest_biz = next((c["business"] for c in calls if c.get("business")), None)
        secs["business"] = {"from_transcript": latest_biz, "source_call": next((c["call"] for c in calls if c.get("business")), None),
                            "source_url": next((c["url"] for c in calls if c.get("business")), None),
                            "analyst_focus": [f for c in calls[:2] for f in c.get("analyst_focus", [])][:6]}
        if not good:
            save(status="partial", stage="", errors=state["errors"] + ["No transcript could be read; ledger skipped."])
            return state
        save(stage="Auditing guidance against reported numbers")
        q = fin["trajectory"]["quarterly"]
        latest_q = q[-1]["period"] if q else "unknown"
        secs["ledger"] = ledger.build(calls, fin["facts"], latest_q)
        save(stage="Writing the bull and bear case")
        secs["thesis"] = thesis.build(fin, calls, secs["ledger"])
        save(status="done", stage="")
    except LLMUnavailable as e:
        save(status="partial", stage="", errors=state["errors"] + [f"AI unavailable: {e}"[:300]])
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        save(status="partial", stage="", errors=state["errors"] + [f"{type(e).__name__}: {e}"[:300]])
    return state


def start(sym: str, force: bool = False) -> dict:
    """Kick off a background build; return current state immediately."""
    sym = sym.upper().strip()
    prev = get(sym)
    with _lock:
        if sym in _running:
            return prev or {"symbol": sym, "status": "running", "stage": "Starting", "sections": {}}
        fresh = prev and prev.get("status") in ("done", "partial") and \
            now() - dt.datetime.fromisoformat(prev["updated"]) < dt.timedelta(hours=24)
        if fresh and not force:
            return prev
        _running.add(sym)

    def run():
        try:
            build(sym, force=True)
        finally:
            with _lock:
                _running.discard(sym)

    threading.Thread(target=run, daemon=True).start()
    return {"symbol": sym, "status": "running", "stage": "Starting", "sections": (prev or {}).get("sections", {})}
