# Design: Weekly Hotspot Novelty + Contextual Transfer

**Date:** 2026-07-31  
**Status:** Approved  
**Depends on:** Weekly hotspot (`analysis/weekly_hotspot.py`), transferable gaps (`2026-07-29-transferable-gap-task-quality-design.md`), entity normalize (`extractor/entity_normalize.py`)

## Problem

「每周热点」方法主榜与可迁移候选仍把 `large language model`、`support vector machine` 等成熟骨架排在前列。根因是 `emerging_score` 只看近窗相对前窗增速与引用，**不区分方法在领域/语料中的成熟度**。可迁移模块只约束 Task 桥与稀疏共现，无法纠正「主榜实体本身不够新」。

日常科研扫榜需要：

1. **新苗头（A）** — 历史少见、本窗升温的方法，而不是 LLM/SVM。
2. **情境新意（C）** — 允许旧方法 × 新病种/新任务交叉，但须标注并降权。

## Goals

1. 方法主榜默认只展示非 `established` 方法（新苗头）。
2. 成熟度 = **可维护黑名单 + 语料历史频次**（本库首现年份信号弱，不作主依据）。
3. 可迁移候选仍可含 `established` 方法，但降权并标注 `method_maturity`；加情境新意加分。
4. UI 提供折叠「本周活跃（含成熟方法）」以免误解数据缺失。
5. 报告 / LLM 简报文案与上述语义一致。

## Non-goals

- 不改抽取 prompt；不强制全库重抽。
- 不改 Task 质量 / synonym 规则。
- 不回退笛卡尔积空洞作主信号。
- 不做 UMLS/MeSH 外部成熟度。
- 不重建整套三信号 UI 架构（采用方案 1：闸门 + 情境分）。

## Approach (chosen)

**方案 1 — 主榜闸门 + 交叉情境分**（否决：单一惩罚分榜、三信号大重建）。

## Method maturity

Module: `fulltext_workflow/analysis/method_maturity.py`（纯函数，供 weekly hotspot / 可迁移共用）。

### Tiers

| Tier | Rule (first match wins; blacklist before frequency) | 新苗头主榜 | 可迁移 / 热门组合 |
|------|------------------------------------------------------|------------|-------------------|
| `established` | ① 命中成熟方法表；或 ② 全库 `APPLIES_METHOD` + `status=active` 历史 distinct PMID ≥ `HOTSPOT_ESTABLISHED_MIN_PAPERS`（默认 **10**） | 默认不出 | 可出；降权 + 标注 |
| `emerging` | 非 established，且 `corpus_paper_cnt` ∈ [3, 9] | 出 | 正常 |
| `nascent` | 非 established，且 `corpus_paper_cnt` ≤ 2 | 出（优先） | 正常 / 略加分 |

### Established method table (v1)

Normalized whole-string / common aliases, including:

- Umbrellas already in `_GENERIC_METHODS` (e.g. `deep learning`, `machine learning`, `radiomics`, …) — import or re-export to avoid drift.
- Classic baselines / skeletons (whole-string / explicit aliases only): `large language model`, `large language models`, `llm`, `svm`, `support vector machine`, `cnn`, `random forest`, `logistic regression`, `xgboost`, `resnet`, `resnet-50`, `resnet50`, etc.

Do **not** use naive substring matching (e.g. do not treat every name containing `cnn` as established). Niche named models stay off the table unless explicitly aliased.

Config: `HOTSPOT_ESTABLISHED_MIN_PAPERS` (env, default 10). Blacklist extendable in-module constants.

### Outputs per method row

- `method_maturity`
- `corpus_paper_cnt`
- Optional: `maturity_reason` (`blacklist` | `corpus_frequency`) for debug/caption — nice-to-have, not required in v1 UI.

## Scoring and candidate pools

### Method main board (新苗头)

