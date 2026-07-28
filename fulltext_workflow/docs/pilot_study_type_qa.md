# Stratified pilot QA — study-type prompts & policy matrix

**Scope:** Phase-1 pilot before full Pass 1+2 re-extract.  
**Depends on:** `2026-07-28-study-type-prompt-policy-design.md`, `2026-07-25-extraction-quality-design.md`.

## Schema reference (verified from `db/schema.py`)

| Column | Table | Values / meaning |
|--------|-------|------------------|
| `study_type` | `papers` | Classifier output (`ai_algorithm`, `clinical_study`, `review`, …) |
| `full_text_status` | `papers` | `pending` (default), `available` (JATS), `pdf_available` (MinerU PDF), `unavailable`; transient `jats_unavailable` → `unavailable` |
| `extraction_done` | `papers` | `0` / `1` — Pass 1 complete |
| `reconcile_status` | `papers` | `pending`, `done`, `skipped_no_ft`, `failed` |
| `status` | `relations` | `active` (default), `superseded` |
| `relation` | `relations` | Legacy + `SURVEYS_METHOD`, `COVERS_DISEASE`, `RELEASES_DATASET`, `PRETRAINS_ON` |

**Fulltext-ready papers:** `full_text_status IN ('available', 'pdf_available')` (same predicate as `main.py reconcile` and `get_papers_for_extraction` priority).

---

## Step 1 — Inventory by `study_type`

```sql
-- Count all classified papers
SELECT COALESCE(study_type, '(null)') AS study_type, COUNT(*) AS n
FROM papers
GROUP BY study_type
ORDER BY n DESC;
```

```sql
-- Stratified pilot types: counts with fulltext readiness
SELECT
  study_type,
  full_text_status,
  COUNT(*) AS n
FROM papers
WHERE study_type IN (
  'ai_algorithm', 'clinical_study', 'review',
  'dataset_benchmark', 'foundation_model'
)
GROUP BY study_type, full_text_status
ORDER BY study_type, full_text_status;
```

---

## Step 2 — Stratified PMID sample (≥3 per type when corpus allows)

Prefer JATS over PDF, recent year, and papers that already have `document_sections` (needed for Pass 1).

```sql
WITH ranked AS (
  SELECT
    p.pmid,
    p.study_type,
    p.full_text_status,
    p.year,
    p.extraction_done,
    p.reconcile_status,
    ROW_NUMBER() OVER (
      PARTITION BY p.study_type
      ORDER BY
        CASE p.full_text_status
          WHEN 'available' THEN 0
          WHEN 'pdf_available' THEN 1
          ELSE 2
        END,
        p.year DESC,
        p.pmid
    ) AS rn
  FROM papers p
  WHERE p.study_type IN (
    'ai_algorithm', 'clinical_study', 'review',
    'dataset_benchmark', 'foundation_model'
  )
    AND p.pmid IS NOT NULL
    AND p.full_text_status IN ('available', 'pdf_available')
    AND EXISTS (
      SELECT 1 FROM document_sections s WHERE s.paper_id = p.id
    )
)
SELECT pmid, study_type, full_text_status, year, extraction_done, reconcile_status
FROM ranked
WHERE rn <= 3
ORDER BY study_type, rn;
```

Write PMIDs (one per line, `#` comments OK) to `data/pilot_study_type_pmids.txt`. Target **20–50** total; extend the window (`rn <= 5`) or add `meta_analysis` / `multimodal` if a type has fewer than 3 fulltext rows.

```sql
-- Types under-represented in fulltext-ready pool (action: fetch more or relax to abstract-only for that type only)
SELECT study_type, COUNT(*) AS fulltext_ready
FROM papers
WHERE study_type IN (
  'ai_algorithm', 'clinical_study', 'review',
  'dataset_benchmark', 'foundation_model'
)
  AND full_text_status IN ('available', 'pdf_available')
  AND pmid IS NOT NULL
GROUP BY study_type
HAVING COUNT(*) < 3;
```

