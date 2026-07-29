# Design: Weekly hotspot time axis → `pub_date`

**Date:** 2026-07-24  
**Status:** Implemented  
**Depends on:** `papers.date_precision` (see `2026-07-24-date-precision-design.md`)

## Decision

Weekly hotspot windows use **publication date** (`papers.pub_date`), not local ingest (`created_at`).

## Eligibility (折中)

- Main boards: `date_precision IN ('day', 'month')`
- Excluded from main boards: `year` / `unknown` (counted in `papers_excluded_low_precision` for transparency)

## Payload fields

- `time_axis`: `"pub_date"`
- `eligible_precision`: `["day", "month"]`
- `papers_in_window`: count in publication window
- `papers_ingested`: same value (legacy persist column name)
- `papers_excluded_low_precision`: in-window but low precision

## UI

Gap UI caption and metrics refer to publication window / 窗口内发表; slider labeled 发表窗口（天）.
