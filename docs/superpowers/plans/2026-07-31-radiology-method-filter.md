# Radiology Method Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop radiology / imaging Methods in extraction postprocess so they never enter the KG as research Methods.

**Architecture:** Add `is_radiology_method()` with exact + word-boundary patterns in `entity_normalize.py`; call it from `is_low_value_method()` so all existing Method drop paths apply. Document in GRANULARITY.md; cover with unit tests.

**Tech Stack:** Python 3, pytest, existing `extractor.entity_normalize` postprocess.

## Global Constraints

- Aggressive policy: multimodal pathology+CT names are dropped.
- Bare `imaging` / `medical imaging` are exact-only (do **not** use `\bimaging\b`, to avoid over-dropping pathology phrases).
- No DB migration / no hotspot-only filter in this plan.
- Do not commit unless the user asks.

---

### Task 1: Failing tests for radiology Methods

**Files:**
- Modify: `fulltext_workflow/tests/test_entity_normalize.py`
- Test: same

**Interfaces:**
- Consumes: `is_low_value_method`, `is_radiology_method` (to be added), `postprocess_triples`, `_method_triple`
- Produces: failing tests that define required behavior

- [ ] **Step 1: Write the failing tests**

Add imports for `is_radiology_method`. Add:

```python
def test_is_radiology_method():
    assert is_radiology_method("pyradiomics")
    assert is_radiology_method("Radiomics Model")
    assert is_radiology_method("ai-assisted cbct")
    assert is_radiology_method("mri-mba toolkit")
    assert is_radiology_method("pet assisted reporting system (pars)")
    assert is_radiology_method("quantitative ultrasound")
    assert is_radiology_method("ai-enhanced endoscopy")
    assert is_radiology_method("high-resolution optical coherence tomography")
    assert is_radiology_method("cpnet (ct and pathology mutual guidance fusion diagnostic network)")
    assert is_radiology_method("radiomics")
    assert is_radiology_method("imaging")
    assert not is_radiology_method("hover-net")
    assert not is_radiology_method("clam")
    assert not is_radiology_method("dual-attention mil")
    assert not is_radiology_method("resnet-50")


def test_is_low_value_includes_radiology_methods():
    assert is_low_value_method("pyradiomics")
    assert is_low_value_method("radiomics model")
    assert not is_low_value_method("hover-net")


def test_postprocess_drops_radiology_methods():
    triples = [
        _method_triple("pyradiomics"),
        _method_triple("radiomics model"),
        _method_triple("ai-assisted cbct"),
        _method_triple("clam"),
    ]
    out = postprocess_triples(triples, "methods")
    names = [t.object.name for t in out if t.relation == "APPLIES_METHOD"]
    assert names == ["clam"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest fulltext_workflow/tests/test_entity_normalize.py::test_is_radiology_method fulltext_workflow/tests/test_entity_normalize.py::test_is_low_value_includes_radiology_methods fulltext_workflow/tests/test_entity_normalize.py::test_postprocess_drops_radiology_methods -v`

Expected: FAIL (import / assert failures)

---

### Task 2: Implement `is_radiology_method` and wire into `is_low_value_method`

**Files:**
- Modify: `fulltext_workflow/extractor/entity_normalize.py`
- Modify: `fulltext_workflow/extractor/GRANULARITY.md` (Method maintenance table)
- Test: `fulltext_workflow/tests/test_entity_normalize.py`

**Interfaces:**
- Consumes: `_norm_key`, existing `_RADIOLOGY_MODALITIES` (reuse membership where useful)
- Produces: `is_radiology_method(name: str) -> bool`; `is_low_value_method` returns True when radiology

- [ ] **Step 1: Add constants and function after `_RADIOLOGY_MODALITY_PATTERNS`**

```python
_RADIOLOGY_METHODS = frozenset(
    set(_RADIOLOGY_MODALITIES)
    | {
        "pyradiomics",
        "optical coherence tomography",
        "endoscopy",
        "endoscope",
        "cbct",
        "oct",
        "computed tomography",
    }
)

_RADIOLOGY_METHOD_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"\bradiomics?\b",
        r"\bpyradiomics\b",
        r"\bct\b",
        r"\bmri\b",
        r"\bpet\b",
        r"\bcbct\b",
        r"\boct\b",
        r"\bultrasound\b",
        r"\bsonograph",
        r"\bendoscop",
        r"\bmammograph",
        r"\btomograph",
        r"\bx[\s-]?ray\b",
        r"\bpet[\s\-/]?ct\b",
        r"\bradiolog",
        r"\boptical\s+coherence\s+tomograph",
    )
)


def is_radiology_method(name: str) -> bool:
    """True for radiology/imaging Methods (Fangxin has pathology slides only)."""
    key = _norm_key(name)
    if key in _RADIOLOGY_METHODS:
        return True
    return any(p.search(key) for p in _RADIOLOGY_METHOD_PATTERNS)
```

- [ ] **Step 2: Extend `is_low_value_method`**

```python
def is_low_value_method(name: str) -> bool:
    key = _norm_key(name)
    if key in _LOW_VALUE_METHODS:
        return True
    if any(p.search(key) for p in _LOW_VALUE_METHOD_PATTERNS):
        return True
    return is_radiology_method(name)
```

- [ ] **Step 3: Update GRANULARITY.md §2.1 / §2.2**

In **不保留**, add radiology Methods line. In the maintenance table, add rows for `_RADIOLOGY_METHODS` / `_RADIOLOGY_METHOD_PATTERNS` / `is_radiology_method`. Note bare `imaging` is exact-only.

- [ ] **Step 4: Re-run tests**

Run: `py -m pytest fulltext_workflow/tests/test_entity_normalize.py -q`

Expected: all pass