---

## Step 3 — Extract & reconcile CLI (`main.py`)

From `fulltext_workflow/`:

```bash
python main.py extract \
  --pmid-list data/pilot_study_type_pmids.txt \
  --force-reextract
```

| Flag | Purpose |
|------|---------|
| `--pmid-list PATH` | Text file, one PMID per line (`#` lines ignored) |
| `--force-reextract` | Clear relations/bindings for target PMIDs, then Pass 1 → rules → Pass 2 |
| `--core-only` | Methods/results/discussion/limitations/future_work only (faster) |
| `--all-sections` | Include introduction/other sections |
| `--limit N` | Max papers when `--pmid-list` omitted (default 30; `0` = all pending) |
| `--section-workers N` | Parallel LLM calls per paper |
| `--paper-workers N` | Parallel papers |

Pass 2 only (after Pass 1):

```bash
python main.py reconcile --pmid-list data/pilot_study_type_pmids.txt
```

Export CSV for manual review:

```bash
python scripts/pilot_reconcile_qa.py \
  --pmid-list data/pilot_study_type_pmids.txt \
  --out output/pilot_study_type_qa.csv
```

---

## Step 4 — QA gates (human + SQL)

Downstream reads use **`COALESCE(r.status, 'active') = 'active'`** unless checking superseded history.

### Gate A — Review / meta: no active dataset-class edges

**Pass:** zero rows on pilot PMIDs (`USES_DATASET` / `RELEASES_DATASET` / `PRETRAINS_ON`).

```sql
SELECT p.pmid, p.study_type, r.relation, e.name AS dataset, r.evidence_quote
FROM papers p
JOIN relations r ON r.source_pmid = p.pmid
JOIN entities e ON e.id = r.object_id
WHERE p.study_type IN ('review', 'meta_analysis')
  AND r.relation IN ('USES_DATASET', 'RELEASES_DATASET', 'PRETRAINS_ON')
  AND COALESCE(r.status, 'active') = 'active'
  AND p.pmid IN (/* pilot list */);
-- Expected: 0 rows
```

### Gate B — Review / meta: residual false `APPLIES_METHOD`

**Pass:** ≈0 active `APPLIES_METHOD` on review/meta pilot rows (should remap to `SURVEYS_METHOD` or drop).

```sql
SELECT p.pmid, e.name AS method, r.evidence_section, r.evidence_quote
FROM papers p
JOIN relations r ON r.source_pmid = p.pmid
JOIN entities e ON e.id = r.object_id AND e.type = 'Method'
WHERE p.study_type IN ('review', 'meta_analysis')
  AND r.relation = 'APPLIES_METHOD'
  AND COALESCE(r.status, 'active') = 'active'
  AND p.pmid IN (/* pilot list */);
```

### Gate C — `dataset_benchmark`: release vs use ≥80%

For each pilot `dataset_benchmark` PMID, manually label each named dataset as **released by this paper** vs **cited/used only**. Compare to active edges:

```sql
SELECT
  p.pmid,
  p.title,
  GROUP_CONCAT(DISTINCT CASE WHEN r.relation = 'RELEASES_DATASET' THEN e.name END) AS releases,
  GROUP_CONCAT(DISTINCT CASE WHEN r.relation = 'USES_DATASET' THEN e.name END) AS uses
FROM papers p
LEFT JOIN relations r ON r.source_pmid = p.pmid
  AND r.relation IN ('RELEASES_DATASET', 'USES_DATASET')
  AND COALESCE(r.status, 'active') = 'active'
LEFT JOIN entities e ON e.id = r.object_id
WHERE p.study_type = 'dataset_benchmark'
  AND p.pmid IN (/* pilot list */)
GROUP BY p.pmid, p.title;
```

