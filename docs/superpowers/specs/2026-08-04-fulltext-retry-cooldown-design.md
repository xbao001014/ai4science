# Design: Fulltext Retry with Cooldown (Abstract-Only Backfill)

**Date:** 2026-08-04  
**Status:** Approved (brainstorm)  
**Depends on:** `fetcher/fulltext_fetcher.py`, `fetcher/pmc_fetcher.py`, `db/schema.py` (`full_text_status`, `full_text_fetched_at`), weekly ops `WEEKLY_STEPS` / `fetch-fulltext`

## Problem

新文献刚入库时往往还没有 PMC JATS / 可下载 PDF。当前 `fetch-fulltext` 失败后把 `full_text_status` 写成终态 `unavailable`，之后只处理 `pending`，**永不重试**。即使出版社后来上线全文，周常更新也捞不回来，只能摘要抽取（或长期卡在 abstract-only）。

现状（设计时快照）：约 3k+ 篇 `unavailable`；`fetch-fulltext` 无冷却重试路径。

## Goals

1. 冷却期满的 `unavailable` / `jats_unavailable` 在 `fetch-fulltext` 中自动重新入队。
2. **JATS 重试不限量**；**PDF/MinerU 有默认上限**，控制贵路径成本。
3. 周常一键（ops weekly / `-Stage weekly`）无需新步骤即可补抓——仍调用默认 `fetch-fulltext`。
4. 保留手动开关：`--no-retry`（行为与今天一致）、`--force-retry`（忽略冷却）。

## Non-goals

- 摘要已抽取后全文补齐的自动 Pass 2 reconcile / Pass 1 重抽（见 [Future work](#future-work-abstract--fulltext-upgrade)）。
- 阶梯退避、`fulltext_attempt_count` 等新 schema 字段。
- Gap UI 表单暴露冷却天数 / PDF 上限（先走 env / config）。

## Approach (chosen)

**在现有 `fetch-fulltext` 内嵌 retry 入队**（方案 1）。

Rejected:

- **独立 `retry-fulltext` 步骤** — 周常多一步、易漏跑。
- **新状态 `retry_pending` + attempt 计数** — schema/查询面过大，不适配先止血。

## Queue rules

At the start of `fetch_all_fulltext` (retry enabled by default):

1. Select candidates: `full_text_status IN ('unavailable', 'jats_unavailable')` AND (`full_text_fetched_at` IS NULL OR age ≥ `FULLTEXT_RETRY_COOLDOWN_DAYS`, default **7**).
2. Reset those rows to `pending` and set `full_text_fetched_at = now` (marks this attempt).
3. Existing pipeline continues: only `pending` → JATS → `jats_unavailable` → PDF/MinerU → `unavailable`.

Never re-fetch `available` / `pdf_available`. Do not touch `extraction_done` or `reconcile_status` in this change.

`--no-retry`: skip the reset; only process already-`pending` papers.  
`--force-retry`: ignore cooldown; reset all `unavailable` / `jats_unavailable` to `pending` (PDF limit still applies unless limit=0).

## Fetch flow and PDF cap

1. Retry enqueue (above).
2. **Tier 1 JATS**: all current `pending` (new + retried). **No count limit.**
3. **Tier 2 PDF/MinerU**: papers that became `jats_unavailable` this run, truncated by `FULLTEXT_PDF_RETRY_LIMIT` (default **500**; `0` = unlimited). Order: `year DESC`, then `created_at DESC`.
4. Remaining `jats_unavailable` not attempted under the cap: mark `unavailable` and refresh `full_text_fetched_at` (same end state as today; eligible again after cooldown).
5. Summary log fields: `retried_into_pending`, JATS/PDF success counts, `pdf_skipped_by_limit`, final `unavailable` count.

## Config / CLI / weekly

**Config** (`config.py` + env):

| Name | Default | Meaning |
|------|---------|---------|
| `FULLTEXT_RETRY_COOLDOWN_DAYS` | `7` | Min days since `full_text_fetched_at` before re-enqueue |
| `FULLTEXT_PDF_RETRY_LIMIT` | `500` | Max PDF/MinerU attempts per run; `0` = unlimited |

**CLI** (`main.py fetch-fulltext`):

- Default: cooldown retry + PDF limit from config.
- `--no-retry`
- `--force-retry`
- Optional `--pdf-retry-limit N` override (nice-to-have; env alone is acceptable).

**Weekly:** `WEEKLY_STEPS` keeps a single `fetch-fulltext` step. Default argv `["fetch-fulltext"]` inherits retry behavior. No ops UI param panel changes in this iteration.

**Docs:** Note in `PIPELINE.md` / `SCRIPTS.md` that cooled-down `unavailable` papers are retried inside `fetch-fulltext`; JATS uncapped, PDF/MinerU capped.

## Testing

Unit tests (temp DB / mocks; no live PMC):

- Cooldown not met → not reset; cooldown met → reset to `pending`.
- `--no-retry` / `--force-retry` behavior.
- PDF limit: only first N of `jats_unavailable` attempted; remainder → `unavailable` with fresh `full_text_fetched_at`.
- Weekly argv for `fetch-fulltext` unchanged (`["fetch-fulltext"]`).

## Future work: abstract → fulltext upgrade

Out of scope for this spec; sketched so the retry work does not paint into a corner.

Today, abstract-only Pass 1 sets `reconcile_status = skipped_no_ft` and `extraction_done = 1`. After a later fulltext success, normal `extract` will not revisit the paper.

**Recommended follow-on (separate spec):**

1. **Light path (default):** On successful upgrade to `available` / `pdf_available`, if `reconcile_status == 'skipped_no_ft'`, set `reconcile_status = 'pending'`. Existing Pass 2 (`main.py reconcile` / extract’s reconcile hook) upgrades datasets/limitations against new sections without wiping Pass 1.
2. **Full path (optional / capped):** For high-value PMIDs, `--force-reextract` (Pass 1 on full sections + Pass 2).
3. **Weekly:** After `fetch-fulltext`, optionally run reconcile (or capped force-reextract) for papers that transitioned abstract→fulltext this run.

This change only needs to leave hooks clean: do not clear `extraction_done` on retry failure; only future upgrade logic flips `skipped_no_ft` → `pending` on **successful** fulltext store.

## Implementation touchpoints (expected)

- `fulltext_workflow/config.py` — new settings
- `fulltext_workflow/fetcher/fulltext_fetcher.py` — enqueue + PDF limit
- `fulltext_workflow/db/schema.py` — helper(s) to select/reset cooled-down papers if useful
- `fulltext_workflow/main.py` — CLI flags
- `fulltext_workflow/tests/` — new tests
- `PIPELINE.md` / `SCRIPTS.md` — short notes
