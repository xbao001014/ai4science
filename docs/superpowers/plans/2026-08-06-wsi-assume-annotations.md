# WSI Assume Annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When WSI exists, temporarily score all `required_annotations` as available at `has_wsi` scale, while returning structured observed vs assumed disclosure for proposals and UI.

**Architecture:** Assess-time only in `assess_feasibility_from_pools` behind `FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI`. Landscape pools stay API-observed. Tool JSON adds `annotation_assumption`; Idea prompts and Gap UI surface observed vs assumed lists.

**Tech Stack:** Python 3, pytest, existing V-01 assessment / Streamlit gap_ui / idea_agent prompts

**Spec:** `docs/superpowers/specs/2026-08-06-wsi-assume-annotations-design.md`

## Global Constraints

- Assume only `required_annotations` (not molecular, not survival/follow-up labels)
- Assumed count = `has_wsi` when `has_wsi > 0` (not ratio floor)
- Landscape / `feasibility_pools` remain observed; do not rewrite on bootstrap
- Disclosure must split `observed` vs `assumed_from_wsi`
- Flag default `True`; `False` restores 2026-08-04 annotation `min` behavior
- Do not change Critic numeric accept thresholds

## File map

| File | Role |
|------|------|
| `fulltext_workflow/config.py` | `FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI` |
| `.env.example` | Document the env override |
| `fulltext_workflow/feasibility/assessment.py` | Assess-time assumption + `annotation_assumption` |
| `fulltext_workflow/tests/test_feasibility_sparse_annotation_floor.py` | Update faithful tests + add assumption tests |
| `fulltext_workflow/gap_ui.py` | Render assumption under 样本分解 |
| `fulltext_workflow/idea_agent.py` | Generator §9 + Critic disclosure rules |
| `fulltext_workflow/PIPELINE.md` | One-line note on temporary assumption |

---

### Task 1: Config flag + assessment assumption logic

**Files:**
- Modify: `fulltext_workflow/config.py` (after `FEASIBILITY_SCORE_MARGINAL`)
- Modify: `.env.example` (near `PATHOLOGY_DATA_PROVIDER`)
- Modify: `fulltext_workflow/feasibility/assessment.py`
- Modify: `fulltext_workflow/tests/test_feasibility_sparse_annotation_floor.py`

**Interfaces:**
- Consumes: `HypothesisRequest.required_annotations`, pools `has_wsi` / annotation keys, `config.FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI`
- Produces: assessment dict field `annotation_assumption: dict | None` with keys `observed: list[str]`, `assumed_from_wsi: list[str]`, `raw_observed: dict[str, int]`, `assumed_count: int`

- [ ] **Step 1: Write failing tests**

In `fulltext_workflow/tests/test_feasibility_sparse_annotation_floor.py`, keep existing normalize + survival tests. Replace / extend annotation tests as follows:

```python
def test_flag_off_sparse_tnm_still_tightens(monkeypatch):
    import config
    monkeypatch.setattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", False)
    pools = {
        "cohort_base": 2709,
        "has_wsi": 2709,
        "has_tnm_stage": 1,
        "has_who_grade": 1,
        "enumerated_patients": 560,
    }
    req = HypothesisRequest(
        disease_id="C_CA",
        task_type="grade_classification",
        required_labels=[],
        required_annotations=["tnm_stage", "who_grade"],
        min_followup_months=0,
    )
    result = assess_feasibility_from_pools(req, pools)
    assert result["available_cohort_size"] == 1
    assert result["feasibility_score"] == 0.0
    assert result.get("annotation_assumption") in (None, {})


def test_flag_on_zero_tumor_region_assumes_has_wsi(monkeypatch):
    import config
    monkeypatch.setattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", True)
    pools = {
        "cohort_base": 12066,
        "has_wsi": 12066,
        "has_tumor_region": 0,
        "enumerated_patients": 930,
    }
    req = HypothesisRequest(
        disease_id="C_XR",
        task_type="segmentation",
        required_labels=[],
        required_annotations=["tumor_region"],
        min_followup_months=0,
    )
    result = assess_feasibility_from_pools(req, pools)
    assert result["available_cohort_size"] == 12066
    assert result["feasibility_score"] == 1.0
    aa = result["annotation_assumption"]
    assert aa["assumed_from_wsi"] == ["tumor_region"]
    assert aa["observed"] == []
    assert aa["raw_observed"]["tumor_region"] == 0
    assert aa["assumed_count"] == 12066
    assert result["breakdown"]["has_tumor_region"] == 12066


def test_flag_on_sparse_observed_listed_under_observed(monkeypatch):
    import config
    monkeypatch.setattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", True)
    pools = {
        "cohort_base": 2709,
        "has_wsi": 2709,
        "has_tnm_stage": 1,
    }
    req = HypothesisRequest(
        disease_id="C_CA",
        task_type="classification",
        required_labels=[],
        required_annotations=["tnm_stage"],
        min_followup_months=0,
    )
    result = assess_feasibility_from_pools(req, pools)
    assert result["available_cohort_size"] == 2709
    aa = result["annotation_assumption"]
    assert aa["observed"] == ["tnm_stage"]
    assert aa["assumed_from_wsi"] == []
    assert aa["raw_observed"]["tnm_stage"] == 1
    assert result["breakdown"]["has_tnm_stage"] == 2709


def test_no_wsi_does_not_assume(monkeypatch):
    import config
    monkeypatch.setattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", True)
    pools = {"cohort_base": 100, "has_wsi": 0, "has_tumor_region": 0}
    req = HypothesisRequest(
        disease_id="X",
        task_type="segmentation",
        required_annotations=["tumor_region"],
    )
    result = assess_feasibility_from_pools(req, pools)
    assert result["available_cohort_size"] == 0
    assert result.get("annotation_assumption") in (None, {})
```

