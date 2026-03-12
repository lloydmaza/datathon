# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python pipeline to scrape, parse, and analyze marathon race results from multiple timing platforms.
Supports 4 races: 2026 LA Marathon, 2025 LA Marathon, 2025 SF Marathon, 2025 Monterey Bay Half Marathon.

## Running the pipeline

```bash
pip install -r requirements.txt

# Unified pipeline CLI (run from repo root)
python src/pipeline.py <race> --fetch --parse   # fetch + parse
python src/pipeline.py <race> --stats            # summary statistics
python src/pipeline.py <race> --stats --bib 1234 # runner profile
python src/pipeline.py <race> --viz              # Dash app at http://127.0.0.1:8050

# Available race keys:
#   la_marathon_2026 | la_marathon_2025 | sf_marathon_2025 | monterey_bay_half_2025

# Ad-hoc per-race scripts (legacy, still functional)
python src/la_marathon_2026/fetch.py
python src/la_marathon_2026/parse.py
python src/la_marathon_2026/stats.py [--bib N]
python src/la_marathon_2026/visualize.py
```

## Architecture

### Directory structure

```
src/
  pipeline.py              ← unified CLI entry point
  core/
    connector.py           ← RaceConnector ABC, RESULTS_COLUMNS, SPLITS_COLUMNS
    normalize.py           ← hhmmss_to_ms, ms_to_hhmmss, parse_name, fmt_time_minutes
    cache.py               ← load_meta, save_meta, archive_cache, fetch_all_with_retry
    stats.py               ← race-agnostic stats functions + run_stats()
    visualize.py           ← race-agnostic Dash app + run_app()
  connectors/
    xacte.py               ← XacteConnector (LA 2025, 2026)
    athlinks.py            ← AthlinkConnector (SF Marathon 2025)
    sve_timing.py          ← SVETimingConnector (Monterey Bay 2025)
  races/
    __init__.py            ← REGISTRY dict
    la_marathon_2026.py    ← LAMarathon2026 (event_id=2626, subevent_id=6584)
    la_marathon_2025.py    ← LAMarathon2025 (event_id=2574, subevent_id=6436)
    sf_marathon_2025.py    ← SFMarathon2025 (event_id=1119286, race_id=2598266)
    monterey_bay_half_2025.py ← MontereyBayHalf2025 (SVE Timing HTML)
  la_marathon_2026/        ← legacy per-race scripts (fetch/parse/stats/visualize)
  la_marathon_2025/
  sf_marathon_2025/
  monterey_bay_half_2025/
data/
  {race_key}/
    pages/                 ← cached raw pages (JSON or HTML)
    pages/meta.json        ← total record count for cache validation
    pages/cacheNNN/        ← archived cache on record count change
    eventconfig.json       ← Xacte only: split labels, finish distance, category names
    metadata.json          ← Athlinks only: division map
    results.csv            ← normalized output (RESULTS_COLUMNS)
    splits.csv             ← Xacte only: long-format splits
```

### Connector system

`RaceConnector` (ABC in `core/connector.py`) defines:
- `fetch()` → calls `_fetch_impl()`, caches raw data to disk
- `parse()` → calls `_parse_impl()`, then `_post_process()`, then `_coerce_schema()`, saves CSV
- `load_results()` → reads results.csv, adds `age_group` column
- `_post_process(df, splits_df)` → override hook for race-specific logic
- `_coerce_schema(df)` → ensures all `RESULTS_COLUMNS` present (None where unavailable)

Properties that vary by race: `has_category`, `has_short_course`.

### Normalized schema (RESULTS_COLUMNS)

`bib, full_name, firstname, lastname, age, sex, city, state, country, overall, oversex, overdiv,
wave_id, external_id, start_time_ms, chiptime_ms, clocktime_ms, chiptime, clocktime,
dq, dnf, short_course, category`

All columns always present; unavailable fields are None. `age_group` is derived on load, not stored.

### Splits CSV (splits.csv)

Long format: `bib | label | distance_m | displayorder | elapsed_ms | delta_ms`
Only produced for Xacte races (LA 2025, 2026).

### Data sources

| Race | Platform | Format | Notes |
|---|---|---|---|
| LA 2026 | Xacte (event 2626, sub 6584) | JSON API | Has splits, categories, waves |
| LA 2025 | Xacte (event 2574, sub 6436) | JSON API | Same schema as 2026 |
| SF 2025 | Athlinks (event 1119286, race 2598266) | JSON API | No splits from main endpoint |
| Monterey Bay 2025 | SVE Timing | HTML scraping | No splits, no category |

### Caching behavior

- Pages cached individually; restarts only fetch missing pages
- If total record count changes, existing cache is archived to `pages/cacheNNN/`
- `httpx.TransportError` triggers a 10s pause + retry of remaining missing pages only
