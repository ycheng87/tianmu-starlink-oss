# Tianmu Starlink — agricultural price data pipeline

A small, self-hosted data pipeline that collects **daily agricultural wholesale prices** for Yunnan Province, China, and serves them to a WeChat mini-program used by local flower and vegetable growers.

Built and maintained by one person. It runs on a single VPS with cron, no paid APIs, no cloud services.

## Why this exists

Growers in Yunnan sell into wholesale markets (Dounan for flowers, Wangqiying for vegetables). The prices are published — but on provincial government pages that are hard to read on a phone, and impossible to compare over time.

The result is a real information gap: a flower farmer takes a bunch to market without knowing yesterday's price in the same market, let alone last month's trend.

This project closes that gap. It scrapes the public provincial data sources every day, normalises them into SQLite, and exposes a simple "what is the price today, and how does it compare" feed to a mini-program that growers actually use.

**It is deliberately boring.** Zero LLM calls at runtime, no paid dependencies, no clever infrastructure — because it has to keep working unattended on a 2-core box.

## Data sources

All public, all free:

- **Yunnan Provincial Department of Agriculture** — Wangqiying wholesale vegetable prices (~80 commodities)
- **Dounan Flower Market** — cut flower prices (~23 commodities, priced per bunch)
- **HeFeng Weather** — local weather, for the "will this affect tomorrow's harvest" question

No scraped data is redistributed in this repository.

## Architecture

```
cron (daily)
   │
   ├── collect.py          # orchestration: fetch → normalise → store
   ├── dounan_collect.py   # flower market collector
   ├── nync_collect.py     # provincial vegetable collector
   ├── weather.py          # weather snapshot
   │
   ▼
SQLite (prices.db)  ← schema in db_schema.py
   │
   ├── detect.py           # sanity checks: gaps, spikes, stale sources
   ├── weekly_report.py    # weekly digest
   └── server.py           # small HTTP API consumed by the mini-program
```

Design choices worth calling out:

- **Zero-token collection.** Every collector is plain Python + requests. LLM cost at runtime is zero by construction, not by optimisation.
- **Fail loud, not silent.** `detect.py` flags stale sources, impossible price jumps, and missing days; `health_report.sh` writes a machine-readable health file every run.
- **Name normalisation is the hard part.** The same vegetable gets called three different things across sources, so `data/name_aliases.json` carries the mapping and `scripts/clean_names.py` keeps it honest.
- **Backfills are first-class.** Three `backfill_*.py` scripts rebuild history from the same sources when a collector has been down, because a gap in a price series is worse than no data at all.

## What is NOT in this repository

This is the data pipeline, not the product. Deliberately excluded:

- WeChat mini-program credentials (AppID / AppSecret) and cloud configuration
- Any API keys, tokens, or account credentials
- User data of any kind (no accounts, no locations, no identifiers)
- The production database and collected price history
- The production server's own service code

## Status

- **Live since August 2026**, running daily on a single VPS
- **95 commits** over ~2.5 months of active maintenance
- Used by a small group of trial growers in Yunnan

## Running it locally

```bash
pip install requests beautifulsoup4 lxml
python3 db_schema.py            # create an empty database
python3 collect.py              # one collection pass
python3 detect.py               # check what you got for sanity
```

Nothing is required to be configured — the collectors hit public endpoints and write to a local SQLite file.

## License

MIT — see [LICENSE](LICENSE).

---

*Tianmu Starlink (田亩星链) is an independent project. It is not affiliated with the data sources it reads.*
