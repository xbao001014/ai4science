# Design: Ops Weekly Toggle for Abstract→Fulltext Upgrade Re-extract

**Date:** 2026-08-05  
**Status:** Approved (brainstorm)  
**Depends on:** `2026-08-05-abstract-fulltext-upgrade-reextract-design.md`, Gap UI ops weekly job (`ops_panel.py`, `analysis/ops_jobs.py`), `main.py extract`

## Problem

自动全文升级重抽默认开启后，周常 `extract --limit 0` 可能对大量 `skipped_no_ft` + 已补全文论文做完整重抽，周常耗时过长。运维 Tab 需要**按次选择**是否升级，且周常默认应偏向快路径。

## Goals

1. 运维「启动周常更新」表单增加勾选：**升级先前仅摘要文献**，**默认未勾选（关）**。
2. 选择写入 weekly job `params`，经 CLI flag 控制：
   - `extract`：`--no-upgrade-reextract` / `--upgrade-reextract` → `config.FULLTEXT_UPGRADE_REEXTRACT`
   - `fetch-fulltext`：关 → `--no-retry --skip-pdf`；开 → `--pdf-retry-limit N`（表单「Tier2 PDF 上限」，默认 50；0=不限）
3. 单独 CLI `extract` / `fetch-fulltext` 不加 flag 时行为不变。

## Non-goals

- 升级数量上限控件
- 改全局 env 默认值
- 新增周常步骤
- Gap UI 以外的面板重构

## Approach (chosen)

**方案 1：checkbox → `upgrade_abstract_fulltext` param → `--no-upgrade-reextract` / `--upgrade-reextract`。**

Rejected: 仅设子进程 env（argv/日志不透明）。

## UI

In `ops_panel.py` weekly form (alongside SkipEnrich):

- Checkbox label: `升级先前仅摘要文献（冷却重试 + Tier2 PDF + 完整重抽）`
- Default: `False`
- Help: 开启后会重试冷却失败全文并跑 Tier2；默认关闭以加快周常（本周新 pending 仅试 JATS）
- Number input: `Tier2 PDF 上限（勾选升级时生效，0=不限）`，default `50`，disabled when checkbox off

Pass `upgrade_abstract_fulltext=bool(...)` and `pdf_retry_limit=int(...)` into `start_weekly_job` / `create_weekly_job`.

## Job params + argv

- `params["upgrade_abstract_fulltext"]`: bool, default `False` when missing (old status.json safe).
- `params["pdf_retry_limit"]`: int, default `50` when missing.
- `build_weekly_argv("fetch-fulltext", params)`:
  - `False` / missing → `["fetch-fulltext", "--no-retry", "--skip-pdf"]`
  - `True` → `["fetch-fulltext", "--pdf-retry-limit", str(pdf_retry_limit)]`
- `build_weekly_argv("extract", params)`:
  - `False` → `["extract", "--limit", …, "--core-only", "--no-upgrade-reextract"]`
  - `True` → `… "--upgrade-reextract"`
- Mutual exclusion on extract CLI: cannot pass both upgrade flags.

## Extract CLI

`main.py extract`:

- `--upgrade-reextract` → `config.FULLTEXT_UPGRADE_REEXTRACT = True`
- `--no-upgrade-reextract` → `config.FULLTEXT_UPGRADE_REEXTRACT = False`
- Neither → leave config/env as-is (default true)

Set flags in `cmd_extract` before `run_extraction`, same pattern as `--core-only`.

## Testing

- `build_weekly_argv` includes the correct flag for true/false/missing param
- `create_weekly_job` / `start_weekly_job` accept and persist the param
- Optional: argparse mutual exclusion smoke (not required if covered by cmd_extract guard)

## Docs

- `SCRIPTS.md` / `gap_ui_guide.md`: note ops checkbox default off; CLI flags for extract

## Implementation touchpoints

- `fulltext_workflow/ops_panel.py`
- `fulltext_workflow/analysis/ops_jobs.py`
- `fulltext_workflow/main.py`
- `fulltext_workflow/tests/test_ops_jobs.py`
- `SCRIPTS.md`, `gap_ui_guide.md`
