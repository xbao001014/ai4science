# Study-Type Prompt Packs & Policy Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Specialize classify + Pass 1 + Pass 2 extraction by `study_type` using composable prompt packs and an enforceable policy matrix, including four new relations (`SURVEYS_METHOD`, `COVERS_DISEASE`, `RELEASES_DATASET`, `PRETRAINS_ON`).

**Architecture:** Keep Pass 1 section extraction and Pass 2 reconcile. Add `study_prompts/` (shared core + eight packs) and `study_policy.apply_policy()`. Wire policy after relation repair in `postprocess_triples` and again before Pass 2 DB writes. Extend `RelationLiteral` and minimal downstream whitelist/stats.

**Tech Stack:** Python 3, SQLite, existing `llm_client.llm_call_structured`, pytest under `fulltext_workflow/`.

**Spec:** `docs/superpowers/specs/2026-07-28-study-type-prompt-policy-design.md`

## Global Constraints

- Do not rewrite gap combo / hotspot scoring; Method heat stays `APPLIES_METHOD`-only (`SURVEYS_METHOD` excluded).
- Remap rules apply **only** to `review` / `meta_analysis`.
- `dataset_mode=none` strips `USES_DATASET`, `RELEASES_DATASET`, and `PRETRAINS_ON`.
- Review disease remap: `TARGETS_DISEASE`→`COVERS_DISEASE` only when `evidence_quote` is non-empty; else drop.
- Do not auto-remap `USES_DATASET`→`RELEASES_DATASET`.
- Meta self-analysis `USES_DATASET` exception: Pass 2 explicit keep only; Pass 1 stays `none`.
- Pack type-specific text budget ~400–600 tokens per pack (excluding shared core).
- Run pytest from `fulltext_workflow/` (tests add that root to `sys.path`).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave working tree dirty and note the suggested commit message.
- Do not commit secrets; do not change PubMed query groups.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/extractor/triple_models.py` | Add four relations to `RelationLiteral` |
| `fulltext_workflow/extractor/study_policy.py` | **New** — matrix + `apply_policy` + `dataset_mode` helpers |
| `fulltext_workflow/extractor/study_prompts/__init__.py` | **New** — `build_section_system`, `build_reconcile_system`, pack registry |
| `fulltext_workflow/extractor/study_prompts/shared.py` | **New** — shared section core + shared reconcile core |
| `fulltext_workflow/extractor/study_prompts/packs.py` | **New** — eight `StudyTypePack` definitions |
| `fulltext_workflow/extractor/entity_normalize.py` | Register new relation↔object maps; call `apply_policy`; remove hard-coded review dataset drop |
| `fulltext_workflow/extractor/section_extractor.py` | Use `build_section_system`; save new dataset relations with access resolution |
| `fulltext_workflow/extractor/study_classifier.py` | Scholar-lens decision hints |
| `fulltext_workflow/extractor/fulltext_reconcile.py` | Type reconcile prompt; `datasets[].role`; survey/cover persist; policy on clear |
| `fulltext_workflow/config.py` | `STUDY_POLICY_ENABLED` (default `true`) |
| `fulltext_workflow/graph/kg_builder.py` | Edge attribute / colors for new relations if applicable |
| `fulltext_workflow/analysis/gap_tools.py` | Read-only `tool_study_type_relation_stats` |
| `fulltext_workflow/idea_agent.py` | One-line note: survey ≠ applied; release ≠ cited-only |
| `fulltext_workflow/tests/test_study_policy.py` | **New** |
| `fulltext_workflow/tests/test_study_prompts.py` | **New** |
| `fulltext_workflow/tests/test_entity_normalize.py` | Update review dataset tests to go through policy |
| `fulltext_workflow/tests/test_fulltext_reconcile.py` | Role + survey/cover + policy clear |
| `fulltext_workflow/tests/test_study_classifier_prompt.py` | **New** — prompt contains lens keywords (no live LLM) |
| `fulltext_workflow/docs/pilot_study_type_qa.md` | **New** — stratified pilot QA checklist |

---

### Task 1: Extend `RelationLiteral` and object-type maps

**Files:**
- Modify: `fulltext_workflow/extractor/triple_models.py`
- Modify: `fulltext_workflow/extractor/entity_normalize.py` (`_RELATION_EXPECTED_OBJECT` only in this task)
- Test: `fulltext_workflow/tests/test_study_policy.py` (create; start with parse tests)

**Interfaces:**
- Produces: `RelationLiteral` includes `SURVEYS_METHOD`, `COVERS_DISEASE`, `RELEASES_DATASET`, `PRETRAINS_ON`
- Produces: `_RELATION_EXPECTED_OBJECT` entries for those four (Method / Disease / Dataset / Dataset)

- [ ] **Step 1: Write the failing test**

Create `fulltext_workflow/tests/test_study_policy.py`:

```python
from extractor.triple_models import Triple


