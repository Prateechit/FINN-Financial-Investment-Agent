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
from ..push import results
from . import financials, ledger, narrative, periods, thesis, transcripts, verify

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


def _add_results_facts(sym: str, fin: dict) -> None:
    """Exact exchange-XBRL quarter figures (NII, pre-provision profit, provisions for lenders; EBITDA otherwise)."""
    try:
        card = results.results_card(sym)
    except Exception:  # noqa: BLE001 — the memo stands without them
        return
    if not card or card["source"] != "NSE XBRL":
        return
    q, url = card["quarter"]["label"], card["links"][0]
    add = lambda fid, label, v, unit, period: v is not None and fin["facts"].__setitem__(fid, {  # noqa: E731
        "id": fid, "label": label, "value": v, "unit": unit, "period": period, "source": "NSE exchange XBRL", "url": url})
    for r in card["rows"]:
        add(f"X.{r['key']}.{q}", f"{r['label']} (exchange filing)", r["cur"], "₹ Cr", q)
        add(f"X.{r['key']}.{card['yoy_label']}", f"{r['label']} (exchange filing)", r["yoy"], "₹ Cr", card["yoy_label"])
        add(f"X.{r['key']}_yoy.{q}", f"{r['label']} growth YoY (exchange filing)", r["yoy_pct"], "%", q)
    for m in card["margins"]:
        add(f"X.{m['label']}.{q}", f"{m['label']} (exchange filing)", m["cur"], "%", q)
        add(f"X.{m['label']}.{card['yoy_label']}", f"{m['label']} (exchange filing)", m["yoy"], "%", card["yoy_label"])


def _verify(fin: dict, calls: list[dict], secs: dict) -> None:
    """Second-model check plus FINN's own narrative checks (comparison wording, promise status). Unsupported thesis
    points trigger one rewrite; anything still unsupported is flagged.

    A point is verified=True only if the verifier model judged it supported in the pass that checked its current text;
    False if the verifier or a narrative check found it unsupported; None (unchecked) otherwise — e.g. the verifier
    was unavailable for the rewrite, or skipped that point."""
    q = fin["trajectory"]["quarterly"]
    latest = periods.from_calendar(q[-1]["period"]) if q else None

    def judge(th: dict, led: dict) -> tuple[dict, set]:
        """(results by claim id, ids the verifier model actually judged) — the second set is empty if it didn't run."""
        model = verify.check(verify.claims_for(th, led))
        res = dict(model)
        for k, v in narrative.thesis_issues(th, secs["ledger"], latest).items():
            if res.get(k, {"supported": True})["supported"]:  # the verifier's own objection, if any, stands
                res[k] = v
        return res, set(model)

    res, judged = judge(secs["thesis"], secs["ledger"])
    first_ran, recheck = bool(judged), None
    if not res:
        secs["verification"] = {"status": "skipped"}
        return
    bad = [f"\"{p['point']}\" — {res[f'{side}{i + 1}']['issue']}" for side in ("bull", "bear")
           for i, p in enumerate(secs["thesis"][side]) if not res.get(f"{side}{i + 1}", {"supported": True})["supported"]]
    rewritten = False
    if bad:
        secs["thesis"] = thesis.build(fin, calls, secs["ledger"], feedback=bad)
        for k in [k for k in res if k.startswith(("bull", "bear"))]:  # judge the rewrite afresh, not by the draft
            del res[k]
        judged = {k for k in judged if not k.startswith(("bull", "bear"))}
        second, second_judged = judge(secs["thesis"], {"rows": []})
        res.update(second)
        judged |= second_judged
        recheck = "done" if second_judged else "unavailable"
        rewritten = True
    # Last resort, after the one rewrite: a point still claiming an untested / unmet promise was met loses that clause
    # if the rest stands on its own — then the trimmed text is judged again by the verifier and the narrative checks.
    trimmed, trim_recheck = [], None
    if rewritten:
        rows = {f"L{i + 1}": r for i, r in enumerate(secs["ledger"].get("rows", []))}
        for side in ("bull", "bear"):
            for i, p in enumerate(secs["thesis"][side]):
                k = f"{side}{i + 1}"
                if k in res and not res[k]["supported"] and \
                        (cut := narrative.trim_unmet_promise_claim(p["point"], p["refs"], p["evidence"], rows, latest)):
                    p["trimmed_from"] = p["point"]
                    p["point"], p["refs"], p["evidence"] = cut
                    trimmed.append(k)
    if trimmed:
        third, third_judged = judge(secs["thesis"], {"rows": []})
        trim_recheck = "done" if third_judged else "unavailable"
        if third_judged:  # every point judged afresh on its current text
            for k in [k for k in res if k.startswith(("bull", "bear"))]:
                del res[k]
            judged = {k for k in judged if not k.startswith(("bull", "bear"))} | third_judged
            res.update(third)
        else:  # no verifier: trimmed points keep only the narrative re-check, so they end up unchecked (not verified)
            for k in trimmed:
                res.pop(k, None)
                judged.discard(k)
            res.update({k: v for k, v in third.items() if k in trimmed})
    unchecked = 0
    for side in ("bull", "bear"):
        for i, p in enumerate(secs["thesis"][side]):
            r = res.get(f"{side}{i + 1}")
            if r and (not r["supported"] or f"{side}{i + 1}" in judged):
                p["verified"], p["issue"] = r["supported"], r.get("issue") or None
            else:  # no verdict on this text from the verifier: unchecked, never silently "verified"
                p["verified"], p["issue"] = None, None
                unchecked += 1
    for i, row in enumerate(secs["ledger"].get("rows", [])):
        r = res.get(f"L{i + 1}")
        if r:
            row["verified"], row["issue"] = r["supported"], r["issue"] or None
    flagged = sum(1 for p in secs["thesis"]["bull"] + secs["thesis"]["bear"] if p.get("verified") is False) +         sum(1 for r in secs["ledger"].get("rows", []) if r.get("verified") is False)
    status = ("narrative_only" if not first_ran else
              "rewrite_unverified" if "unavailable" in (recheck, trim_recheck) else "done")
    secs["verification"] = {"status": status, "checked": len(res), "flagged": flagged, "unchecked": unchecked,
                            "rewrote_thesis": rewritten, "recheck": recheck, "trimmed": trimmed,
                            "trim_recheck": trim_recheck, "initially_unsupported": bad}


