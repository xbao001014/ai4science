# Design: Gap UI Ops Tab — Weekly Job + Clear Ops Memory

**Date:** 2026-08-04  
**Status:** Approved (brainstorm)  
**Depends on:** `run_pipeline.ps1 -Stage weekly`, `main.py` CLI, `scripts/clear_ops_memory.py` / `analysis/ops_memory.py`, `gap_ui.py`

## Problem

周常增量更新（`run_pipeline.ps1 -Stage weekly`）与清空 ops 记忆（`clear_ops_memory.py`）目前只能在终端跑。周更链路长（fetch → … → stats），用户需要：

1. 在 Gap UI 内一键触发周更；
2. 看到**阶段进度 + 可展开日志**；
3. 周更在**后台**运行，期间仍可使用其它 Tab；
4. 安全地清空近期已报空白记忆。

## Goals

1. UI 新增「运维」Tab：周常一键 + 清空 ops 记忆（范围 A）。
2. 周更后台执行；阶段勾选 + 日志尾部；刷新页面可恢复进度。
3. 侧栏显示紧凑「周更」状态，不重复完整表单。
4. 清空记忆需预览 + 二次确认；可选按当前焦点、可选删引用 md。
5. Job 逻辑与 UI 分离，可单测状态机 / 并发拒绝 / 取消。

## Non-goals

- 不把 landscape / import-if / 单阶段流水线 / `clear_database` / `reset_extraction` 放进 UI。
- 不自动跑 `gap-debate` / `idea-pipeline`。
- 不要求与 PowerShell 脚本进程级复用（行为对齐即可，用 Python job runner 调 `main.py`）。
- 不做多用户远程队列；默认单机单 Streamlit 会话场景，全库仅允许 1 个 running weekly job。

## Approach (chosen)

**独立 Python Job Runner + `output/ops_jobs/<job_id>/` 状态文件 + 运维 Tab 轮询**（brainstorm 方案 1）。

Rejected:

- **直接调 `run_pipeline.ps1` 解析 stdout** — 绑 Windows/PS，结构化进度弱。
- **Streamlit 进程内线程跑 `cmd_*`** — 刷新易丢状态，长任务不适合。

## Architecture

```
gap_ui.py (运维 Tab / 侧栏状态)
    │  start / cancel / read status+log
    ▼
analysis/ops_jobs.py
    │  spawn detached: python -m analysis.ops_jobs --run-job <job_id>
    ▼
ops_jobs __main__ runner
    │  for each weekly step:
    │     subprocess: python main.py <cmd> ...
    │     update status.json + append log.txt
    ▼
output/ops_jobs/<job_id>/{status.json, log.txt}
```

Runner 入口固定为 `python -m analysis.ops_jobs --run-job <job_id>`（同一模块 `__main__`），不另增脚本文件。

### Weekly stage sequence

对齐 `run_pipeline.ps1 -Stage weekly`：

| # | step_id | CLI |
|---|---------|-----|
| 1 | fetch | `fetch --since-days N` |
| 2 | enrich-s2 | `enrich-s2`（`skip_enrich` → `skipped`） |
| 3 | fetch-fulltext | `fetch-fulltext` |
| 4 | extract | `extract --limit L --core-only` |
| 5 | compute-gap-lifecycle | `compute-gap-lifecycle` |
| 6 | hotspot-report | `hotspot-report` |
| 7 | hotspot-brief | `hotspot-brief` |
| 8 | stats | `stats` |

（周更不含 `build` / `analyze`；需要时用 `-Stage build` / `-Stage analyze` 或 CLI 单独跑。）

默认参数：`since_days=14`，`extract_limit=0`，`skip_enrich=false`。

### Job status schema (`status.json`)

```json
{
  "job_id": "20260804T141500Z_weekly",
  "kind": "weekly",
  "state": "running",
  "params": {"since_days": 14, "extract_limit": 0, "skip_enrich": false},
  "pid": 12345,
  "started_at": "...",
  "finished_at": null,
  "error": null,
  "steps": [
    {"id": "fetch", "label": "fetch", "status": "succeeded", "started_at": "...", "finished_at": "..."},
    {"id": "enrich-s2", "label": "enrich-s2", "status": "running", "started_at": "...", "finished_at": null}
  ]
}
```