def test_new_relations_parse_on_triple():
    for rel, otype in (
        ("SURVEYS_METHOD", "Method"),
        ("COVERS_DISEASE", "Disease"),
        ("RELEASES_DATASET", "Dataset"),
        ("PRETRAINS_ON", "Dataset"),
    ):
        t = Triple.model_validate(
            {
                "subject": {"name": "paper", "type": "Method"},
                "relation": rel,
                "object": {"name": "x", "type": otype},
                "evidence_quote": "quoted",
            }
        )
        assert t.relation == rel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd fulltext_workflow; python -m pytest tests/test_study_policy.py::test_new_relations_parse_on_triple -v`

Expected: FAIL (validation error — relation not in Literal).

- [ ] **Step 3: Extend models + expected-object map**

In `triple_models.py`, add the four strings to `RelationLiteral`.

In `entity_normalize.py`, add to `_RELATION_EXPECTED_OBJECT`:

```python
"SURVEYS_METHOD": "Method",
"COVERS_DISEASE": "Disease",
"RELEASES_DATASET": "Dataset",
"PRETRAINS_ON": "Dataset",
```

Do **not** change `_OBJECT_CANONICAL_RELATION` (Dataset must still default-repair to `USES_DATASET`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd fulltext_workflow; python -m pytest tests/test_study_policy.py::test_new_relations_parse_on_triple -v`

Expected: PASS

- [ ] **Step 5: Commit** (only if user requested commits)

```bash
git add fulltext_workflow/extractor/triple_models.py fulltext_workflow/extractor/entity_normalize.py fulltext_workflow/tests/test_study_policy.py
git commit -m "feat(extract): register study-type dataset/survey relations"
```

---

### Task 2: `study_policy.apply_policy` matrix

**Files:**
- Create: `fulltext_workflow/extractor/study_policy.py`
- Modify: `fulltext_workflow/config.py` (add `STUDY_POLICY_ENABLED`)
- Modify: `fulltext_workflow/tests/test_study_policy.py`

**Interfaces:**
- Produces:
  - `DATASET_RELATIONS: frozenset[str]` = `{USES_DATASET, RELEASES_DATASET, PRETRAINS_ON}`
  - `NEW_RELATIONS: frozenset[str]` = the four new relations
  - `get_policy(study_type: str | None) -> StudyPolicy`
  - `apply_policy(triples: list[Triple], study_type: str | None) -> list[Triple]`
  - `StudyPolicy` dataclass: `deny: frozenset[str]`, `remap: dict[str, str]`, `prefer: tuple[str, ...]`, `dataset_mode: str`, `enable_new: frozenset[str]`
- Consumes: `Triple` from `triple_models`; `config.STUDY_POLICY_ENABLED`

**Policy encoding (must match spec):**

- `dataset_mode`: `experimental` | `none` | `release_ok` | `pretrain_ok`
- `enable_new`: which of the four new relations may survive
- `other`: `enable_new` empty → drop all `NEW_RELATIONS`
- `review` / `meta_analysis`: deny `DATASET_RELATIONS`; remap `APPLIES_METHOD`→`SURVEYS_METHOD`; `TARGETS_DISEASE`→`COVERS_DISEASE` iff `evidence_quote` strip non-empty else drop

When `config.STUDY_POLICY_ENABLED` is False, `apply_policy` returns triples unchanged.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_study_policy.py`:

```python
from extractor.triple_models import Triple
from extractor import study_policy as sp


def _t(rel: str, otype: str, name: str = "x", quote: str | None = "q") -> Triple:
    return Triple.model_validate(
        {
            "subject": {"name": "paper", "type": "Method"},
            "relation": rel,
            "object": {"name": name, "type": otype},
            "evidence_quote": quote,
        }
    )


