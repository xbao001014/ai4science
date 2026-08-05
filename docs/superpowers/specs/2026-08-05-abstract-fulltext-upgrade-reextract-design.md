# Design: Abstract→Fulltext Auto Re-extract

**Date:** 2026-08-05  
**Status:** Approved (brainstorm)  
**Depends on:** `docs/superpowers/specs/2026-08-04-fulltext-retry-cooldown-design.md`, `clear_paper_kg_extractions`, `run_extraction` / weekly `extract`, Pass 1+2 pipeline

## Problem

补抓冷却重试落地后，摘要阶段抽取的论文会带着 `reconcile_status=skipped_no_ft` 和 `extraction_done=1`。一旦后来拿到 JATS/PDF 全文，普通 `extract` 只处理 `extraction_done=0`，**不会**再跑全文 Pass 1 / Pass 2，KG 永久停在摘要粒度。

现状快照：约 3k+ 篇 `unavailable` + `skipped_no_ft` + 已抽取；全文补齐后需要自动完整重抽。

## Goals

1. 当「曾摘要抽取」的论文变为有全文时，在常规 `extract` 队列中**自动完整重抽**（clear → Pass 1 on fulltext sections → Pass 2 reconcile）。
2. 周常一键无需新步骤：`fetch-fulltext` → `extract` 即可消化升级。
3. **不设升级数量上限**（与用户选择一致）；正数 `--limit` 时升级候选与新 pending **共享**该 limit。
4. 可配置关闭：`FULLTEXT_UPGRADE_REEXTRACT`（默认 `true`）。

## Non-goals

- 仅 Pass 2 reconcile、保留摘要 Pass 1（轻量路径）
- 升级数量硬上限 / 阶梯配额
- 新状态值、新表、`attempt_count`
- Gap UI 表单开关
- 改变 `--pmid-list` 语义（定点列表仍须显式 `--force-reextract` 才 clear）

## Approach (chosen)

**方案 1：`extract` 开始时 deferred clear + 合并进现有队列。**

Rejected:

- **补抓成功立即 clear** — 在 extract 前出现大规模 KG 空窗。
- **新状态 `upgrade_pending`** — schema/查询面过重。

## Eligibility

A paper is an **upgrade candidate** iff all of:

| Field | Value |
|-------|--------|
| `extraction_done` | `1` |
| `reconcile_status` | `skipped_no_ft` |
| `full_text_status` | `available` or `pdf_available` |

Do **not** upgrade: `done` fulltext papers; `skipped_no_ft` still `unavailable`; `extraction_done=0` (already in normal queue).

## Extract flow

Only on the **corpus queue** path of `run_extraction` (no `--pmid-list`):

1. If `FULLTEXT_UPGRADE_REEXTRACT` is false → skip to step 4.
2. Select upgrade candidates ordered by `year DESC, id DESC`.
3. For each candidate: `clear_paper_kg_extractions(pmid)` (deletes relations / bindings / improvement suggestions; sets `extraction_done=0`, `study_type=NULL`, `reconcile_status='pending'`, `reconcile_at=NULL`). **Does not** delete `document_sections`.
4. Call existing `get_papers_for_extraction(limit=...)` — cleared upgrades now appear as pending with fulltext and follow existing priority (fulltext before abstract-only, then `year DESC`).
5. Existing `_process_paper`: fulltext/mineru Pass 1 → Pass 2 → `reconcile_status=done`.

**Limit sharing:** When CLI `--limit` is a positive integer, upgrades and fresh pending share that budget via `get_papers_for_extraction` after clear. Prefer clearing **all** eligible upgrades before the limited select only if that would orphan upgrades behind a small limit forever — **chosen rule:** clear all eligible upgrades first (so they compete fairly in the limited select by existing ORDER BY); papers not selected remain `extraction_done=0` for the next run. When `--limit 0` (weekly), all pending including upgrades are processed.

**Log:** print `upgraded_from_abstract=N` (count cleared this run).

**`--pmid-list`:** unchanged — auto-upgrade does not run; use `--force-reextract` to clear listed PMIDs.

## Weekly / config / docs

- `WEEKLY_STEPS` unchanged: `fetch-fulltext` then `extract --limit 0 --core-only`.
- Config: `FULLTEXT_UPGRADE_REEXTRACT: bool` default `true` (env same name).
- Docs: note in `PIPELINE.md` / `SCRIPTS.md` that abstract-extracted papers auto full-reextract once fulltext exists.

## Testing

Temp DB / mocks (no live LLM):

- `skipped_no_ft` + `available` → cleared; relations gone; `extraction_done=0`
- `skipped_no_ft` + `unavailable` → not cleared
- `done` + `available` → not cleared
- `FULLTEXT_UPGRADE_REEXTRACT=false` → no clear
- With `_process_paper` mocked, upgrade candidates appear in the extract queue after prep

## Implementation touchpoints (expected)

- `fulltext_workflow/config.py` — `FULLTEXT_UPGRADE_REEXTRACT`
- `fulltext_workflow/db/schema.py` — helper to list upgrade candidates (optional but preferred)
- `fulltext_workflow/extractor/section_extractor.py` — prep step in `run_extraction`
- `fulltext_workflow/tests/test_fulltext_upgrade_reextract.py` — new
- `PIPELINE.md` / `SCRIPTS.md` — short notes

## Relation to prior spec

Extends the Future work section of `2026-08-04-fulltext-retry-cooldown-design.md` by choosing the **full** path (force-reextract style) with deferred clear at extract time, uncapped, weekly via existing extract step.
