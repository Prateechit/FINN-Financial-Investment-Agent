# FINN — AI-Assisted Build History

**FINN (Financial Investment Agent)** · ENAM Holdings AI Engineer Build Challenge

This document records how FINN was built: what was built in each phase, which AI tools were used, and which steps were taken by the AI assistant and which by the project owner. Every statement is drawn from the Git history, the GitHub pull-request records, the project's decision log (`docs/DECISIONS.md`) or the Claude Code session transcript. Where the record does not settle a point, the document says so.

| | |
|---|---|
| Build window | 9 – 12 November 2026 |
| Commits on `main` | 35: 23 authored commits and 12 pull-request merges |
| Pull requests | 12 as of 12 November 2026, all merged into `main` by the repository owner |
| Backend tests | 0 → 28 → 112 → 299 → **347** (collected at each milestone; see [§6](#6-testing-milestones)) |
| AI coding tool | Claude Code, running the Claude Opus 5.5 model |
| Production | Vercel (frontend) · Render (API) · Neon Postgres (database) · GitHub Actions (scheduled ingest) |

Commit times are IST (UTC+5:30), as Git records them. Production and server events are UTC, as the FINN API reports them.

---

## 1. AI tools used

| Tool | Role | Evidence |
|---|---|---|
| **Claude Code**, Anthropic's coding agent, run in the VS Code extension | Wrote the code, tests, scripts and documentation; ran tests, audits and read-only production checks; prepared commits and branches | Session `c363bd54-6dbf-4695-9f84-97a9ce39aca0`, exported in redacted form to `docs/ai-history/` by `scripts/export_history_redacted.py`. All **23 of 23** authored commits carry `Co-Authored-By: Claude Opus 5.5`. PRs #10–#12 end with "Generated with Claude Code". |
| **Claude Opus 5.5** (`claude-opus-5-5`) | The model behind every assistant turn in the session | The session transcript records `claude-opus-5-5` on all 2,551 assistant messages. |

**No other AI coding tool** (for example Copilot, Cursor, ChatGPT or Codex) is named anywhere in the repository or the session record, so none is claimed here.

**Models inside the product are separate.** FINN itself calls the free tiers of **Google Gemini** and **Groq** (`gpt-oss-120b`, `gpt-oss-20b`, `qwen3.8-27b`) at runtime, with **Ollama** (`gemma3:4b`) as a local development fallback. These are components of the product, not tools used to build it (`backend/finn/llm.py`, `docs/DECISIONS.md`).

---

## 2. Who did what

The session record shows a consistent division of work. The project owner set direction and constraints, controlled anything outward-facing, and merged every PR. The assistant implemented, tested, verified and reported, and asked for approval before any production action.

| Activity | Project owner | Claude Code (AI) |
|---|---|---|
| Product brief and scope | Wrote the opening brief (Push and Pull workflows, 15–20 stock portfolio, ENAM requirements) and approved the proposed plan | Proposed the architecture and plan; ran the data-source checks (`spikes/`) |
| Implementation | Set constraints in each request (for example "Do not push or deploy", "Do not rebuild any memo", "Do not expose secrets") | Wrote all application code, tests, scripts and documentation |
| Hosting accounts and secrets | Set up the Vercel, Render and Neon services; entered secrets in the Render dashboard and in GitHub Actions; confirmed deployments from the Render dashboard | Wrote the deploy configuration (`render.yaml`, `vercel.json`) and the migration script; checked deployments with read-only requests only |
| Pushes to `main` | Gave explicit instructions for each early push to `main` and for the fast-forward of `edc3910` ("I approve merging commit `edc3910` … into `main`") | Ran those pushes. After that, pushed feature branches only |
| Pull requests | Opened PRs #1–#9 on GitHub; **reviewed and merged all 12** | Opened PRs #10–#12 with the `gh` CLI. **Merged no PR.** Its only merge in the session record is the approved fast-forward of `edc3910`, before the PR workflow began |
| Code review | Asked for reviews at set points (for example "read-only code review of PR #1") and chose which findings to fix | Carried out the requested reviews and reported findings before changing code |
| Production memo rebuilds | **Approved each rebuild individually**, usually as "exactly one POST", after confirming the deployed commit | Sent exactly the approved request, polled with GET only, never retried, and reported the outcome, including failures |
| Ingestion workflow | Configured the GitHub secrets; triggered the manual run (#3) | Diagnosed the problem read-only (missing secrets; scheduled runs delayed or dropped); verified the effect with GET requests |
| Decisions on remaining issues | Chose what to fix and what to leave (for example kept one known verifier quirk unchanged) | Reported what remained open, with evidence |

The record does not show how much time the owner spent reviewing each PR on GitHub. It shows only that every merge was made from the owner's account (`mergedBy: Prateechit`) and that the assistant never ran a merge.

---

## 3. Development timeline

### Phase 0 — Data-source checks (9 Nov)
The first files written were seven small scripts, kept in `spikes/`, which tested each candidate source before any design was fixed. Results are in `docs/DECISIONS.md`:
- **Prices:** yfinance as the primary source, with the NSE bhavcopy as fallback.
- **Announcements:** NSE corporate announcements as the primary source, with BSE as fallback.
- **Results:** NSE Integrated Filing XBRL for current results, because the older XBRL endpoint ends in Dec 2024.
- **Financials and documents:** screener.in for statements and for discovering transcripts.
- **Transcripts:** a test transcript was about 16k tokens, so a whole transcript fits in one model call and the Promise Ledger needs no retrieval step (no RAG).

### Phase 1 — Core system (9 Nov, 18:03–18:33 IST)
| Commit | What was built |
|---|---|
| `f84abb6` | Push pipeline: NSE, screener and yfinance sources; XBRL results engine; rule-based classifier; explainable materiality scoring |
| `b48f912` | Pull pipeline: deterministic financials, quote-verified guidance extraction, Promise Ledger, bull/bear thesis; FastAPI layer; story clustering; penalty-vs-revenue materiality |
| `f93bd55` | Mobile PWA frontend (Brief, Alerts, Research memo, Portfolio, Company); deploy configuration; evidence guards; AI-history export |

**Decisions recorded at this point:**
- the AI models never produce numbers: every figure comes from code;
- every quote must be found verbatim on its cited page;
- everything is cached by content hash;
- a static Vite + React PWA was chosen over Next.js.

### Phase 2 — Validation on real companies with real models (9 Nov, 19:12–20:18 IST)
| Commit | What changed, and what found it |
|---|---|
| `55d3f72` | **First live run, on DIXON.** It exposed lenient verdicts (FY26 capex of ₹1,058 Cr called "delivered" against a ₹1,100–1,200 Cr guide). A deterministic range check now overrides such verdicts. Also added: free-tier model routing and fallback, and new margin and profit signals. |
| `284a5df` | **Second company, HDFC Bank.** Added a lender fact table and a "no proxy metric" guard (NIM cannot be judged from PAT margin). FY24 merger growth is now labelled as a step-change. First smoke test and **28 unit tests**. |
| `7da34e0` | **Groq added.** Introduced the second-model claim verifier, which triggers one rewrite. A speaker-turn check now drops guidance spoken by analysts, and a horizon guard stops "missed" verdicts on open promises. |

**Result recorded in the decision log:** DIXON 52/52 and HDFC Bank 28/28 guidance quotes verbatim, and 6/6 thesis points grounded for each company.

### Phase 3 — Deployment and fiscal-period correctness (9 Nov 22:21 – 10 Nov 01:37 IST)
| Commit | What changed |
|---|---|
| `9932c08` | Moved from SQLite to Neon Postgres; batched price queries. The owner then deployed the API on Render and the PWA on Vercel. |
| `d6088ce` | Company names now resolve to NSE tickers before research starts; fixed a stale search on Enter. |
| `d00f648` | **Fiscal-period alignment:** each promise is judged on figures from the period it is about (Indian fiscal year, Apr–Mar). Tests: 31 → **112**. |
| `edc3910` | Quarterly margin comparisons now use exact margins rather than screener's rounded OPM % (16.03% vs 15.72%, where rounding showed 16% vs 16%). Fast-forwarded into `main` with the owner's written approval. Tests: **131**. |

### Phase 4 — Narrative accountability, through reviewed PRs (10 Nov)
From here on, every change went through a feature branch and a PR merged by the owner. Each fix came from a finding in a real production memo, mostly TATATECH and HDFCBANK.

| PR | Merge | What it fixed | Tests at merge |
|---|---|---|---|
| #1 | `016a6d6` | Thesis and credibility wording made consistent with fiscal-period evidence; second-pass verification recorded. Two review findings were fixed before merge. | 169 |
| #2 | `5332283` | QoQ and YoY growth figures accepted as comparison evidence (removed a false positive) | 188 |
| #3 | `d41ad7e` | Margin promises get their base-quarter figure; promise-period labels fixed. The findings of a code review were fixed before merge. | 225 |
| #4 | `3408129` | Unmet-promise claims repaired, verifier evidence aligned, and **stale-memo refresh made safe**: at most one build at a time, a cooldown after failures, and a failed rebuild never replaces a good memo | 258 |
| #5 | `d253e69` | Flags cross-series trends, and "failed" claims about promises that were not missed | 281 |
| #6 | `e16d84b` | Deterministic repairs: move a cross-series trend onto one series; give a mislabelled period its real label | 299 |

Between these PRs, the owner approved individual production rebuilds of TATATECH and HDFCBANK. Each rebuild was then audited read-only. The final TATATECH memo (built `2026-11-10T07:29:57`) passed the period audit with 0 failing rows and had 16/16 quotes verbatim.

### Phase 5 — Submission documentation and UI polish (10 Nov)
| PR | Merge | Change |
|---|---|---|
| #7 | `4b05547` | README rewritten for the challenge: problem, architecture, setup, API, testing, limitations |
| #8 | `b5abf82` | Screenshot gallery, captured by the owner from the live app (read-only navigation) |
| #9 | `8110c48` | Failed research memos hidden from the Research list |

### Phase 6 — Operational reliability (10 Nov)
These were read-only diagnoses, with no code change:
- **Scheduled ingestion.** Only 2 scheduled runs had happened, and production data had not changed. The likely cause, confirmed once the secrets were set, was that the Actions secrets were missing and the CLI fell back silently to a throwaway SQLite database. The owner configured the secrets and triggered manual run #3. Production announcements then went from **170 to 173**. Delayed or dropped scheduled runs were also documented.
- **Prices.** After ingestion, the latest close was still 9 Nov. The NSE holiday calendar showed **10 Nov was a trading holiday** (Diwali-Balipratipada), so this was expected, not an ingestion fault.

### Phase 7 — End-to-end QA loop on HDFCBANK (10–12 Nov)
Each production rebuild, approved one at a time, was audited. Each defect it exposed got its own PR.

| Step | Outcome |
|---|---|
| Rebuild (18:51 UTC) | **Failed:** `TypeError` in the series check. The previous memo was kept, as designed. |
| **PR #10** (`96e7cc8`) | Fixed the sort key that crashed when one metric was cited both as a level and as a growth rate. Tests **302**. |
| Rebuild (19:07 UTC) | Succeeded (`19:10:18`). Audit: bull 2 quoted "above 25%", which is not a reported figure, and the ledger shrank from 7 rows to 4. |
| **PR #11** (`5729d7e`) | Ungrounded points now go to rewrite and repair. **Quotes spanning transcript page breaks now verify** (31 of 31 page breaks were previously unmatchable because of running headers). Malformed model output no longer drops a whole transcript. Each rejected quote is recorded with a reason. Tests **325**. |
| Rebuild (19:30 UTC) | Succeeded (`19:34:16`). A quote across a page break was recovered in production. The new rejection records showed **7 management quotes wrongly credited to analysts**. Bull 2 claimed 5.6% "outpaced" 20.0% and cited an uncited ₹20,700 Cr. |
| **PR #12** (`6575cc4`, merged 12 Nov 02:26 IST) | Inline speaker labels recognised (all 7 now credited to management); comparison-direction check; every number must be in the point's **own** cited evidence; the validator re-checks this independently. Tests **347**. |

Offline replay of the PR #12 checks on 48 thesis points (DIXON, TATATECH, three HDFCBANK snapshots and the test fixtures) flagged only the two known-bad points.

---

## 4. Key engineering decisions

| Decision | Why | Where |
|---|---|---|
| The AI models never produce figures; prose cites fact IDs, and any number not found in the cited evidence is rejected | Investment prose must stay accountable to reported numbers | `grounding.py`, `narrative.py`, `thesis.py` |
| Guidance quotes must appear verbatim on the cited transcript page (after normalisation) | A promise FINN cannot quote cannot be held to account | `sources/docs.py`, `pull/transcripts.py` |
| Deterministic guards override model verdicts: range checks, metric match, fiscal period, horizon, exact margins | Model judgements were measurably lenient in live runs | `pull/ledger.py`, `pull/periods.py` |
| A second model verifies claims; failing points get one rewrite and then a deterministic repair; anything still failing is shown as disputed, never hidden | Numeric grounding cannot catch wrong reasoning ("5.6% outpacing 20.0%") | `pull/verify.py`, `pull/research.py` |
| Indian fiscal calendar built into the code (FY26 = Apr 2025 – Mar 2026) | Fixed several ledger verdicts that were judged against the wrong quarter | `pull/periods.py` |
| Free-tier model routing by task tier (fast, long, reason, verify), with quota-aware benching and a cache walked in quality order | Zero-cost operation within strict free-tier limits | `llm.py` |
| Rule-based classification first (90.7% of 11,450 filings with no model call) | Cost, speed and explainability | `push/classify.py`, `docs/DECISIONS.md` |
| Safe memo refresh: a single build lock, a 24-hour freshness window, a 30-minute cooldown after failures, and a good memo is never overwritten by a failed rebuild | Opening a memo can trigger a rebuild; failures must stay harmless | `pull/research.py` |

---

## 5. How production changes were controlled

The working rules, set by the owner and recorded in the session, were:
- secrets are never shown, printed or committed;
- the Neon schema is not changed and production data is not deleted;
- every production write, meaning a memo rebuild, needs **separate explicit approval** and is sent **once, with no retry**;
- the deployed commit is confirmed before a rebuild. When the assistant could not confirm a Render deploy (on 10 Nov), it stopped and asked rather than sending the request;
- all verification uses read-only GET requests;
- failures are reported as they are. The failed rebuild at 18:51 UTC, for example, was reported with its exact error and not retried.

---

## 6. Testing milestones

Counts come from `pytest --collect-only` run on each listed commit's tree (`git archive`). Results in PR descriptions and the session record show the full suite passing at each merge from PR #10 onwards.

| Commit | Milestone | Backend tests |
|---|---|---|
| `284a5df` | First unit tests (deterministic guards) | 28 |
| `7da34e0` | Groq and claim verifier | 30 |
| `9932c08` | Neon migration | 31 |
| `d00f648` | Fiscal-period alignment | 112 |
| `edc3910` | Exact margins | 131 |
| `016a6d6` | PR #1 | 169 |
| `5332283` | PR #2 | 188 |
| `d41ad7e` | PR #3 | 225 |
| `3408129` | PR #4 | 258 |
| `d253e69` | PR #5 | 281 |
| `e16d84b` | PR #6 (unchanged through PR #9) | 299 |
| `96e7cc8` | PR #10 | 302 |
| `5729d7e` | PR #11 | 325 |
| `6575cc4` | PR #12, current `main` | **347** |

**Other quality tooling:**
- `scripts/audit_periods.py`: read-only fiscal-period and margin audit through the API.
- `scripts/validate_memo.py`: independent re-check of quotes, ledger numbers and thesis grounding.
- `scripts/smoke_test.py`: end-to-end endpoint checks.
- `scripts/eval_results.py`: checks of the results engine across the portfolio.

---

## 7. Open items when this document was compiled (12 Nov 2026)

- **The HDFCBANK memo in production** is still the 19:34 UTC build from 10 Nov: bull 2 is disputed, and 7 management quotes are rejected. The PR #12 fixes reach it only after deployment and one approved rebuild; neither has been checked since the merge.
- **The README's HDFCBANK screenshot** comes from a 9 Nov build; its caption now says so. A replacement waits for an approved rebuild with the PR #12 code. (The README's test count, ingestion limitation and build section, and a FINN-specific `frontend/README.md`, were updated in a documentation pass on 12 Nov.)
- **Housekeeping:** a stray, unreferenced `docs/screens$1.png` (a full-length Portfolio screenshot), and 9 other screenshots in `docs/screens/` that the README does not use.
- **The AI-history export** in `docs/ai-history/` now covers the whole session up to this document, in two redacted Markdown files with no gap or overlap: 9 Nov 12:07 → 15:37 UTC (966 conversation records) and 9 Nov 15:38 → 12 Nov 21:19 UTC (1,832). Each has a `.redaction-report.json`. They contain prompts, replies, tool calls and truncated tool results. They do **not** contain the model's private reasoning, harness metadata, images, or the output of commands that touched a `.env` file. Credentials, account identifiers, email addresses, local paths and usernames are redacted by `scripts/export_history_redacted.py`, and an independent leak review of both files found nothing. The first, partial export (committed in `9932c08`) was removed from the repository tree when these replaced it; it remains in the Git history of earlier commits.
- **The decision log** (`docs/DECISIONS.md`) ends on 9 Nov. Later decisions are recorded in the PR descriptions and commit messages.

---

## 8. How this document was compiled

All sources are read-only:
- `git log` of `origin/main`, with the `Co-Authored-By` trailer of every commit;
- GitHub pull-request metadata (`gh pr list` and `gh pr view`: authors, `mergedBy`, timestamps, descriptions);
- `pytest --collect-only` on exported trees of each milestone commit;
- `docs/DECISIONS.md` and the README;
- the Claude Code session transcript (`c363bd54-…`), used for model identity, approvals and what was run. In the record, the assistant merged no pull request and ran no deploy command (deploys follow automatically from pushes to `main`). It pushed to `main` only during the initial setup and deployment steps the owner asked for, and fast-forwarded `edc3910` once with written approval.

No application code, commit, push, merge, deployment or production API call was made in compiling this document.