def test_review_drops_dataset_relations(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy(
        [_t("USES_DATASET", "Dataset"), _t("RELEASES_DATASET", "Dataset")],
        "review",
    )
    assert out == []


def test_review_remaps_applies_to_surveys(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy([_t("APPLIES_METHOD", "Method", "clam")], "review")
    assert len(out) == 1
    assert out[0].relation == "SURVEYS_METHOD"


def test_review_targets_without_quote_dropped(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy(
        [_t("TARGETS_DISEASE", "Disease", "lung adenocarcinoma", quote=None)],
        "review",
    )
    assert out == []


def test_review_targets_with_quote_becomes_covers(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy(
        [_t("TARGETS_DISEASE", "Disease", "lung adenocarcinoma", quote="covers NSCLC")],
        "review",
    )
    assert len(out) == 1
    assert out[0].relation == "COVERS_DISEASE"


def test_ai_algorithm_keeps_applies(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy([_t("APPLIES_METHOD", "Method", "clam")], "ai_algorithm")
    assert out[0].relation == "APPLIES_METHOD"


def test_other_denies_new_relations(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy([_t("SURVEYS_METHOD", "Method", "clam")], "other")
    assert out == []


def test_foundation_allows_pretrains_on(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy([_t("PRETRAINS_ON", "Dataset", "tcga")], "foundation_model")
    assert len(out) == 1
    assert out[0].relation == "PRETRAINS_ON"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fulltext_workflow; python -m pytest tests/test_study_policy.py -v`

Expected: FAIL (`study_policy` missing).

- [ ] **Step 3: Implement `study_policy.py` + config flag**

Add to `config.py`:

```python
STUDY_POLICY_ENABLED: bool = os.getenv("STUDY_POLICY_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
```

Implement `study_policy.py` with full eight-type table. Core logic:

```python
def apply_policy(triples: list[Triple], study_type: str | None) -> list[Triple]:
    import config
    if not config.STUDY_POLICY_ENABLED:
        return list(triples)
    policy = get_policy(study_type)
    out: list[Triple] = []
    for t in triples:
        rel = t.relation
        if rel in policy.deny:
            continue
        if policy.dataset_mode == "none" and rel in DATASET_RELATIONS:
            continue
        if rel in policy.remap:
            if rel == "TARGETS_DISEASE":
                q = (t.evidence_quote or "").strip()
                if not q:
                    continue
            rel = policy.remap[rel]
            t = t.model_copy(update={"relation": rel})
        if rel in NEW_RELATIONS and rel not in policy.enable_new:
            continue
        if rel in policy.deny:
            continue
        out.append(t)
    return out
```

Populate `enable_new` per type: review/meta → `{SURVEYS_METHOD, COVERS_DISEASE}`; dataset_benchmark → `{RELEASES_DATASET}`; foundation_model → `{PRETRAINS_ON}`; others that do not use new relations → empty.

`prefer` is stored for prompt assembly; unused by `apply_policy`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fulltext_workflow; python -m pytest tests/test_study_policy.py -v`

Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add fulltext_workflow/extractor/study_policy.py fulltext_workflow/config.py fulltext_workflow/tests/test_study_policy.py
git commit -m "feat(extract): add study-type policy matrix"
```

---

### Task 3: Wire policy into `postprocess_triples`

**Files:**
- Modify: `fulltext_workflow/extractor/entity_normalize.py`
- Modify: `fulltext_workflow/tests/test_entity_normalize.py`

**Interfaces:**
- Consumes: `apply_policy(triples, study_type)`, `get_policy`, `DATASET_RELATIONS`
- Order inside `postprocess_triples`: name normalize → `repair_triple_relation` → **`apply_policy`** → existing filters
- Dataset filter: if `get_policy(study_type).dataset_mode == "none"`, drop triples with `relation in DATASET_RELATIONS` or `object.type == "Dataset"`
- Remove hard-coded `drop_all_datasets = study_type in ("review", "meta_analysis")`

- [ ] **Step 1: Write / update failing tests**

Keep `test_postprocess_drops_all_datasets_for_review_study_type`.

Add (adapt `_triple` to existing helpers in the file):

```python
def test_postprocess_review_remaps_applies_method(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    t = _triple("APPLIES_METHOD", "Method", "clam", quote="survey of clam")
    out = postprocess_triples([t], "methods", study_type="review")
    assert len(out) == 1
    assert out[0].relation == "SURVEYS_METHOD"


def test_postprocess_ai_keeps_uses_dataset(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    t = _triple("USES_DATASET", "Dataset", "camelyon16", quote="trained on")
    out = postprocess_triples([t], "methods", study_type="ai_algorithm")
    assert any(x.relation == "USES_DATASET" for x in out)
```

- [ ] **Step 2: Run tests to verify behavior gap**

Run: `cd fulltext_workflow; python -m pytest tests/test_entity_normalize.py::test_postprocess_review_remaps_applies_method -v`

Expected: FAIL (APPLIES_METHOD still present) until wired.

- [ ] **Step 3: Wire `apply_policy`**

After building `normalized` via `repair_triple_relation`:

```python
from extractor.study_policy import DATASET_RELATIONS, apply_policy, get_policy

normalized = apply_policy(normalized, study_type)
dataset_mode = get_policy(study_type).dataset_mode
```

Replace `drop_all_datasets` checks with `dataset_mode == "none"`. For non-`none` modes, run platform blacklist / rename when `triple.relation in DATASET_RELATIONS` or `object.type == "Dataset"`.

- [ ] **Step 4: Run tests**

Run: `cd fulltext_workflow; python -m pytest tests/test_entity_normalize.py tests/test_study_policy.py -v`

Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add fulltext_workflow/extractor/entity_normalize.py fulltext_workflow/tests/test_entity_normalize.py
git commit -m "feat(extract): enforce study policy in postprocess"
```

---

### Task 4: Prompt packs + section system assembly

**Files:**
- Create: `fulltext_workflow/extractor/study_prompts/__init__.py`
- Create: `fulltext_workflow/extractor/study_prompts/shared.py`
- Create: `fulltext_workflow/extractor/study_prompts/packs.py`
- Modify: `fulltext_workflow/extractor/section_extractor.py`
- Test: `fulltext_workflow/tests/test_study_prompts.py`

**Interfaces:**
- Produces:
  - `@dataclass StudyTypePack`: `study_type: str`, `section_lens: str`, `reconcile_lens: str`, `prefer: tuple[str, ...]`
  - `PACKS: dict[str, StudyTypePack]` for all eight types
  - `build_section_system(section_type: str, study_type: str | None) -> str`
  - `build_reconcile_system(study_type: str | None) -> str`
- Section hints: reuse the existing hint dict from `section_extractor` (move to `study_prompts/shared.py` or import)

**Pack content:** each `section_lens` states scholar focus + emphasize/forbid from the spec table; each `reconcile_lens` restates dataset_mode / survey-cover checklist. Keep each lens ≤ ~600 tokens.

- [ ] **Step 1: Write failing assembly tests**

```python
from extractor.study_prompts import PACKS, build_section_system, build_reconcile_system


def test_all_eight_packs_present():
    for st in (
        "ai_algorithm",
        "clinical_study",
        "review",
        "meta_analysis",
        "dataset_benchmark",
        "foundation_model",
        "multimodal",
        "other",
    ):
        assert st in PACKS
        assert PACKS[st].section_lens.strip()
        assert PACKS[st].reconcile_lens.strip()


def test_review_section_system_mentions_survey_not_applies():
    text = build_section_system("methods", "review")
    assert "SURVEYS_METHOD" in text
    assert "review" in text.lower()


def test_dataset_benchmark_mentions_releases():
    text = build_section_system("methods", "dataset_benchmark")
    assert "RELEASES_DATASET" in text


def test_reconcile_foundation_mentions_pretrain():
    text = build_reconcile_system("foundation_model")
    assert "PRETRAINS_ON" in text or "pretrain" in text.lower()
```

- [ ] **Step 2: Run tests — expect fail**

Run: `cd fulltext_workflow; python -m pytest tests/test_study_prompts.py -v`

Expected: FAIL (package missing).

- [ ] **Step 3: Move shared core and implement packs**

1. Cut current `_BASE_SYSTEM` body from `section_extractor.py` into `study_prompts/shared.py` as `SECTION_SHARED_CORE`. Update the relation list to document the four new relations and when they apply.
2. Copy current `RECONCILE_SYSTEM` rules into `RECONCILE_SHARED_CORE` in `shared.py` (JSON shape extended in Task 6; for now keep shape + note optional fields).
3. `packs.py`: define eight packs. Review example:

```python
StudyTypePack(
    study_type="review",
    prefer=("COVERS_DISEASE", "SURVEYS_METHOD", "REPORTS_LIMITATION"),
    section_lens="""\
STUDY-TYPE LENS (review):
  Read as a survey: coverage of diseases/methods and field gaps — not a single experiment.
  Prefer COVERS_DISEASE and SURVEYS_METHOD. Do NOT emit USES_DATASET / RELEASES_DATASET /
  PRETRAINS_ON. Do NOT emit APPLIES_METHOD for methods only discussed; use SURVEYS_METHOD.
  Limitations may be field-level gaps stated by authors.
""",
    reconcile_lens="""\
RECONCILE LENS (review): prefer empty datasets; map surveyed methods/diseases via
surveyed_methods / covered_diseases arrays. Never keep literature-table datasets.
""",
)
```

Fill the other seven from the spec emphasize/forbid rows.

4. `build_section_system`:

```python
def build_section_system(section_type: str, study_type: str | None) -> str:
    st = (study_type or "other").lower()
    pack = PACKS.get(st, PACKS["other"])
    hint = SECTION_HINTS.get(section_type, DEFAULT_SECTION_HINT)
    return (
        f"{SECTION_SHARED_CORE}\n\n"
        f"Study type pack: {pack.study_type}\n"
        f"{pack.section_lens}\n\n"
        f"Section focus: {hint}"
    )
```

5. In `section_extractor.py`, delete `_BASE_SYSTEM`; `_section_system(section_type, study_type=None)` calls `build_section_system`; `_extract_from_text` passes `study_type`.

- [ ] **Step 4: Run tests**

Run: `cd fulltext_workflow; python -m pytest tests/test_study_prompts.py -v`

Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add fulltext_workflow/extractor/study_prompts fulltext_workflow/extractor/section_extractor.py fulltext_workflow/tests/test_study_prompts.py
git commit -m "feat(extract): study-type section prompt packs"
```

---

### Task 5: Classifier prompt alignment

**Files:**
- Modify: `fulltext_workflow/extractor/study_classifier.py`
- Test: `fulltext_workflow/tests/test_study_classifier_prompt.py`

**Interfaces:**
- Produces: updated `_STUDY_TYPE_SYSTEM` text (no API change to `classify_study_type`)

- [ ] **Step 1: Failing test on prompt keywords**

```python
from extractor import study_classifier as sc


def test_classifier_system_has_scholar_lenses():
    text = sc._STUDY_TYPE_SYSTEM
    assert "benchmark" in text.lower() or "dataset construction" in text.lower()
    assert "pre-trained" in text.lower() or "foundation" in text.lower()
    assert "survey" in text.lower() or "narrative" in text.lower()
```

- [ ] **Step 2: Run — may fail if wording missing**

Run: `cd fulltext_workflow; python -m pytest tests/test_study_classifier_prompt.py -v`

- [ ] **Step 3: Rewrite classifier bullets**

Replace type bullets with scholar-focus discriminators from the spec (dataset release/protocol → `dataset_benchmark`; pretrain + broad transfer → `foundation_model`; clinical validation/outcomes → `clinical_study`; etc.). Keep JSON response schema and heuristics unchanged.

- [ ] **Step 4: Pass tests**

Run: `cd fulltext_workflow; python -m pytest tests/test_study_classifier_prompt.py tests/test_skip_rules.py -v`

Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add fulltext_workflow/extractor/study_classifier.py fulltext_workflow/tests/test_study_classifier_prompt.py
git commit -m "feat(extract): align study-type classifier with scholar lenses"
```

---

### Task 6: Pass 2 reconcile packs, `role`, survey/cover writes

**Files:**
- Modify: `fulltext_workflow/extractor/fulltext_reconcile.py`
- Modify: `fulltext_workflow/extractor/study_prompts/shared.py`
- Modify: `fulltext_workflow/extractor/section_extractor.py` (`_save_triple`)
- Modify: `fulltext_workflow/tests/test_fulltext_reconcile.py`

**Interfaces:**
- Consumes: `build_reconcile_system(study_type)`, `apply_policy`, `get_policy`, `DATASET_RELATIONS`
- Produces:
  - `parse_reconcile_payload` accepts optional `role` on datasets (`experimental|release|pretrain|drop`)
  - Optional `surveyed_methods: [{name, quote}]`, `covered_diseases: [{name, quote}]`
  - `_apply_dataset_actions`: `role=release` → `RELEASES_DATASET`; `role=pretrain` → `PRETRAINS_ON`; `experimental` → `USES_DATASET`; `dataset_mode==none` clears all dataset-class edges except meta keep exception
  - `_apply_survey_cover(paper_id, pmid, surveyed, covered)` inserts Paper→ relations
  - `call_reconcile_llm` uses `build_reconcile_system(study_type)`

**Meta exception contract:** If `study_type == "meta_analysis"` and a dataset row has `action=keep`, `role=experimental`, and `reason` lowercased contains `"self-analysis"` **or** `"pooled analysis by the authors"`, allow that `USES_DATASET` keep; otherwise clear under `dataset_mode=none`. Document these exact substrings in `RECONCILE_SHARED_CORE`.

- [ ] **Step 1: Failing tests**

```python
def test_parse_dataset_role_and_survey_fields():
    from extractor.fulltext_reconcile import parse_reconcile_payload
    raw = {
        "datasets": [
            {
                "name": "camelyon16",
                "access": "public",
                "action": "keep",
                "role": "release",
                "reason": "we release",
            }
        ],
        "surveyed_methods": [{"name": "clam", "quote": "CLAM is widely used"}],
        "covered_diseases": [{"name": "breast cancer", "quote": "we cover breast cancer"}],
        "bindings": [],
        "limitations": [],
    }
    p = parse_reconcile_payload(raw)
    assert p["datasets"][0]["role"] == "release"
    assert p["surveyed_methods"][0]["name"] == "clam"
```

Add `test_review_apply_clears_datasets_and_writes_survey` by extending the existing `test_review_study_type_clears_all_datasets` fixture pattern in the same file: after clear, assert a `SURVEYS_METHOD` edge exists when payload includes `surveyed_methods`.

- [ ] **Step 2: Run — expect fail**

Run: `cd fulltext_workflow; python -m pytest tests/test_fulltext_reconcile.py::test_parse_dataset_role_and_survey_fields -v`

- [ ] **Step 3: Implement parse + apply + prompt**

1. Extend parsers for `role`, `surveyed_methods`, `covered_diseases`.
2. `_apply_dataset_actions`: honor roles when inserting; on `dataset_mode==none`, supersede all `DATASET_RELATIONS` unless meta keep exception.
3. New `_apply_survey_cover`.
4. `apply_reconcile_payload` calls survey/cover after datasets.
5. `call_reconcile_llm`: `llm_call_structured(build_reconcile_system(study_type), user)`.
6. In `section_extractor._save_triple`, treat `RELEASES_DATASET` / `PRETRAINS_ON` like `USES_DATASET` for normalize + access resolve.

- [ ] **Step 4: Run tests**

Run: `cd fulltext_workflow; python -m pytest tests/test_fulltext_reconcile.py tests/test_study_prompts.py -v`

Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add fulltext_workflow/extractor/fulltext_reconcile.py fulltext_workflow/extractor/section_extractor.py fulltext_workflow/extractor/study_prompts fulltext_workflow/tests/test_fulltext_reconcile.py
git commit -m "feat(extract): study-type Pass2 roles and survey/cover edges"
```

---

### Task 7: Downstream minimal adapters

**Files:**
- Modify: `fulltext_workflow/graph/kg_builder.py`
- Modify: `fulltext_workflow/analysis/gap_tools.py`
- Modify: `fulltext_workflow/idea_agent.py` (docstring / blurb only)
- Test: `fulltext_workflow/tests/test_gap_study_type_stats.py` (**New**)

**Interfaces:**
- Produces: `tool_study_type_relation_stats() -> dict` with counts per new relation
- Graph: if edges support attributes, set `relation` (already) and optional color from a `RELATION_COLORS` map; must not break `KGBuilder` build
- Verify `tool_hotspot_entities` still counts Method via `APPLIES_METHOD` only

- [ ] **Step 1: Failing test for stats tool**

```python
def test_study_type_relation_stats_shape():
    from analysis.gap_tools import tool_study_type_relation_stats
    out = tool_study_type_relation_stats()
    assert "data" in out
    names = {r["relation"] for r in out["data"]}
    for rel in (
        "SURVEYS_METHOD",
        "COVERS_DISEASE",
        "RELEASES_DATASET",
        "PRETRAINS_ON",
    ):
        assert rel in names
```

(Use the same DB isolation pattern as other gap tool tests if the suite requires a temp DB; otherwise empty production-test DB returning zeros is fine.)

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement tool + graph/idea notes**

```python
def tool_study_type_relation_stats() -> dict:
    rows = _q("""
        SELECT r.relation AS relation, COUNT(*) AS edge_cnt,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt
        FROM relations r
        WHERE COALESCE(r.status, 'active') = 'active'
          AND r.relation IN (
            'SURVEYS_METHOD', 'COVERS_DISEASE',
            'RELEASES_DATASET', 'PRETRAINS_ON'
          )
        GROUP BY r.relation
    """)
    by = {r["relation"]: r for r in rows}
    data = []
    for rel in (
        "SURVEYS_METHOD",
        "COVERS_DISEASE",
        "RELEASES_DATASET",
        "PRETRAINS_ON",
    ):
        data.append(by.get(rel, {"relation": rel, "edge_cnt": 0, "paper_cnt": 0}))
    return {
        "description": "Read-only counts for study-type-specific relations (QA)",
        "data": data,
    }
```

In `idea_agent.py`, add one sentence near dataset/method tool docs: surveyed methods/diseases ≠ APPLIES/TARGETS; `RELEASES_DATASET` ≠ cited-only `USES_DATASET`.

- [ ] **Step 4: Run tests**

Run: `cd fulltext_workflow; python -m pytest tests/test_gap_study_type_stats.py tests/test_graph_pagerank.py -v`

Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add fulltext_workflow/graph/kg_builder.py fulltext_workflow/analysis/gap_tools.py fulltext_workflow/idea_agent.py fulltext_workflow/tests/test_gap_study_type_stats.py
git commit -m "feat(analysis): QA stats for study-type relations"
```

---

### Task 8: Stratified pilot checklist + regression suite

**Files:**
- Create: `fulltext_workflow/docs/pilot_study_type_qa.md`

- [ ] **Step 1: Write checklist with exact SQL and gates**

Include:

1. SQL to count papers by `study_type` and sample ≥3 PMIDs per available type among `ai_algorithm`, `clinical_study`, `review`, `dataset_benchmark`, `foundation_model` (verify column names for fulltext readiness from `db/schema.py` before finalizing WHERE clauses).
2. QA gates from the spec (review `USES_DATASET`≈0; release vs use ≥80% on sample; foundation pretrain vs eval spot check; ai_algorithm platform blacklist regression).
3. Exact extract CLI invocation from `main.py` (`extract --pmid-list ...`).

- [ ] **Step 2: Run full unit regression (no live LLM)**

Run: `cd fulltext_workflow; python -m pytest tests/test_study_policy.py tests/test_study_prompts.py tests/test_entity_normalize.py tests/test_fulltext_reconcile.py tests/test_study_classifier_prompt.py tests/test_gap_study_type_stats.py tests/test_dataset_access.py -v`

Expected: PASS

- [ ] **Step 3: Commit** (if requested)

```bash
git add fulltext_workflow/docs/pilot_study_type_qa.md
git commit -m "docs: stratified pilot QA for study-type prompts"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| Prompt packs (section + reconcile) | 4, 6 |
| Policy matrix allow/deny/remap/dataset_mode | 2, 3 |
| Four new relations | 1, 6 |
| Classifier lens alignment | 5 |
| Pass 1 assembly + postprocess enforce | 3, 4 |
| Pass 2 role + survey/cover + clear | 6 |
| Downstream minimal (graph/stats/idea note) | 7 |
| Stratified pilot gates | 8 |
| `other` denies new relations | 2 |
| Remap only review/meta | 2 |
| No USES→RELEASES auto-remap | 2 (absent by design) |
| Meta Pass2-only exception | 6 |
| Method heat APPLIES-only | 7 (verify) |

## Consistency notes

- `SECTION_HINTS` must match current `section_extractor` section focus strings; move or import — do not invent new section policy.
- Task 6 DB tests reuse existing `test_fulltext_reconcile.py` fixtures; do not invent a second schema helper.
- Exact fulltext readiness column values verified at Task 8 write time from `db/schema.py`.
