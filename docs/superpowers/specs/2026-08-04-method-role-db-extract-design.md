# Design: Persist Method Role in DB + Extract Hints

**Date:** 2026-08-04  
**Status:** Approved  
**Depends on:** Method role display (`2026-08-04-method-role-hotspot-display-design.md`), `entities.access_class` / Triple `access_hint` pattern, `analysis/method_role.py`, extractor prompts (`study_prompts/shared.py`)

## Problem

周热点已按运行时 `method_role` 分段，但：

1. 角色未落库，无法被抽取下游、审计或跨进程复用。
2. 仅 `backbone` / `aggregator` / `unknown` 时，语料中大量传统 ML、工具/组学方法堆在「未分类」（审计约 70%+ unknown）。
3. 抽取 prompt 未引导模型区分方法架构角色，新入库 Method 仍无结构化角色信号。

## Goals

1. Method 实体持久化 `method_role`（五值）。
2. **规则主写库**：扩展规则分类器；批量回填现有 Method；新抽取可选 LLM hint，仅在规则为 `unknown` 时采纳合法 hint。
3. 抽取 prompt / Triple 契约增加 `method_role_hint`（对齐 Dataset `access_hint`）。
4. 周热点 UI 按五段展示；优先读库列，缺则回退 `classify_method_role`。
5. **不改** `emerging_score`、成熟度闸门、同义词归并、Top-N、可迁移评分公式。

## Non-goals

- 不建独立 `method_role_annotations` 表；不在 relation 行上存角色。
- 不强制全库重抽（回填即可）。
- 不新增 `framework` / `explainability` / `omics` 等更细档（可后续从 `tool` / `unknown` 再拆）。
- 不按角色拆独立 Top-N 榜。

## Approach (chosen)

**方案 1 — `entities.method_role` + 规则回填 CLI + prompt hint（规则覆盖）**

否决：独立注解表（过重）；角色挂 relation（同名冲突、主榜难聚合）。

## Role vocabulary

| Value | Meaning | Examples |
|-------|---------|----------|
| `backbone` | Feature / vision / segmentation backbone or encoder | ResNet, UNI, Hover-Net, SegFormer, DINOv2 |
| `aggregator` | MIL / pooling / fusion / contribution-level aggregation head | ABMIL, TransMIL, attention pooling |
| `classical_ml` | Classical ML / statistical / survival models | RF, SVM, XGBoost, Cox, LightGBM, logistic regression |
| `tool` | Software, platform, omics/pipeline tools (not a net backbone) | QuPath, Seurat, GSVA, VOSviewer, CiteSpace |
| `unknown` | Unmatched or ambiguous | `combined model`, vague compounds |

## Storage

- Column: `entities.method_role TEXT` (nullable).
- Used only when `type = 'Method'`.
- Migration: same pattern as `access_class` — `PRAGMA table_info` then `ALTER TABLE entities ADD COLUMN method_role TEXT` if missing.
- Index (optional v1): none required; Method count is modest. Add later if audits scan often.

### `upsert_entity`

Extend signature with `method_role: str | None = None` (Method-only).

**Insert:** store `resolve_method_role(name, llm_role=method_role)`.

**Update when entity exists:**

```
new = resolve_method_role(name, llm_role=method_role)
if new != "unknown" and new != current:
    UPDATE method_role = new
# if new == unknown: do not clear an existing non-null role
```

## Classification module

File: `fulltext_workflow/analysis/method_role.py` (extend existing).

### API

- `classify_method_role(name: str) -> MethodRole` — rules only; canonical via `resolve_method_canonical` then `_norm_key`.
- `resolve_method_role(name: str, llm_role: str | None = None) -> MethodRole` — merge policy below.
- `annotate_method_role(rows, *, name_key="name", role_by_name: dict[str, str] | None = None)` — if `role_by_name` provided (or loaded from DB), prefer non-empty DB value; else `classify_method_role`.
- `load_method_roles() -> dict[str, str]` — `name → method_role` for `type=Method` where column non-null (optional helper for hotspot).

### Decision order (rules)

First match wins:

1. Aggregator aliases  
2. Backbone aliases  
3. Classical_ml aliases  
4. Tool aliases  
5. Aggregator heuristics  
6. Backbone heuristics  
7. Classical_ml heuristics  
8. Tool heuristics  
9. `unknown`

