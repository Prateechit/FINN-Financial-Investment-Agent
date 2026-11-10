"""Stale-memo refresh safety: opening a memo rebuilds it at most once, only when due, never twice at the same time,
and a failed rebuild never replaces a good memo.

The flow under test: Memo screen → POST /api/research/{symbol} → research.start(). The store (kv), clock and
background thread are replaced here, so nothing touches a database or starts a real build.
"""
import datetime as dt
import threading

import pytest

from finn.pull import research

T0 = dt.datetime(2026, 11, 10, 6, 0, 0)
RealThread = threading.Thread   # research.threading is this module: keep the real class before Env patches it


class Env:
    def __init__(self, monkeypatch, run_builds=True):
        self.store, self.clock, self.builds, self.threads = {}, [T0], [], []
        self.run_builds = run_builds
        monkeypatch.setattr(research, "kv_get", lambda key, *a: self.store.get(key))
        monkeypatch.setattr(research, "kv_set", lambda key, value: self.store.__setitem__(key, value))
        monkeypatch.setattr(research, "now", lambda: self.clock[0])
        monkeypatch.setattr(research, "_running", set())
        env = self

        class FakeThread:
            def __init__(self, target, daemon=None):
                self.target = target
                env.threads.append(self)

            def start(self):
                if env.run_builds:
                    self.target()

        monkeypatch.setattr(research.threading, "Thread", FakeThread)
        self.outcome = "done"
        monkeypatch.setattr(research, "_build", self._fake_build)

    def _fake_build(self, sym):
        self.builds.append(sym)
        state = {"symbol": sym, "status": self.outcome, "stage": "", "started": self.clock[0].isoformat(),
                 "updated": self.clock[0].isoformat(), "errors": [] if self.outcome == "done" else ["AI unavailable: 429"],
                 "sections": {"ledger": {"rows": []}} if self.outcome == "done" else {"snapshot": {}}}
        research.kv_set(research._key(sym), state)
        return state

    def memo(self, sym="DIXON", status="done", age=dt.timedelta(hours=2), **extra):
        ts = (self.clock[0] - age).isoformat()
        self.store[research._key(sym)] = {"symbol": sym, "status": status, "started": ts, "updated": ts, "errors": [],
                                          "sections": {"ledger": {"rows": [{"subject": "kept"}]}} if status == "done" else {}, **extra}
        return self.store[research._key(sym)]

    def later(self, **kw):
        self.clock[0] += dt.timedelta(**kw)


@pytest.fixture
def env(monkeypatch):
    return Env(monkeypatch)


# ---------- fresh / stale ----------

def test_fresh_memo_is_returned_without_a_build(env):
    prev = env.memo(age=dt.timedelta(hours=2))
    assert research.start("DIXON") is prev and env.builds == []


def test_stale_memo_is_rebuilt_once(env):
    env.memo(age=dt.timedelta(hours=30))
    research.start("DIXON")
    assert env.builds == ["DIXON"] and env.store["research:DIXON"]["status"] == "done"


def test_freshness_boundary_is_24_hours(env):
    env.memo(age=dt.timedelta(hours=23, minutes=59))
    research.start("DIXON")
    assert env.builds == []
    env.later(minutes=2)
    research.start("DIXON")
    assert env.builds == ["DIXON"]


def test_unknown_company_is_built(env):
    research.start("NEWCO")
    assert env.builds == ["NEWCO"]


# ---------- repeated views ----------

def test_repeated_views_after_a_rebuild_do_not_rebuild_again(env):
    env.memo(age=dt.timedelta(hours=30))
    for _ in range(10):                      # ordinary navigation and page refreshes
        research.start("DIXON")
        env.later(minutes=1)
    assert env.builds == ["DIXON"]


# ---------- concurrent ----------

def test_concurrent_opens_start_one_build(monkeypatch):
    e = Env(monkeypatch, run_builds=False)   # the first build stays "in progress"
    e.memo(age=dt.timedelta(hours=30))
    results = []
    workers = [RealThread(target=lambda: results.append(research.start("DIXON"))) for _ in range(8)]
    [w.start() for w in workers]
    [w.join() for w in workers]
    assert len(e.threads) == 1 and len(results) == 8
    assert research.start("DIXON", force=True)["status"] == "running" and len(e.threads) == 1   # Rebuild button too


def test_build_running_in_another_process_blocks_even_an_explicit_rebuild(env):
    env.memo(status="running", age=dt.timedelta(minutes=3))      # e.g. the old instance during a deploy overlap
    research.start("DIXON")
    research.start("DIXON", force=True)
    assert env.builds == []


def test_abandoned_running_state_does_not_block_forever(env):
    env.memo(status="running", age=dt.timedelta(minutes=15))     # its process restarted mid-build
    research.start("DIXON")
    assert env.builds == ["DIXON"]


# ---------- failures ----------

def test_failed_rebuild_keeps_the_previous_complete_memo(env):
    prev = env.memo(age=dt.timedelta(hours=30))
    env.outcome = "partial"                                       # e.g. model quota exhausted
    research.start("DIXON")
    kept = env.store["research:DIXON"]
    assert kept["status"] == "done" and kept["sections"] == prev["sections"] and kept["updated"] == prev["updated"]
    assert kept["refresh_failed"] == {"at": T0.isoformat(), "status": "partial", "errors": ["AI unavailable: 429"]}


def test_after_a_failed_rebuild_views_wait_for_the_cooldown(env):
    env.memo(age=dt.timedelta(hours=30))
    env.outcome = "partial"
    research.start("DIXON")
    for _ in range(5):
        env.later(minutes=5)
        research.start("DIXON")
    assert env.builds == ["DIXON"]                                # 25 minutes: no retry yet
    env.outcome = "done"
    env.later(minutes=6)
    research.start("DIXON")
    assert env.builds == ["DIXON", "DIXON"] and "refresh_failed" not in env.store["research:DIXON"]


def test_error_state_is_not_retried_on_every_view(env):
    env.memo(status="error", age=dt.timedelta(minutes=5))
    research.start("DIXON")
    assert env.builds == []
    env.later(minutes=30)
    research.start("DIXON")
    assert env.builds == ["DIXON"]


def test_explicit_rebuild_is_allowed_during_the_cooldown_and_still_keeps_a_good_memo(env):
    env.memo(age=dt.timedelta(hours=30), refresh_failed={"at": T0.isoformat(), "status": "partial", "errors": []})
    env.outcome = "error"
    research.start("DIXON", force=True)
    assert env.builds == ["DIXON"] and env.store["research:DIXON"]["status"] == "done"


def test_failed_first_build_without_a_previous_memo_is_saved_as_is(env):
    env.outcome = "error"
    research.start("NEWCO")
    assert env.store["research:NEWCO"]["status"] == "error" and "refresh_failed" not in env.store["research:NEWCO"]


def test_running_placeholder_is_not_mistaken_for_the_previous_memo(env):
    # start() stores a "running" placeholder before the thread starts; the build must compare with the memo before it
    env.memo(age=dt.timedelta(hours=30))
    env.outcome = "partial"
    research.start("DIXON")
    assert env.store["research:DIXON"]["status"] == "done"


@pytest.mark.parametrize("ts", [None, "", "not-a-date"])
def test_missing_or_bad_timestamps_never_crash(env, ts):
    env.store["research:DIXON"] = {"symbol": "DIXON", "status": "done", "updated": ts, "started": ts, "sections": {}}
    research.start("DIXON")
    assert env.builds == ["DIXON"]
