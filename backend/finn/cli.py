"""python -m finn.cli <command>

  init                 create tables + load portfolio.json
  prices               update EOD prices for the portfolio
  ingest [days]        fetch, classify, score and enrich announcements (default 2 days)
  enrich               retry pending / un-enriched material announcements
  research SYMBOL      build (or refresh) the research memo for any NSE symbol
  all [days]           prices + ingest — what the scheduler runs
"""
import json
import sys

from .db import init_db


def main(argv: list[str]):
    cmd = argv[0] if argv else "all"
    init_db()
    from .push import ingest
    if cmd == "init":
        print(ingest.load_portfolio())
    elif cmd == "prices":
        print(ingest.ingest_prices())
    elif cmd == "ingest":
        print(json.dumps(ingest.ingest_announcements(int(argv[1]) if len(argv) > 1 else 2), indent=1))
    elif cmd == "reprocess":
        print(ingest.reprocess(use_llm="--no-llm" not in argv), ingest.enrich_pending())
    elif cmd == "enrich":
        print(ingest.enrich_pending())
    elif cmd == "research":
        from .pull import research
        for sym in argv[1:]:
            r = research.build(sym.upper(), force="--force" in argv)
            print(sym, r.get("status"), [k for k, v in r.get("sections", {}).items() if v])
    elif cmd == "all":
        ingest.load_portfolio()
        print(ingest.ingest_prices())
        print(json.dumps(ingest.ingest_announcements(int(argv[1]) if len(argv) > 1 else 2), indent=1))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
