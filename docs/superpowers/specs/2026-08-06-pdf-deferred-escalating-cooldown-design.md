# Design: PDF Deferred Queue + Attempt-Prioritized Cap + Escalating Cooldown

**Date:** 2026-08-06  
**Status:** Approved (brainstorm)  
**Supersedes (partial):** cooldown finalize behavior in `2026-08-04-fulltext-retry-cooldown-design.md` § Fetch flow step 4  
**Depends on:** `fetcher/fulltext_fetcher.py`, `db.schema.requeue_cooled_fulltext_failures`, weekly `fetch-fulltext`

## Problem

PDF/MinerU 有每轮上限（默认 500）。当前实现把**因上限未尝试**的 `jats_unavailable` 一律打成 `unavailable` 并刷新 `full_text_fetched_at`，与「真的 PDF 失败」混同，导致大量文献空等 7 天冷却且从未试过 PDF。另：PDF 队列按新年优先，老文/从未试过的更难排到。

## Goals

1. **未试 PDF ≠ 失败**：上限跳过的保持 `jats_unavailable`，下轮直接进 PDF，不进冷却。
2. **从未试过优先**：用 `fulltext_pdf_attempts` 排序（升序），再 `year DESC`。
3. **真失败才冷却**，且按 PDF 尝试次数递增：`7 → 14 → 28 → 56` 天（封顶 56）。
4. 冷却重入队**只**针对 `unavailable`（不再把 `jats_unavailable` 重置为 `pending`）。
5. 一次性纠正存量：误标的「`unavailable` 且 attempts=0」改回 `jats_unavailable`。

## Non-goals

- 改变默认 `FULLTEXT_PDF_RETRY_LIMIT=500`
- 新运维 UI 勾选
- 阶梯退避以外的复杂调度（多队列、公平加权等）

## Status semantics

| Status | Meaning |
|--------|---------|
| `pending` | 待 JATS |
| `available` / `pdf_available` | 已有全文 |
| `jats_unavailable` | JATS 失败，**尚未完成本轮 PDF 尝试**（含上限暂缓） |
| `unavailable` | PDF **已尝试且失败**（无 DOI / 下载失败 / MinerU 失败） |

## Schema

Add column (migrate via existing ALTER pattern in `schema.py`):

- `papers.fulltext_pdf_attempts INTEGER DEFAULT 0`

Increment **only** when a paper is selected into the PDF/MinerU attempt loop (before download). Limit-skipped papers do **not** increment.

## Fetch flow (revised)

1. **Requeue** cooled `unavailable` → `pending` (escalating days; see below). **Do not** requeue `jats_unavailable`.
2. **Tier 1 JATS**: all `pending` (uncapped).
3. **Tier 2 PDF/MinerU**: all current `jats_unavailable`, ordered by  
   `fulltext_pdf_attempts ASC, year IS NULL, year DESC, created_at DESC`,  
   truncated by `FULLTEXT_PDF_RETRY_LIMIT` (`0` = unlimited).
4. For each PDF attempt: `fulltext_pdf_attempts += 1`; on failure → `unavailable` (+ refresh `full_text_fetched_at`); on success → `pdf_available`.
5. **Do not** bulk-finalize remaining `jats_unavailable` to `unavailable`. They remain queued for the next run’s PDF tier.
6. Log: `retried_into_pending`, `pdf_attempted`, `pdf_ok`, `pdf_deferred` (= remaining `jats_unavailable` count), corpus totals.

## Escalating cooldown

Only for rows with `full_text_status='unavailable'`.

Let `a = fulltext_pdf_attempts` (treat `a < 1` as `1` for cooldown length):

| attempts | cooldown days |
|----------|---------------|
| 1 | 7 |
| 2 | 14 |
| 3 | 28 |
| ≥4 | 56 |

Formula: `min(56, 7 * 2**(max(a, 1) - 1))`.

Eligible when `full_text_fetched_at` is NULL or age ≥ that paper’s cooldown days.

`--force-retry`: ignore cooldown; still only reset `unavailable` → `pending` (not `jats_unavailable`), unless product later wants force to also flush deferred — **this spec: force_retry only affects `unavailable`**.

`--no-retry`: skip requeue entirely.

## One-shot backlog repair

On migrate / first use of the column (or explicit helper called from `fetch_all_fulltext` once / always-safe idempotent UPDATE):

```sql
UPDATE papers
SET full_text_status='jats_unavailable'
WHERE full_text_status='unavailable'
  AND COALESCE(fulltext_pdf_attempts, 0)=0
  AND pmid IS NOT NULL;
```

Rationale: never incremented attempts ⇒ never truly PDF-attempted under new rules (includes prior limit-skipped mis-marks).

## Config

Reuse:

- `FULLTEXT_RETRY_COOLDOWN_DAYS` — **base** unit stays 7; escalating schedule is fixed as above (document that base is the step-1 value; do not require new env for the geometric series unless needed later).
- `FULLTEXT_PDF_RETRY_LIMIT` — unchanged default 500.

Optional (YAGNI unless coding convenience): hardcode schedule in code with comment referencing this spec.

## Testing

Temp DB / mocks:

- Limit skip leaves status `jats_unavailable`, attempts unchanged.
- PDF failure → `unavailable`, attempts incremented.
- PDF queue order: attempts=0 before attempts>0; then year DESC.
- Requeue: `jats_unavailable` never reset; `unavailable` respects escalating days by attempts.
- Backlog repair UPDATE moves attempts=0 unavailable → jats_unavailable.
- `--force-retry` requeues cooled/uncosted unavailable regardless of days.

## Docs

Update `PIPELINE.md` / `SCRIPTS.md` and amend note in prior cooldown design (or point to this spec as the authoritative finalize/cooldown rules).

## Implementation touchpoints

- `fulltext_workflow/db/schema.py` — column migrate; `requeue_cooled_fulltext_failures` only `unavailable` + per-row/SQL escalating predicate; backlog repair helper
- `fulltext_workflow/fetcher/fulltext_fetcher.py` — PDF order; increment attempts; remove bulk finalize-to-unavailable; stats `pdf_deferred`
- `fulltext_workflow/tests/test_fulltext_retry.py` — extend / replace outdated “remainder → unavailable” cases
- `PIPELINE.md` / `SCRIPTS.md`