Rename/remove old `test_sparse_observed_tnm_tightens_without_floor` so it does not conflict (covered by `test_flag_off_sparse_tnm_still_tightens`).

- [ ] **Step 2: Run tests — expect FAIL**

```powershell
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_feasibility_sparse_annotation_floor.py -v
```

Expected: FAIL (missing config attr and/or `annotation_assumption` / wrong cohort).

- [ ] **Step 3: Add config**

In `fulltext_workflow/config.py` after the score thresholds:

```python
FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI: bool = (
    os.getenv("FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", "true").lower()
    in ("1", "true", "yes")
)
```

In `.env.example` near pathology settings:

```
# Temporary: treat required_annotations as available at has_wsi scale (default true)
FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI=true
```

- [ ] **Step 4: Implement assessment loop**

In `fulltext_workflow/feasibility/assessment.py`:

1. `import config` (already present).
2. Before the annotation loop, init:

```python
ann_observed: list[str] = []
ann_assumed: list[str] = []
raw_observed: dict[str, int] = {}
assume = bool(getattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", False))
has_wsi = int(pools.get("has_wsi") or breakdown.get("has_wsi") or 0)
```

3. Replace the annotation loop body with:

```python
for ann in req.required_annotations:
    key = _ANNOTATION_POOL_KEYS.get(ann, f"has_{ann}")
    if _is_unverifiable_pool_key(key, provenance):
        unverified.append(ann)
        continue
    raw = int(pools[key]) if key in pools else 0
    raw_observed[ann] = raw
    if assume and has_wsi > 0:
        cnt = has_wsi
        if raw > 0:
            ann_observed.append(ann)
        else:
            ann_assumed.append(ann)
    else:
        cnt = raw
    breakdown[f"has_{ann}"] = cnt
    cohort = min(cohort, cnt)
```

4. Build return payload:

```python
annotation_assumption = None
if assume and has_wsi > 0 and (ann_observed or ann_assumed):
    annotation_assumption = {
        "observed": ann_observed,
        "assumed_from_wsi": ann_assumed,
        "raw_observed": raw_observed,
        "assumed_count": has_wsi,
    }
```

Include `"annotation_assumption": annotation_assumption` in the returned dict (also on the early `disease_exists=False` path use `None`).

5. Optionally extend `note_from_assessment` to accept optional assumed list and append  
   `；标注临时假定(有WSI): a, b` — keep short; structured field remains source of truth.

- [ ] **Step 5: Run tests — expect PASS**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_feasibility_sparse_annotation_floor.py -v
```

Also run:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_feasibility.py -v
```

Fix any mock expectations if they assert old sparse-zero behavior under default flag.

- [ ] **Step 6: Commit** (only if user requested commits in this session)

```bash
git add fulltext_workflow/config.py .env.example fulltext_workflow/feasibility/assessment.py fulltext_workflow/tests/test_feasibility_sparse_annotation_floor.py
git commit -m "feat: assume required_annotations from WSI at assess time"
```

---

### Task 2: Gap UI disclosure

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (inside the V-01 renderer that shows 样本分解 — around the `breakdown` expander near lines 481–486)

**Interfaces:**
- Consumes: `result["annotation_assumption"]` from Task 1
- Produces: UI block listing observed / assumed_from_wsi / raw_observed

- [ ] **Step 1: Add render after breakdown expander**

Immediately after the existing `样本分解` expander block:

```python
aa = result.get("annotation_assumption")
if isinstance(aa, dict) and (aa.get("observed") or aa.get("assumed_from_wsi")):
    with st.expander("标注假定（有 WSI 临时策略）", expanded=True):
        st.markdown(
            "- **接口实测**: "
            + (", ".join(aa.get("observed") or []) or "（无）")
        )
        st.markdown(
            "- **有 WSI 临时假定**: "
            + (", ".join(aa.get("assumed_from_wsi") or []) or "（无）")
        )
        raw = aa.get("raw_observed") or {}
        if raw:
            safe_table(
                pd.DataFrame(
                    [{"annotation": k, "raw_observed": v} for k, v in raw.items()]
                )
            )
        st.caption(
            f"假定计数 = has_wsi（{aa.get('assumed_count', '—')}）；"
            "landscape 池仍为接口实测。"
        )
```