**Pass:** ≥80% of sampled dataset rows agree (released set has `RELEASES_DATASET`; cited-only sets are not `RELEASES_DATASET`). Coexistence of `RELEASES_DATASET` + `USES_DATASET` for the same canonical name is allowed.

### Gate D — `foundation_model`: pretrain vs eval spot check

**Pass:** pretraining corpora → `PRETRAINS_ON`; finetune/eval/benchmark → `USES_DATASET`; no eval set labeled `PRETRAINS_ON`.

```sql
SELECT
  p.pmid,
  r.relation,
  e.name AS dataset,
  e.access_class,
  r.evidence_quote
FROM papers p
JOIN relations r ON r.source_pmid = p.pmid
JOIN entities e ON e.id = r.object_id AND e.type = 'Dataset'
WHERE p.study_type = 'foundation_model'
  AND r.relation IN ('PRETRAINS_ON', 'USES_DATASET')
  AND COALESCE(r.status, 'active') = 'active'
  AND p.pmid IN (/* pilot list */)
ORDER BY p.pmid, r.relation, e.name;
```

Confirm no active `RELEASES_DATASET` on foundation_model papers (policy: `pretrain_ok` only).

### Gate E — `ai_algorithm`: platform blacklist regression

**Pass:** `platform_hit = 0` in `pilot_reconcile_qa.py` CSV; no literature platforms as active Dataset.

```sql
SELECT p.pmid, e.name AS dataset, r.evidence_quote
FROM papers p
JOIN relations r ON r.source_pmid = p.pmid
JOIN entities e ON e.id = r.object_id
WHERE p.study_type = 'ai_algorithm'
  AND r.relation IN ('USES_DATASET', 'RELEASES_DATASET', 'PRETRAINS_ON')
  AND COALESCE(r.status, 'active') = 'active'
  AND p.pmid IN (/* pilot list */)
  AND (
    LOWER(e.name) IN (
      'pubmed', 'pubmed central', 'pmc', 'ncbi', 'ncbi geo', 'geo',
      'gene expression omnibus', 'google scholar', 'web of science',
      'scopus', 'medline', 'embase', 'cochrane library', 'cochrane',
      'sciencedirect', 'springer link', 'wiley online library'
    )
    OR LOWER(e.name) LIKE '%pubmed%'
    OR LOWER(e.name) LIKE '%scopus%'
  );
-- Expected: 0 rows (full list: extractor/dataset_access.py LITERATURE_PLATFORM_BLOCKLIST)
```

Also from extraction-quality baseline: unlisted LLM `public` → `access_class=unknown` unless alias-listed (`PUBLIC_DATASET_ALIASES`).

### Gate F — Reconcile hygiene (all types)

```sql
SELECT pmid, study_type, full_text_status, reconcile_status, reconcile_at
FROM papers
WHERE pmid IN (/* pilot list */)
ORDER BY study_type, pmid;
```

**Pass:** fulltext-ready papers → `reconcile_status IN ('done', 'failed')` (retry failures); abstract-only → `skipped_no_ft`.

---

## Step 5 — Unit regression (no live LLM)

Run before/after pilot code changes:

```bash
cd fulltext_workflow
python -m pytest \
  tests/test_study_policy.py \
  tests/test_study_prompts.py \
  tests/test_entity_normalize.py \
  tests/test_fulltext_reconcile.py \
  tests/test_study_classifier_prompt.py \
  tests/test_gap_study_type_stats.py \
  tests/test_dataset_access.py \
  -v
```

**Expected:** all tests PASS.

---

## Rollout checklist

- [ ] Stratified PMID list saved (`data/pilot_study_type_pmids.txt`)
- [ ] `extract --pmid-list … --force-reextract` completed
- [ ] Gates A–F reviewed; CSV archived under `output/`
- [ ] Unit regression PASS
- [ ] Only then: full-corpus re-extract or enable `STUDY_POLICY_ENABLED` for production runs
