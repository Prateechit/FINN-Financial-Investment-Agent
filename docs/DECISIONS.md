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