FRESH_FOR = dt.timedelta(hours=24)            # a done / partial memo younger than this is not rebuilt on view
RUNNING_TTL = dt.timedelta(minutes=10)        # a stored "running" state younger than this: a build is in progress
RETRY_AFTER_FAILURE = dt.timedelta(minutes=30)  # after a failed build, wait this long before an automatic retry


def _younger(ts: str | None, limit: dt.timedelta) -> bool:
    """Is this ISO timestamp less than `limit` old? A missing or unreadable timestamp is not young."""
    try:
        return bool(ts) and now() - dt.datetime.fromisoformat(ts) < limit
    except (TypeError, ValueError):
        return False


def _complete(memo: dict | None) -> bool:
    """A finished memo worth keeping: done, with its Promise Ledger."""
    return bool(memo and memo.get("status") == "done" and (memo.get("sections") or {}).get("ledger"))


def _hold(prev: dict | None, force: bool) -> str | None:
    """Why a build must NOT start now, or None. A build already in progress — in this process or, via its stored
    "running" state, in another (deploy overlap, restart) — blocks even an explicit rebuild; freshness and the
    post-failure cooldown only hold back automatic (on-view) rebuilds."""
    if not prev:
        return None
    if prev.get("status") == "running" and _younger(prev.get("started") or prev.get("updated"), RUNNING_TTL):
        return "in_progress"
    if force:
        return None
    if prev.get("status") in ("done", "partial") and _younger(prev.get("updated"), FRESH_FOR):
        return "fresh"
    failed_at = (prev.get("refresh_failed") or {}).get("at") or (prev.get("updated") if prev.get("status") == "error" else None)
    if _younger(failed_at, RETRY_AFTER_FAILURE):
        return "cooling_down"
    return None


def build(sym: str, force: bool = False, previous: dict | None = None) -> dict:
    """Build a memo. If the build does not finish ("partial" / "error") and the company already had a complete memo,
    that memo is kept — marked with refresh_failed — rather than replaced by a broken one. `previous` is the memo as
    it was before start() stored its "running" placeholder."""
    sym = sym.upper().strip()
    prev = previous if previous is not None else get(sym)
    if prev and not force and prev.get("status") in ("done", "partial") and _younger(prev.get("updated"), FRESH_FOR):
        return prev
    state = _build(sym)
    if state.get("status") != "done" and _complete(prev):
        kept = {**prev, "refresh_failed": {"at": now().isoformat(), "status": state.get("status"),
                                           "errors": state.get("errors") or []}}
        kv_set(_key(sym), kept)
        return kept
    return state


def _build(sym: str) -> dict:
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
    _add_results_facts(sym, fin)
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
        save(stage="Cross-checking every claim against its evidence")
        _verify(fin, calls, secs)
        save(status="done", stage="")
    except LLMUnavailable as e:
        save(status="partial", stage="", errors=state["errors"] + [f"AI unavailable: {e}"[:300]])
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        save(status="partial", stage="", errors=state["errors"] + [f"{type(e).__name__}: {e}"[:300]])
    return state


def start(sym: str, force: bool = False) -> dict:
    """Kick off a background build if one is due; return the current state immediately.

    At most one build per company runs at a time (this process: _running; other processes: the stored "running" state).
    Viewing a memo rebuilds it only when it is stale (older than FRESH_FOR) and no failed build was attempted within
    RETRY_AFTER_FAILURE; force=True (the Rebuild button) skips those two, never the one-build-at-a-time rule."""
    sym = sym.upper().strip()
    prev = get(sym)
    with _lock:
        if sym in _running:
            return prev or {"symbol": sym, "status": "running", "stage": "Starting", "sections": {}}
        if _hold(prev, force):
            return prev
        _running.add(sym)

    def run():
        try:
            build(sym, force=True, previous=prev)
        finally:
            with _lock:
                _running.discard(sym)

    # Persist "running" before the thread starts, so a poll that arrives before the build's first save finds a
    # record (not a 404). Earlier sections are kept so a rebuild doesn't blank an existing memo meanwhile.
    stamp = now().isoformat()
    state = {"symbol": sym, "status": "running", "stage": "Starting", "started": stamp, "updated": stamp,
             "sections": (prev or {}).get("sections", {}), "errors": []}
    try:
        kv_set(_key(sym), state)
    except Exception:  # noqa: BLE001 — a failed write must not stop the build; the build saves its own state
        pass
    threading.Thread(target=run, daemon=True).start()
    return state
