"""Company name → NSE ticker resolution, and the research routes that depend on it.

Runs offline against a snapshot of NSE's equity list (tests/nse_equity_list.json) — the same file production downloads.
"""
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from finn import api
from finn.pull import research
from finn.sources import symbols

HERE = pathlib.Path(__file__).parent
ROWS = json.loads((HERE / "nse_equity_list.json").read_text(encoding="utf-8"))
PORTFOLIO = [h["symbol"] for h in json.loads((HERE.parent / "portfolio.json").read_text())["holdings"]]


# ---------- pure resolver ----------

@pytest.mark.parametrize("typed", ["Tata Technologies", "TATA TECHNOLOGIES", "tata technologies ltd",
                                   "Tata Technologies Limited", "  Tata  Technologies  "])
def test_tata_technologies_name_resolves_to_tatatech(typed):
    res = symbols.resolve(typed, ROWS)
    assert res["symbol"] == "TATATECH"
    assert res["matched_by"] == "name"


def test_ticker_resolves_to_itself():
    assert symbols.resolve("tatatech", ROWS) == {"symbol": "TATATECH", "matched_by": "symbol", "suggestions": []}


@pytest.mark.parametrize("sym", PORTFOLIO)
def test_every_portfolio_symbol_still_resolves_to_itself(sym):
    assert symbols.resolve(sym, ROWS)["symbol"] == sym


def test_unmatched_company_name_is_not_resolved():
    res = symbols.resolve("Nonexistent Widgets Corporation", ROWS)
    assert res == {"symbol": None, "matched_by": None, "suggestions": []}


def test_ambiguous_name_is_not_guessed_but_offers_suggestions():
    res = symbols.resolve("Tata", ROWS)
    assert res["symbol"] is None
    assert 1 < len(res["suggestions"]) <= 5 and all("TATA" in s["name"].upper() or "TATA" in s["symbol"] for s in res["suggestions"])


def test_search_ranking_unchanged():
    hits = symbols.search_rows("tata technologies", ROWS)
    assert hits[0]["symbol"] == "TATATECH"
    assert [h["symbol"] for h in symbols.search_rows("DIXON", ROWS)][0] == "DIXON"  # prefix match first
    assert len(symbols.search_rows("TATA", ROWS)) == 12  # capped


def test_normalize_name():
    assert symbols.normalize_name("Tata Technologies Ltd.") == "TATA TECHNOLOGIES"
    assert symbols.normalize_name("Mahindra & Mahindra Limited") == "MAHINDRA AND MAHINDRA"


# ---------- research routes (no network, no database writes, no build) ----------

@pytest.fixture
def client(monkeypatch):
    started, read = [], []
    monkeypatch.setattr(api, "_equity_list", lambda: ROWS)
    monkeypatch.setattr(research, "start", lambda sym, force=False: started.append(sym) or {"symbol": sym, "status": "running", "sections": {}})
    monkeypatch.setattr(research, "get", lambda sym: read.append(sym) or ({"symbol": sym, "status": "done", "sections": {}} if sym == "TATATECH" else None))
    c = TestClient(api.app)
    c.started, c.read = started, read
    return c


def test_post_research_by_company_name_starts_tatatech(client):
    r = client.post("/api/research/Tata%20Technologies")
    assert r.status_code == 200
    assert client.started == ["TATATECH"]
    assert r.json()["symbol"] == "TATATECH" and r.json()["resolved_from"] == "Tata Technologies"


def test_post_research_unmatched_name_returns_clear_error_and_starts_nothing(client):
    r = client.post("/api/research/Nonexistent%20Widgets%20Corporation").json()
    assert client.started == []
    assert r["status"] == "error" and "No NSE-listed company matches" in r["errors"][0]


def test_post_research_ambiguous_name_suggests_and_starts_nothing(client):
    r = client.post("/api/research/Tata").json()
    assert client.started == [] and r["status"] == "error"
    assert "Did you mean" in r["errors"][0] and r["suggestions"]


def test_get_research_by_company_name_reads_the_resolved_memo(client):
    r = client.get("/api/research/Tata%20Technologies")
    assert r.status_code == 200 and r.json()["symbol"] == "TATATECH"
    assert client.read[0] == "TATATECH"


def test_post_research_portfolio_symbol_unchanged(client):
    r = client.post("/api/research/DIXON").json()
    assert client.started == ["DIXON"] and "resolved_from" not in r


def test_list_unavailable_still_accepts_tickers_but_not_names(monkeypatch, client):
    def down():
        raise RuntimeError("NSE unreachable")
    monkeypatch.setattr(api, "_equity_list", down)
    assert client.post("/api/research/HDFCBANK").json()["symbol"] == "HDFCBANK"
    assert client.started == ["HDFCBANK"]
    r = client.post("/api/research/Tata%20Technologies").json()
    assert r["status"] == "error" and client.started == ["HDFCBANK"]


# ---------- running state is saved before the background build ----------

def test_running_state_is_saved_before_the_thread_starts(monkeypatch):
    events = []
    monkeypatch.setattr(research, "get", lambda sym: None)
    monkeypatch.setattr(research, "kv_set", lambda key, value: events.append(("saved", key, value["status"])))

    class FakeThread:
        def __init__(self, target, daemon):
            pass

        def start(self):
            events.append(("thread started",))

    monkeypatch.setattr(research.threading, "Thread", FakeThread)
    research._running.discard("TATATECH")
    out = research.start("TATATECH")
    research._running.discard("TATATECH")
    assert events == [("saved", "research:TATATECH", "running"), ("thread started",)]
    assert out["status"] == "running" and out["started"] == out["updated"]