- Keep existing `emerging_score(recent, prior, cite, cpy, if)`.
- After enrichment, **filter out** `method_maturity == established` before Top-N cut for `emerging_methods`.
- Emit parallel list `active_methods`: same window stats **without** established filter (for折叠区 / 调试).

### Transferable opportunities

Keep existing gates: sparse combo (≤2 co-occurrence), transfer prior (method used on ≥1 other disease), ok Task bridge.

**Candidate pool (union):**

1. 新苗头 methods (post-filter emerging board, or equivalent maturity ≠ established with window heat) × heating diseases.
2. `established` methods that still have window activity × heating diseases, with contextual novelty (sparse combo already required); method should show activity on other diseases in-corpus (existing support-diseases gate).

**Score:**

```
opportunity_score =
  emerging_score(method)          # may use active-window stats for established; can be 0
  + literature_gap_points
  + bridge_bonus                  # same_paper / cross_paper (existing)
  + context_novelty_bonus         # co-occ 0 → +1.5; ≤2 → +0.5; optional +0.5 if combo first appears in recent window
  + actionability_bump            # existing
  − maturity_penalty              # established → 2.0; else 0
  + nascent_bonus                 # nascent → +0.5; else 0
```

Sort key: `(-opportunity_score, established last)`.

Row fields added: `method_maturity`, and either expose `context_novelty_bonus` / `maturity_penalty` or fold into documented score components in tool description.

### Hot combos

- Keep nascent/heating phase logic.
- Add `method_maturity`; when sorting for default UI/report, prefer non-established ahead of established at equal score (or caption that mature-method combos are included but ranked lower).

### Explicitly unchanged

- No Cartesian `method_disease_combo_gap` as transferable source.
- Disease board heating logic unchanged in v1 (maturity is Method-focused).

## UI (`gap_ui.py`)

- Methods tab: title/caption **新苗头方法**; note that established are filtered.
- Collapsible **本周活跃（含成熟方法）** under same tab using `active_methods`.
- Top metric「热门方法」→ first 新苗头 name, else「—」.
- Transferable tab: columns `method_maturity` (+ optional novelty/penalty fields); caption that established are demoted.
- Hot combos: show `method_maturity`.

## Report / LLM brief

- Markdown method section = 新苗头; short appendix Top-5 established actives.
- Brief system prompt: do not call established methods “emerging hotspots”; contextual transfers OK if labeled mature + novel context.

## Testing

| Area | Cases |
|------|--------|
| Maturity | LLM / SVM → established (blacklist and/or frequency); rare non-blacklist → nascent/emerging |
| Main board | Established absent from `emerging_methods`; present in `active_methods` |
| Transferable | Established × hot disease + ok bridge + sparse → listed with demoted score vs nascent peer; `method_maturity=established` |
| Regression | Cartesian-only fixtures still absent; Task-bridge rules intact |

Use in-memory / temp DB patterns from `test_weekly_hotspot*.py` / `test_transferable_opportunities.py`.

## Rollout

1. Land `method_maturity` + weekly hotspot / opportunity wiring + unit tests.
2. Refresh UI hotspot tab; confirm LLM/SVM leave 新苗头 and only appear in 本周活跃 / demoted transferable.
3. Tune blacklist / `HOTSPOT_ESTABLISHED_MIN_PAPERS` from real board review (no re-extract required).

## Risks

| Risk | Mitigation |
|------|------------|
| Corpus frequency marks useful mid-tier tools established | Threshold 10 tuned to current corpus; blacklist is primary for LLM-class terms with low count |
| 新苗头 board empty in sparse windows | Caption + 本周活跃折叠; empty preferred over false “emerging” |
| Blacklist over-matching substrings | Whole-string / alias match after normalize; avoid naive substring |
| Score constants feel arbitrary | Document transparently; env overrides for penalty/bonus |

## Open decisions (resolved)

- Research focus: A+C (新苗头 + 情境新意).
- Established in transferable: demote + label (not drop, not full-weight).
- Maturity: blacklist + corpus frequency (not year-age primary).
- Approach: 方案 1.
