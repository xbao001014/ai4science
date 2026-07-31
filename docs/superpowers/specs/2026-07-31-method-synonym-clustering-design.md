# Design: Method Synonym Soft Clustering (A+C)

**Date:** 2026-07-31  
**Status:** Approved  
**Depends on:** Weekly hotspot novelty (`2026-07-31-weekly-hotspot-novelty-design.md`), `method_maturity.py`, Task synonym / audit patterns (`entity_normalize`, `task_quality`)

## Problem

周热点在拉长窗口后仍常空「新苗头」：不是没有新方法信号，而是抽取把贡献写成**过度私有化**的 Method 名（长 framework 句、一次性变体）。`HOTSPOT_MIN_RECENT_PAPERS=2` 下，同一概念拆成多个 `recent=1` 行，无法进榜；成熟度过滤再去掉 LLM 等唯一过线项后主榜为空。

向量嵌入聚类（原选项 B）本阶段不做：仓库无现成 embedding，误合并与运维成本更高。

## Goals

1. 分析层 **软映射** `alias → canonical`（不改库内实体行、不重抽）。
2. **A+C：** 字符串/词袋近邻 + 骨架启发，用于**审计候选**；运行时只解析表 + 高置信自动规则。
3. **高置信自动合并 + 其余人审**（方案 1 双轨）。
4. 周热点 / 可迁移方法池按 canonical **聚合计数**，缓解热点离散。
5. 只读审计 CLI，便于补 synonym 表。

## Non-goals

- Embedding / 向量索引。
- 抽取期硬归并或 DB entity rename migration。
- Disease / Task 聚类（Task 已有 synonym + quality）。
- 热点路径内联临时簇且不写表（会与软映射目标不一致）。
- 自动把长私有描述并入 `deep learning` 等伞词。

## Approach (chosen)

**双轨软映射（方案 1）** = 分析层落点（用户选 B）+ 算法 A+C + 合并策略「高置信自动 / 其余人审」。

Rejected: 热点内联临时簇（方案 2）；纯人审无自动（方案 3）；本阶段 embedding。

## Module: `analysis/method_synonyms.py`

### APIs

| Function | Role |
|----------|------|
| `resolve_method_canonical(name: str) -> str` | Runtime entry: norm → curated table → auto rules → identity |
| `load_method_synonyms() -> dict[str, str]` | Curated map (keys/values `_norm_key`) |
| `apply_auto_method_canonical(name: str) -> str` | Deterministic high-confidence rules only |
| `method_skeleton(name: str) -> str` | Strip weak modifiers for audit grouping |
| `near_duplicate_method_candidates(names: list[str], ...) -> list[dict]` | Audit suggestions; **never** auto-writes the table |

### Resolve order

1. `_norm_key(name)`
2. Hit in `_METHOD_SYNONYMS` (curated)
3. `apply_auto_method_canonical`
4. Else return normalized name

### Auto rules (allowed)

1. Whitespace / case via `_norm_key` (always).
2. Safe plural tail only where listed (e.g. explicit `models`→`model` style entries — no naive strip-`s`).
3. Parenthetical collapse when one side is already a known alias in the **established method alias set** (shared with / imported from `method_maturity`) or curated table: e.g. `support vector machine (svm)` → `support vector machine`.
4. Explicit same-form aliases aligned with maturity blacklist (e.g. `llm` → `large language model`).

### Auto rules (forbidden)

- Merge long descriptive phrases onto umbrella skeletons (`deep learning`, `machine learning`, …).
- Fuzzy / Jaccard merges at runtime.
- Cross-backbone merges (`resnet-50` ↛ `resnet-based mil …`) without curated row.

### Curated table storage (v1)

In-module `_METHOD_SYNONYMS: dict[str, str]` (same style as `_TASK_SYNONYMS`). JSON file optional later — not required for v1.

### Interaction with maturity

Always `canonical = resolve_method_canonical(name)` **before** `classify_method_maturity(canonical, count)`. Corpus counts for maturity should be aggregated by canonical when used for board gating (sum distinct PMIDs across aliases — see hotspot wiring).

## Audit CLI

Command: `main.py method-cluster-audit` (read-only).

### Candidate generators

1. **Token Jaccard / rapidfuzz:** ≥2 content tokens shared, or high similarity with comparable length.
2. **Skeleton equality:** after removing weak tokens (`framework`, `model`, `based`, `using`, …) and collapsing whitespace.
3. **Skip:** pairs already mapped; suggestions that would map a long alias onto an established **umbrella** blacklist name; low-signal single-token overlap.

### Output

Rows: `alias`, `suggested_canonical` (prefer shorter + higher corpus frequency), score, reason (`jaccard` / `fuzz` / `skeleton`), optional paper counts.  
Stdout summary + optional `output/method_cluster_audit_{date}.md`.

Human copies accepted rows into `_METHOD_SYNONYMS`.

## Hotspot / transferable wiring

In `compute_emerging_entities` for Method (or a post-pass in `compute_weekly_hotspots`):

1. Resolve each method name to canonical.
2. **Aggregate** window stats by canonical. Prefer merging **distinct PMID sets** for recent/prior when available; if only counts exist, document approximation risk and extend the entity query to retain PMIDs or re-aggregate in SQL with a canonical CASE map for known aliases (v1 practical approach: post-process with pmid lists from a small helper query, or aggregate in Python from per-paper edges for the window).
3. Then apply maturity annotation on canonical rows (corpus counts also by canonical).
4. Continue existing emerging vs active split.

Transferable heat pool uses canonical method names from `active_methods`.

Optional row fields: `alias_count`, `aliases` (top few) for UI expander.

UI caption: methods board notes soft synonym merge. `SCRIPTS.md` documents the audit command.

## Testing

| Area | Cases |
|------|--------|
| Resolve | `llm` → `large language model`; curated alias maps; unmapped private phrase unchanged |
| Auto forbid | Long `… deep learning framework …` does **not** auto-map to `deep learning` |
| Aggregate | Two aliases each recent=1 → canonical recent≥2 can pass `min_recent` if not established |
| Maturity | Alias of blacklisted name still established after resolve |
| Audit | Near-dup suggested; does not mutate synonym table |
| Regression | Hotspot maturity / transferable demotion tests still pass |

## Rollout

1. Land module + resolve + hotspot aggregate + unit tests.
2. Land audit CLI; run on current DB; curate first synonym batch.
3. Re-check 31-day 新苗头 density; tune auto alias list conservatively.
4. Defer embedding to a later phase if string/skeleton coverage plateaus.

## Risks

| Risk | Mitigation |
|------|------------|
| Over-merge via auto rules | Narrow allowlist; forbid umbrella absorption |
| Under-merge → board still sparse | Audit-driven curated table; optional later lower min_recent |
| Count double-count without PMID merge | Prefer distinct PMID aggregation in wiring |
| Drift from extract-time names | Soft map only; full re-extract still independent |

## Open decisions (resolved)

- Layer: analysis soft map (not extract hard merge; not hotspot-only ephemeral).
- Algorithm this phase: A+C; embedding deferred.
- Merge policy: high-confidence auto + human review for the rest.
- Implementation shape: dual-track module + audit CLI + hotspot aggregate (方案 1).
