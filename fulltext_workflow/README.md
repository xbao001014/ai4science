# Full-Text Workflow Sandbox

Isolated test pipeline for **pathology AI** literature (same PubMed query groups as the main project in `search_queries.py`, default **2015–2025**) with PMC full-text fetch, section-aware KG extraction, and gap analysis.

Does **not** modify the main pipeline or `data/kg_papers.db`.

## Prerequisites

- Python dependencies from repo root: `pip install -r requirements.txt`
- API keys in repo root `.env`:
  - `PUBMED_EMAIL`, `PUBMED_API_KEY` (recommended)
  - `DASHSCOPE_API_KEY` / `OPENAI_API_KEY`, `OPENAI_API_BASE`, `LLM_MODEL` (default: 百炼 `deepseek-v4-flash`)
  - Optional context: `LLM_MAX_INPUT_CHARS=800000` (~200k tokens), `LLM_MAX_TOKENS=16384`

## Search Scope

PubMed queries and year range are imported from the repo-root [`search_queries.py`](../search_queries.py) (same 14 enabled groups as the main pipeline, default **2015–2025**). Edit that file to add or disable query groups; both pipelines stay in sync.

Optional sandbox-only year override in `.env`:

```
FULLTEXT_SEARCH_YEAR_START=2024
FULLTEXT_SEARCH_YEAR_END=2026
FETCH_EDAT_DAYS=14    # weekly incremental: last N days [EDAT] on fetch
```

### LLM（百炼调用 DeepSeek）

默认通过百炼 OpenAI 兼容接口调用 `deepseek-v4-flash`：

```
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=sk-xxx          # 百炼 API Key
LLM_MODEL=deepseek-v4-flash
```