Conflict across alias tables: earlier step wins (aggregator before backbone before classical_ml before tool). Document in module comment.

### Seed expansions (v1)

- **Backbone aliases/patterns:** keep current; add missings such as `hover-net`, `segformer`, `dinov2`, `googlenet`, `cnn`, `convolutional neural network`, `xception`, `prov-gigapath`, `uni foundation model`, `squeezenet`, etc.
- **Aggregator:** keep MIL / pooling / fusion cues; keep acronym aliases (`abmil`, `clam`, `dsmil`, `transmil`).
- **Classical_ml:** RF, SVM, logistic/lasso/elastic net, XGBoost/LightGBM/CatBoost, decision tree, KNN, PCA, Cox / Kaplan–Meier family, naive Bayes, GBM, etc. (exact aliases + conservative patterns).
- **Tool:** QuPath, Seurat, GSVA, limma, CIBERSORT, CellChat, VOSviewer, CiteSpace, WGCNA, ssGSEA / GSEA-style tool names as exact aliases where stable.

Avoid bare `\battention\b` as aggregator; avoid naive “any `cnn` substring” beyond intended aliases/patterns already scoped.

### Merge policy

```
rule = classify_method_role(name)
if rule != "unknown":
    return rule
hint = normalize(llm_role)  # must be one of the five values
if hint in VALID_ROLES:
    return hint
return "unknown"
```

## Backfill

CLI: e.g. `main.py backfill-method-roles`

- Ensure schema migration applied.
- For each `entities` row with `type='Method'`: set `method_role = classify_method_role(name)` (rules only; overwrite for replayability).
- Print counts per role + unknown rate.
- Document in `SCRIPTS.md`.

Optional: keep/extend `scripts/audit_method_role.py` for coverage checks after dictionary edits.

## Extraction

### Triple model

Add optional field on `Triple` (mirror `access_hint`):

```python
method_role_hint: Optional[Literal[
    "backbone", "aggregator", "classical_ml", "tool", "unknown"
]] = None
```

Validator: case-normalize; invalid → `None`. Meaningful only when `object.type == "Method"`.

### Prompts

Update Method naming policy in `study_prompts/shared.py` (and sync GRANULARITY if needed):

- When emitting Method objects (APPLIES_METHOD / COMPARES_METHOD), set `method_role_hint` when confident.
- Short definitions for the four actionable roles + `unknown`.
- Do not invent Methods solely to fill a role; existing low-value / umbrella filters unchanged.

### Ingest

On Method upsert paths (reconcile / section ingest that call `upsert_entity` for Method):

```python
upsert_entity(canon, "Method", method_role=triple.method_role_hint)
```

`upsert_entity` applies `resolve_method_role` internally (or caller passes already-resolved value — prefer resolve inside upsert for one choke point).

## Weekly hotspot + UI

- After building method-bearing rows, annotate roles preferring DB map (`load_method_roles`) then rule fallback.
- `_METHOD_ROLE_SECTIONS` in `gap_ui.py`:

  1. 基座 / 骨干 (`backbone`)  
  2. 聚合器 / 贡献模块 (`aggregator`)  
  3. 传统 ML (`classical_ml`)  
  4. 工具 / 平台 (`tool`)  
  5. 未分类 (`unknown`) — hide if empty  

- Caption: five roles; rules authoritative; LLM hint only fills rule-unknown; does not affect heat scores.

## Testing / acceptance

1. Unit: five-way `classify_method_role`; `resolve_method_role` (rule wins; hint fills unknown; invalid hint ignored).
2. Schema: column present after migrate; backfill sets roles; counts show non-trivial `classical_ml` / `tool`.
3. upsert: rule-labeled name not overwritten by wrong hint; unknown rule + good hint persists hint; unknown+unknown does not wipe existing DB role.
4. Hotspot/UI: sections render five buckets; scores/maturity unchanged.
5. Prompt/contract: Triple accepts `method_role_hint`; coerce invalid.

## Risks

- Residual `unknown` for novel named modules — dictionary maintenance + LLM hint.
- Mis-file classical vs tool (e.g. some “pipeline” names) — prefer aliases; adjust from audit.
- Global one role per Method name (`UNIQUE(name,type)`) — accepted.

## Out of scope follow-ups

- Finer roles (`explainability`, `omics`).
- Snapshot persistence of role for WoW-by-role.
- LLM-as-primary authority.