Also show `unverified_requirements` nearby if not already shown (if missing, add a one-line caption).

- [ ] **Step 2: Manual smoke** (optional if Streamlit already running)

Open Data Feasibility tab, assess `C_XR` with `required_annotations=["tumor_region"]`, confirm score rises and expander lists `tumor_region` under 临时假定.

- [ ] **Step 3: Commit** (only if user requested)

```bash
git add fulltext_workflow/gap_ui.py
git commit -m "feat: show WSI annotation assumptions in V-01 UI"
```

---

### Task 3: Idea Generator / Critic prompts

**Files:**
- Modify: `fulltext_workflow/idea_agent.py` (`GENERATOR_SYSTEM_PROMPT` §9 block ~527–533; `CRITIC_SYSTEM_PROMPT` rules ~563–566)

**Interfaces:**
- Consumes: tool result `annotation_assumption`
- Produces: proposal markdown bullets + critic verification text rules (prompt-only; no new JSON schema fields required)

- [ ] **Step 1: Extend Generator §9**

Replace the Fangxin section bullet list so after `required_annotations` it includes:

```
- **required_annotations**: [<pathology annotations>]
- **annotations_observed**: [<from feasibility_assess.annotation_assumption.observed, or none>]
- **annotations_assumed_from_wsi**: [<from annotation_assumption.assumed_from_wsi, or none>]
- **min_followup_months**: <integer or N/A>
```

Add one rule line in Generator system prompt (near Fangxin section):

```
When feasibility_assess returns annotation_assumption, copy observed vs assumed_from_wsi \
into §9; never describe assumed_from_wsi items as API-verified annotations.
```

- [ ] **Step 2: Extend Critic rules**

After the unverified_requirements bullet, add:

```
- If annotation_assumption.assumed_from_wsi is non-empty, data_feasibility_verification \
must name those annotations as temporary WSI assumptions (not API-verified). \
Do not set accept=false solely because assumptions exist.
- Do not claim "Fangxin annotations verified" for assumed_from_wsi items.
```

- [ ] **Step 3: No automated LLM test required**; if a prompt snapshot test exists, update it. Otherwise skip.

- [ ] **Step 4: Commit** (only if user requested)

```bash
git add fulltext_workflow/idea_agent.py
git commit -m "docs: disclose WSI-assumed annotations in idea prompts"
```

---

### Task 4: Pipeline note + regression sweep

**Files:**
- Modify: `fulltext_workflow/PIPELINE.md` (API-faithful pools paragraph ~326)
- Optionally: `fulltext_workflow/README.md` one line under feasibility

- [ ] **Step 1: Document temporary override**

After the API-faithful sentence in `PIPELINE.md`, add:

```
**临时策略（2026-08-06）**：评估时若 `FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI=true`（默认）且 `has_wsi>0`，
将假说 `required_annotations` 按 `has_wsi` 计入队列，并在结果 `annotation_assumption` /
提案 §9 / Gap UI 区分「接口实测」与「有 WSI 临时假定」。landscape 池仍只存实测。
接口完善后将该开关设为 `false`。设计见 `docs/superpowers/specs/2026-08-06-wsi-assume-annotations-design.md`。
```

- [ ] **Step 2: Full related pytest**

```powershell
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_feasibility_sparse_annotation_floor.py tests/test_feasibility.py tests/test_landscape_tumor_region_fallback.py -v
```

Expected: all PASS.

- [ ] **Step 3: Mark spec status**

In `docs/superpowers/specs/2026-08-06-wsi-assume-annotations-design.md`, set `Status: Implemented` after verification.

- [ ] **Step 4: Commit** (only if user requested)

```bash
git add fulltext_workflow/PIPELINE.md docs/superpowers/specs/2026-08-06-wsi-assume-annotations-design.md
git commit -m "docs: note temporary WSI annotation assumption"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Assume all `required_annotations` at `has_wsi` | Task 1 |
| Assess-time only; landscape unchanged | Task 1 (no landscape edits) |
| `annotation_assumption` observed / assumed / raw / count | Task 1 |
| Flag default true / off restores faithful | Task 1 tests |
| No molecular/survival assumption | Task 1 (untouched loops) |
| Gap UI disclosure | Task 2 |
| Proposal §9 + Critic disclosure | Task 3 |
| Docs / success criteria | Task 4 |

## Self-review notes

- No TBD placeholders.
- Types consistent: `annotation_assumption` dict shape reused in UI and prompts.
- Existing `test_sparse_observed_tnm_tightens_without_floor` must be migrated to flag-off test so default-on does not break CI.
