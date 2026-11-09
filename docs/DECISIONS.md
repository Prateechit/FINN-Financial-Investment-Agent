# FINN — data findings & decision log

A running record of what we verified, what we chose, and why. Dates are IST.

## 2026-11-09 — Day-1 data checks (scripts in `spikes/`)

| # | Source | Result | Decision |
|---|---|---|---|
| s1 | yfinance `.NS` EOD | Works: same-day close + volume for all 19 tickers | Primary price source |
| s1 | NSE bhavcopy (`BhavCopy_NSE_CM_…csv.zip`) | Works, full-market daily file | Fallback price source |
| s2 | BSE `AnnSubCategoryGetData` | Works per scrip code; returns `CATEGORYNAME` + `SUBCATNAME` | Fallback announcement source |
| s2 | NSE `corporate-announcements` | Works after a cookie handshake from a residential IP; returns `desc` (≈40 distinct exchange categories), the attachment PDF URL and a summary sentence | **Primary announcement source** |
| s3 | NSE `corporates-financial-results` XBRL | Ends Dec-2024 — SEBI moved results to Integrated Filing | Used only for pre-2025 quarters |
| s4/5 | NSE `integrated-filing-results` XBRL | Current quarter + YTD, exact rupee values, both Ind-AS and banking taxonomies | **Primary source for the results card** |
| s3 | screener.in company page (no login) | 13 quarters, 12 yrs P&L/BS/CF, working-capital ratios, AR + concall transcript links (BSE-hosted PDFs) | Pull-side financials + document discovery; cross-check for results |
| s4 | BSE transcript PDF via PyMuPDF | Text layer present: 24 pages / ~16k tokens for DIXON Q2 FY27 | Whole-document extraction fits in one context window → no RAG needed for the ledger |
| s6 | 19-ticker portfolio | All resolve on all three sources | Portfolio confirmed |

### Notable findings
- **Sources lag each other.** On 9 Nov, screener still showed Jun-2026 for HAL and IRCTC while NSE XBRL had Sep-2026; for INFY it was the reverse. The results card therefore uses XBRL first, falls back to screener, and shows which one it used.
- **Banks use a different taxonomy** (`InterestEarned`, `OperatingProfitBeforeProvisionAndContingencies`, …). EBITDA does not apply; bank cards show NII / pre-provision operating profit / provisions / PAT instead.
- **EBITDA is never reported directly.** We compute it as `Revenue from ops − (Total expenses − Finance costs − D&A)`, which excludes other income. This matches screener's "Operating Profit", so the two sources can be cross-checked.
- **Cloud IP risk:** NSE sits behind Akamai bot protection. Ingestion is designed to run wherever NSE answers (laptop or CI) and write to the shared database, so the hosted API never depends on scraping NSE live.

## Architecture decisions
- **Frontend: Vite + React + TypeScript (static PWA on Vercel)** instead of Next.js. All data comes from the API, so server rendering adds nothing; a static bundle has fewer deploy failure modes.
- **LLM layer is provider-agnostic** (OpenAI-compatible chat API). Routing by task tier:
  - `rules` (free): exchange category → our category for most filings.
  - `fast` (Groq free tier / Gemini Flash-Lite): ambiguous classification, one-line "why it matters".
  - `long` (Gemini Flash, large context): one-time structured extraction per transcript / filing PDF, cached by content hash.
  - `reason` (best available): Promise Ledger verdicts and bull/bear over *extracted JSON*, not raw documents.
  - Ollama (`gemma3:4b`, local) as the offline dev fallback.
- **The LLM never produces numbers.** Figures come from XBRL/screener tables computed in code. LLM prose cites fact IDs; a validator rejects any number not in the fact table, and any quote not found verbatim (after whitespace normalisation) on the cited page.
- **Cache everything by content hash**: PDFs, page text, extractions, LLM responses. Every LLM call is logged to `llm_ledger` (tokens, latency, cache hit) and shown in the app.

## 2026-11-09 — Build-day findings

- **Rules first:** on 11,450 market-wide filings, exchange category + keyword rules classify 90.7% without an LLM. Keyword rules see only the filing's head (subject + opening paragraph); whole-document matching misfired ("customer acquisition" → M&A, "disruptive" → operational disruption).
- **Positive score adjustments do not stack** (one strong reason escalates); negative ones do. Stacking pushed a routine news clarification to 100.
- **Penalty sizing:** litigation filings that state a penalty are scored against annual revenue — Bharti Airtel's four DoT notices (₹1–54 lakh) fold automatically.
- **Results engine:** 19/19 portfolio companies pass PBT − tax ≈ PAT; 18/19 agree with a second source. HDFC Bank's ₹837 Cr PAT gap equals the gap between segment PBT and reported PBT — a screener aggregation difference; FINN shows the exchange figure and flags the disagreement.
- **Local model test (gemma3 4B):** plumbing works end to end, and it shows why the validators exist — the small model labelled historical results as guidance and marked future-dated capacity promises "delivered". Added: a forward-looking-language filter on guidance, an evidence requirement for verdicts, ref recovery from prose, and a fix to the number parser ("INR48873" was read as 8873).
- **Prompting:** for long documents the instructions are repeated after the document ("sandwich"); small models otherwise return `{}`.
- **Never cache an empty LLM answer** — a cached `{}` silently poisoned retries.

## 2026-11-09 — First real-model run (DIXON, Gemini free tier)

- **Model availability ≠ model list.** `gemini-2.5-flash(-lite)` return 404 for new keys; `pro` has no free quota; `3.7/3.8-flash` and `flash-latest` timed out on every call. Working: `gemini-3.5-flash` (long + reason), `gemini-3.5-flash-lite` (fast, last-resort reason). Router now benches 404s for a day, quota-429s for 10 min, timeouts for 15 min, and retries 503 overloads with back-off.
- **Robustness bugs found by the real run:** a valid JSON object followed by extra text was rejected (now `raw_decode`); an empty `.env` value overrode defaults; `max_tokens` must cover "thinking" tokens on 3.x models.
- **Quality review of the ledger, and the fixes it drove:**
  - The model called FY26 capex "delivered" at ₹1,058 Cr against a ₹1,100–1,200 Cr guide → strictness rule in the prompt **plus a deterministic range check** that overrides lenient verdicts (only for ended horizons, or rate targets mid-horizon — a first version wrongly downgraded a 3–4-year level target).
  - It skipped open margin promises while margins were falling → coverage rule; "moving against an open promise" = at_risk. The margin-expansion row is now the memo's central finding.
  - Bull/bear presented an analyst's question as fact → analyst claims must be attributed.
  - A Q2 PAT −45% on revenue +47% was not in the computed signals → added latest-quarter profit/revenue divergence and YoY margin signals.
  - Business-segment figures are now number-checked against the transcript (clauses with unverifiable figures are dropped).
- **Result:** 54/54 guidance quotes verbatim on the cited page (6 are elided "…" quotes, both halves present); 7/7 ledger rows and 6/6 thesis points pass number grounding; a rebuild from cache takes 4 s with 0 tokens.