其他地域 Base URL 见[百炼地域文档](https://help.aliyun.com/zh/model-studio/regions/)。直连 DeepSeek 官方 API 时改为 `https://api.deepseek.com`。

## Quick Start

See **[PIPELINE.md](PIPELINE.md)** for the full step-by-step guide and `run_pipeline.ps1` helper script.

```bash
cd fulltext_workflow
python main.py run-all --limit 30
```

## Step-by-Step

```bash
python main.py init
python main.py fetch                     # PubMed metadata (all matching PMIDs)
python main.py fetch-fulltext            # JATS → PDF/MinerU → mark unavailable
python main.py enrich-s2                 # Citation counts via OpenAlex (or S2)
python main.py import-if data/journals_if.xlsx   # Journal IF / quartile (optional)
python main.py extract --limit 30        # LLM: fulltext / mineru_pdf / abstract
python main.py build                     # NetworkX KG → GEXF + HTML
python main.py viz                       # Regenerate kg_entities.html only
python main.py analyze                   # Static SQL report (no LLM)
python main.py gap-debate                # Debate multi-agent gap report (LLM)
python main.py gap-debate --focus radiomics --top 5 -o output/gap_debate.md
python main.py stats
```

## Idea Pipeline（研究空白 → 数据可行性核验 → 假说生成）

Closed-loop workflow aligned with [`pathology_data_api_spec.md`](../pathology_data_api_spec.md). Uses **Fangxin LIS live API** (`http://ai.gzfxyl.cn`, see [`api_document.md`](../api_document.md)).

```bash
# Phase 0: load pathology data landscape from API into SQLite
python main.py bootstrap-landscape --force

# Full pipeline (requires KG + OPENAI_API_KEY)
python main.py idea-pipeline --focus radiomics --top 3 -o output/idea_pipeline_report.md

# Feasibility only (skip LLM proposal generation)
python main.py idea-pipeline --skip-debate --gap-report output/gap_debate_report.md --skip-ideas

# Resume from existing gap report
python main.py idea-pipeline --skip-debate --gap-report output/gap_debate_report.md --top 2
```

| Stage | Module | Description |
|-------|--------|-------------|
| 1 | `gap_agent.py` | Optimist × Skeptic × Moderator → research gaps |
| 2 | `feasibility/client.py` | V-01 assess + V-02 gap analysis (Fangxin API) |
| 2b | `evolution_agent.py` | Refine hypothesis when score 0.5–0.8 |
| 3 | `idea_agent.py` | Generator × Critic with `feasibility_assess` gate |

Run unit tests (no LLM):

```bash
python tests/test_feasibility.py
```

Output: `output/idea_pipeline_report.md` — cross matrix, feasibility table, evolution log, proposals.

## Gap Debate UI (Streamlit)

Interactive five-tab UI (Debate Process, Evidence, Gap Report, **Data Feasibility**, Research Proposal):

```bash
cd fulltext_workflow
..\.venv\Scripts\streamlit.exe run gap_ui.py   # Windows (recommended)
# or:  .\run_gap_ui.ps1
# or:  .\run_gap_ui.bat
streamlit run gap_ui.py                        # only if streamlit is from project .venv
```

Requires `OPENAI_API_KEY` in repo root `.env` for debate and proposal agents.

## Agent Architecture

| Module | Role |
|--------|------|
| `gap_agent.py` | Optimist x Skeptic x Moderator debate loop (Scheme C) |
| `idea_agent.py` | Generator x Critic proposal refinement + feasibility tools |
| `pipeline.py` | End-to-end idea-pipeline orchestrator |
| `feasibility/` | Fangxin pathology LIS HTTP client (D-01 … V-02) |
| `evolution_agent.py` | V-02 driven hypothesis refinement |
| `gap_ui.py` | Streamlit UI mirroring root project four-tab experience |
| `analysis/gap_tools.py` | SQL gap tools + citation/IF impact ranking |
| `analysis/impact_scoring.py` | cross_priority_score / impact_tier helpers |
| `analysis/feasibility_tools.py` | 5 pathology feasibility LLM tools |
| `analysis/graph_tools.py` | 3 graph tools (PageRank, community, reachability) |

## Data Locations

| Path | Purpose |
|------|---------|
| `data/kg_fulltext.db` | Independent SQLite database |
| `raw/pmc_xml/` | Cached PMC JATS XML |
| `raw/pdfs/` | ScanSci-downloaded PDFs |
| `raw/mineru_output/` | MinerU markdown cache per PMID |
| `output/kg_fulltext.gexf` | Graph export |
| `output/kg_fulltext_interactive.html` | Paper + Entity relation graph (Pyvis) |
| `output/kg_entities.html` | Entity co-occurrence / relation projection |
| `output/gap_report.md` | Static gap analysis report |
| `output/gap_debate_report.md` | Debate agent gap report (CLI default output) |
| `output/idea_pipeline_report.md` | Full pipeline report (gaps + feasibility + proposals) |

## Full-Text Coverage

Three-tier full-text acquisition at `fetch-fulltext`, then abstract fallback at `extract`:

1. **Europe PMC JATS** (primary): batch PMID lookup + `fullTextXML` → structured sections
2. **ScanSci PDF + MinerU** (fallback when JATS unavailable): OA-first PDF download, MinerU markdown parse → pseudo-sections
3. **Abstract only** (last resort): `extraction_granularity=abstract` when both tiers fail

Extra dependencies (install in project venv):

```bash
pip install scansci-pdf "mineru[core]"
```

Optional env vars (repo `.env`):

- `SCANSCI_STRATEGY=oa_first` (default)
- `MINERU_MODEL_SOURCE=modelscope` (recommended on CN networks)
- `MINERU_BACKEND=pipeline`
- `MINERU_DEVICE=auto` (default: CUDA if available, else CPU; set `cpu` to force CPU)

Cached artifacts: `raw/pmc_xml/`, `raw/pdfs/`, `raw/mineru_output/`.

## Gap Research — Citation & IF Weighting

After `fetch` + `extract`, enrich metadata for priority ranking in Gap Debate:

```bash
python main.py enrich-s2              # OpenAlex by default; S2 if CITATION_PROVIDER=semantic_scholar
python main.py import-if path/to/journals_if.xlsx
```

If Semantic Scholar returns **403 Forbidden**, set in `.env`:

```
CITATION_PROVIDER=openalex
```

(`auto` probes S2 once, then falls back to OpenAlex.)

`cross_priority_score` = literature gap + LIS cohort + **impact_score** (citations + IF).

Optional `.env` (repo root):

```
PATHOLOGY_API_BASE_URL=http://ai.gzfxyl.cn/api/v1/pathology
PATHOLOGY_API_KEY=your-key
PATHOLOGY_DATA_PROVIDER=api
PATHOLOGY_BOOTSTRAP_MIN_CASES=1
```

Use `PATHOLOGY_DATA_PROVIDER=mock` for offline tests (`feasibility/mock_data/`).

Optional env weights: `GAP_WEIGHT_EVIDENCE`, `GAP_WEIGHT_IMPACT`, `GAP_WEIGHT_FEASIBILITY` (default 1.0 each).

New gap tools: `limitation_impact_rank`, `hotspot_entities`, `recent_highcite_papers`, `literature_impact_priority_matrix`.

Run from repo root with the project venv:

```bash
cd fulltext_workflow
../.venv/Scripts/python.exe main.py run-all --limit 30   # Windows
# python main.py run-all --limit 30                      # Linux/macOS
```

## Schema Extensions vs Main Pipeline

- `document_sections` — parsed JATS sections
- `papers.pmc_id`, `full_text_status`
- `relations.evidence_section`, `evidence_quote`, `extraction_granularity`, `polarity`
- Entity types: `Modality`, `Limitation`
- Relations: `REPORTS_LIMITATION`, `USES_MODALITY`

## LLM Cost Estimate

~30 papers × (1 study_type + ~3–4 section calls) ≈ 120–150 API calls.
