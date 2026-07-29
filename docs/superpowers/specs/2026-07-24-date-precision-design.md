# Design: `papers.date_precision`

**Date:** 2026-07-24  
**Status:** Approved  
**Scope:** Persist PubMed publication-date granularity. Weekly hotspot time-axis change is out of scope.

## Goal

Store whether `pub_date` came from day-, month-, or year-level PubMed `PubDate` fields, so later weekly hotspot windows can exclude low-confidence dates without relying on `*-01-01` heuristics.

## Schema

- Column: `papers.date_precision TEXT`
- Values: `day` | `month` | `year` | `unknown`
- Migration: `_migrate_db` `ALTER TABLE` if missing
- Existing rows: `NULL` until backfill

## Parsing

`fetcher/pubmed_fetcher._parse_date` returns `(pub_date, year, precision)`:

| PubMed fields | precision | `pub_date` |
|---|---|---|
| Year + Month + Day | `day` | `YYYY-MM-DD` |
| Year + Month | `month` | `YYYY-MM-01` |
| Year only | `year` | `YYYY-01-01` |
| MedlineDate / unusable | `unknown` (or `month`/`year` if reliably extracted) | best-effort ISO |
| No PubDate | `unknown` | `""`, year `0` |

Display defaults (`01` for missing month/day) are unchanged.

## Upsert

- INSERT writes `date_precision`.
- UPDATE: if existing `date_precision` is NULL/empty, fill from this parse (also refresh `pub_date`/`year`). Do not overwrite a non-empty precision.

## Backfill

CLI `backfill-date-precision`: batch-fetch PubMed XML by PMID for rows where `date_precision IS NULL`, update date triple. Rate-limited like fetch.

## Tests

Unit tests for `_parse_date` covering day / month / year / missing PubDate / MedlineDate.

## Non-goals

- Changing `weekly_hotspot` window from `created_at`
- UI copy changes
- Heuristic labeling of existing `*-01-01` without re-fetch