Step / job `status` / `state` 枚举：`pending` | `running` | `succeeded` | `failed` | `skipped` | `cancelled`。取消时：job `state=cancelled`；当时正在跑的那一步 `status=cancelled`；尚未开始的步骤保持 `pending`。

维护 `output/ops_jobs/current.json` 指向活跃/`最近一次` job_id（字段含 `job_id`、`state`）。`start` 前若 `current` 指向仍存活的 `running` job 则拒绝；须保证全库最多一个 running weekly。

## UI

### Ops Tab

1. **周常一键更新**
   - 控件：`SinceDays`、`ExtractLimit`、`SkipEnrich`
   - 「开始周更」：无 running job 时可点
   - 进度条：完成数 / 总步数（`skipped` 计入完成）
   - 阶段列表：pending / running / succeeded / skipped / failed 图标
   - 「运行日志」expander：`log.txt` 尾部约 200 行，随轮询刷新
   - 「取消周更」：仅 running；需勾选「确认取消」
   - 成功提示刷新语料库统计；失败停在出错步并保留日志

2. **清空 ops 记忆**
   - 预览：`ops_runs` / `ops_gap_items` / `ops_proposals` 计数
   - 范围：全部 | 仅当前侧栏焦点（焦点空则禁用「仅焦点」）
   - 可选：同时删除引用 md
   - 勾选「我确认清空」后才可执行
   - 成功后刷新侧栏「近期已报空白」；不动 papers / KG / hotspot

### Sidebar

- 底部一行：`周更：空闲` 或 `周更：进行中 · <当前阶段>`
- 不放完整表单

### Polling

- 运维 Tab 使用 `st.fragment(run_every=2)`（或当前环境等价 API）自动重读 status + 日志尾；另提供「刷新状态」按钮作为兜底。
- 页面刷新后读 `current.json` 恢复展示；若不存在则扫描 `ops_jobs/*/status.json` 取最新 mtime。

## Clear ops memory API

将 `scripts/clear_ops_memory.py` 中的预览/删除核心函数抽到 `analysis/ops_memory.py`（可 import），CLI script 改为薄包装调用；UI 只调该 API，避免两套删除逻辑。

## Concurrency, cancel, zombie detection

- **并发**：存在 `state=running` 的 weekly job 时拒绝 start，UI 禁用按钮并说明。
- **取消**：向 runner / 当前 `main.py` 子进程发送终止（Windows 用进程树终止）；写 `state=cancelled`；未跑步骤保持 `pending`。
- **僵尸**：UI 或 `get_job_status` 发现 status 为 running 但 pid 已不存在 → 标 `failed`，error 注明进程已退出。

## Error handling

- 某步 `main.py` 非 0：job `failed`，记录该步 stderr 摘要；后续不跑。
- 无法创建 job 目录 / 无法 spawn：UI 立即报错，不留半截 running。
- 清空记忆异常：展示错误，不宣称成功。

## Testing

- `ops_jobs` 单元测试（假 subprocess）：状态转移、SkipEnrich→skipped、失败中止、取消写状态、第二 job 被拒、僵尸检测。
- 清空记忆：预览计数与 focus 过滤（可用临时 SQLite）。
- UI 纯函数：步骤状态→展示映射、日志尾部截取；不启完整 Streamlit 跑周更。

## Docs

- `fulltext_workflow/SCRIPTS.md`：运维 Tab 与 CLI 等价说明。
- `fulltext_workflow/gap_ui_guide.md`：运维 Tab 操作（若文件存在；否则仅 SCRIPTS / README 补一句）。

## Implementation sketch (not a plan)

1. `analysis/ops_jobs.py`：create / start / cancel / read / list / reclaim_zombie。
2. Runner 入口：顺序执行 weekly steps，写 status + log。
3. Clear-memory 可 import API。
4. `gap_ui.py`：运维 Tab + 侧栏状态 + 轮询。
5. 测试 + 文档短更新。
