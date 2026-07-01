# Pathology AI Knowledge Graph — Architecture Overview

> Last updated: 2026-05-28

---

## Table of Contents

1. [Project Purpose](#1-project-purpose)
2. [Repository Layout](#2-repository-layout)
3. [Data & Storage Layer](#3-data--storage-layer)
4. [Pipeline: End-to-End Flow](#4-pipeline-end-to-end-flow)
5. [Module Reference](#5-module-reference)
6. [Agent Architecture](#6-agent-architecture)
   - 6.1 [Gap Agent (`gap_agent.py`)](#61-gap-agent-gap_agentpy)
   - 6.2 [Idea Agent (`idea_agent.py`)](#62-idea-agent-idea_agentpy)
   - 6.3 [Tool Layer (`graph_tools.py`)](#63-tool-layer-graph_toolspy)
7. [Streamlit UI (`gap_ui.py`)](#7-streamlit-ui-gap_uipy)
8. [Configuration](#8-configuration)
9. [Inter-Component Dependency Graph](#9-inter-component-dependency-graph)

---

## 1. Project Purpose

This project builds a **Knowledge Graph (KG) of Pathology AI literature** and uses LLM-driven agents to automatically:

- Fetch and enrich papers from PubMed and Semantic Scholar.
- Extract structured triples (entities + relations) from abstracts using an LLM.
- Construct a NetworkX / SQLite-backed knowledge graph.
- Identify **research gaps** via SQL statistical analysis and graph topology analysis.
- Generate **research proposals** through an adversarial multi-agent loop.
- Visualize everything through an interactive Streamlit web UI.

---

## 2. Repository Layout

```
build_kg_paper/
├── main.py                  # CLI entry point — orchestrates all pipeline steps
├── config.py                # Central config (API keys, model name, paths)
├── search_queries.py        # PubMed query groups and date ranges
├── gap_agent.py             # Research gap analysis agent (LLM + 13 SQL tools)
├── idea_agent.py            # Research proposal agent (adversarial Generator–Critic)
├── graph_tools.py           # 5 NetworkX graph traversal tools (shared by agents)
├── gap_ui.py                # Streamlit web UI (real-time agent reasoning view)
├── graph_tools.py           # Graph traversal tools (PageRank, community, etc.)
│
├── fetcher/
│   ├── pubmed_fetcher.py    # Step 1 — PubMed efetch via Biopython Entrez
│   └── s2_fetcher.py        # Step 2 — Semantic Scholar batch enrichment
│
├── extractor/
│   └── triple_extractor.py  # Step 3 — LLM two-step extraction (study_type + triples)
│
├── graph/
│   └── kg_builder.py        # Step 4 — Build NetworkX MultiDiGraph from SQLite
│
├── utils/
│   ├── db.py                # SQLite schema, CRUD helpers, connection manager
│   └── if_importer.py       # Import journal impact factors from Excel
│
├── viz/
│   └── visualize.py         # Pyvis HTML export, CSV stats, GEXF/GraphML export
│
├── data/
│   └── unmatched_journals.csv
│
├── output/                  # All generated reports, graphs, CSVs
│   ├── kg_interactive.html
│   ├── kg_entities.html
│   └── gap_report_*.md
│
└── lib/                     # Vendored frontend JS/CSS (vis.js, tom-select)
```

---

## 3. Data & Storage Layer

### SQLite Database (`data/kg.db`)

All persistent state lives in a single SQLite file.  Connection management uses WAL mode and a context-manager helper in `utils/db.py`.

| Table | Purpose |
|---|---|
| `papers` | One row per unique paper (PMID, DOI, S2ID, title, abstract, year, study_type, citation_count …) |
| `journals` | Journal registry with optional impact factor & quartile |
| `authors` | Deduplicated author registry |
| `paper_authors` | M:N join between papers and authors |
| `entities` | Deduplicated entity registry (name, type: Disease / Method / Task / Tissue / Dataset / Metric) |
| `relations` | Triple store: `(subject_id, relation, object_id, source_pmid)` — typed relations such as `TARGETS_DISEASE`, `APPLIES_METHOD`, `PERFORMS_TASK`, `USES_DATASET` |
| `citations` | Paper → paper citation edges sourced from Semantic Scholar |

### Study Types (LLM-classified)

`ai_algorithm` · `clinical_study` · `review` · `meta_analysis` · `dataset_benchmark` · `foundation_model` · `multimodal` · `other`

---

## 4. Pipeline: End-to-End Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         python main.py run-all                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │  Step 1 — PubMed Fetch                  │
          │  fetcher/pubmed_fetcher.py               │
          │  • Entrez esearch/efetch                 │
          │  • Extracts: PMID, title, abstract,      │
          │    pub_date, journal, ISSN, authors,     │
          │    MeSH terms, pub_types                 │
          │  • Resume-safe (skips existing PMIDs)    │
          └────────────────────┬────────────────────┘
                               │  upsert → papers / journals / authors
                               ▼
          ┌────────────────────────────────────────────┐
          │  Step 2 — Semantic Scholar Enrichment       │
          │  fetcher/s2_fetcher.py                      │
          │  • /paper/batch endpoint (up to 500/req)    │
          │  • Adds: citation_count, open_access, s2id  │
          │  • Fetches citation edges → citations table │
          │  • Fallback abstract if PubMed was empty    │
          └────────────────────┬───────────────────────┘
                               │  update papers / insert citations
                               ▼
          ┌────────────────────────────────────────────┐
          │  Step 3 — LLM Triple Extraction             │
          │  extractor/triple_extractor.py              │
          │  Two-step per abstract:                     │
          │  ① Classify study_type  (cheap, 1 call)     │
          │  ② Extract entity+relation triples          │
          │     (Pydantic structured output)             │
          │  • Resume-safe (extraction_done flag)        │
          └────────────────────┬───────────────────────┘
                               │  upsert → entities / relations
                               ▼
          ┌────────────────────────────────────────────┐
          │  Step 4 — Knowledge Graph Build             │
          │  graph/kg_builder.py                        │
          │  • Loads SQLite → NetworkX MultiDiGraph      │
          │  • Optional: author nodes, citation edges    │
          │  • Filters: year range, study_type,          │
          │    min_citation_count                        │
          │  • Export: GEXF / GraphML                    │
          └────────────────────┬───────────────────────┘
                               │
                               ▼
          ┌────────────────────────────────────────────┐
          │  Visualization — viz/visualize.py            │
          │  • kg_interactive.html  (Pyvis, top-500)    │
          │  • kg_entities.html     (entity-only view)  │
          │  • kg_stats.csv                             │
          │  • top_entities.csv                         │
          │  • papers_by_journal.csv                    │
          └────────────────────────────────────────────┘
```

---

## 5. Module Reference

| Module | Role | Key Exports |
|---|---|---|
| `config.py` | Central config, reads `.env` | API keys, `DB_PATH`, `LLM_MODEL`, `TOOL_TOP_N` |
| `search_queries.py` | PubMed query groups | `PUBMED_QUERY_GROUPS`, year range |
| `utils/db.py` | DB schema + CRUD | `init_db()`, `get_conn()`, `upsert_paper()`, `upsert_entity()`, `insert_relation()` |
| `utils/if_importer.py` | Import impact factors | `import_impact_factors(xlsx)` |
| `fetcher/pubmed_fetcher.py` | PubMed fetch | `fetch_all_queries()` |
| `fetcher/s2_fetcher.py` | S2 enrichment | `enrich_from_s2()` |
| `extractor/triple_extractor.py` | LLM extraction | `run_extraction()`, Pydantic schemas |
| `graph/kg_builder.py` | Build NetworkX graph | `KGBuilder.build()`, `.export_gexf()`, `.sync_to_neo4j()` |
| `graph_tools.py` | Graph traversal tools | `GRAPH_TOOLS`, `GRAPH_TOOL_SCHEMAS` |
| `viz/visualize.py` | HTML/CSV/graph export | `export_pyvis()`, `run_all()` |
| `gap_agent.py` | Gap analysis agent | `stream_agent()`, `run_agent()`, 13 SQL tools |
| `idea_agent.py` | Proposal agent | `stream_idea_agent()`, `run_idea_agent()` |
| `gap_ui.py` | Streamlit UI | full reasoning trace, report view |
| `main.py` | CLI pipeline | `fetch`, `extract`, `build`, `run-all`, `stats` |

---

## 6. Agent Architecture

### 6.1 Gap Agent (`gap_agent.py`)

The gap agent is a **single-LLM ReAct-style agent** that iteratively calls KG tools to collect evidence, then synthesises a research gap report.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        stream_agent(focus, top_n)                      │
│                                                                        │
│   ┌─────────────┐   system prompt + user msg    ┌──────────────────┐  │
│   │  messages[] │ ──────────────────────────────► LLM              │  │
│   │             │ ◄────────────────────────────── (OpenAI-compat.) │  │
│   └─────────────┘        AssistantMessage        └────────┬─────────┘  │
│          ▲                                                │            │
│          │  tool result                        tool_calls?│            │
│          │                                               ▼            │
│   ┌──────┴──────────────────────────────────────────────────────────┐ │
│   │                    Tool Dispatcher                               │ │
│   │                                                                  │ │
│   │   SQL Tools (13)                   Graph Tools (5)               │ │
│   │   ─────────────────────────        ──────────────────────────    │ │
│   │   trend_overview                   graph_entity_pagerank         │ │
│   │   hotspot_entities                 graph_structural_holes        │ │
│   │   disease_task_coverage            graph_community_gaps          │ │
│   │   method_clinical_gap              graph_disease_method_reach    │ │
│   │   dataset_scarcity                 graph_citation_pagerank       │ │
│   │   underexplored_disease                                          │ │
│   │   emerging_methods                 ↓ all lazily load the         │ │
│   │   method_disease_combo_gap           NetworkX graph from SQLite  │ │
│   │   foundation_model_gaps                                          │ │
│   │   multimodal_gaps                                                │ │
│   │   recent_highcite_papers                                         │ │
│   │   method_cooccurrence                                            │ │
│   │   low_impact_direction                                           │ │
│   └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│   Loop until finish_reason == "stop"  OR  max_iterations reached       │
│   Yields event dicts: start / tool_call / tool_result / tool_error /  │
│                        thinking / final / error                        │
└────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼  final Markdown report
                      output/gap_report_*.md
```

**Event stream** (yielded by `stream_agent`):

| Event type | Payload fields | Description |
|---|---|---|
| `start` | `focus`, `top_n` | Agent initialised |
| `tool_call` | `name`, `args`, `call_id` | LLM requested a tool |
| `tool_result` | `name`, `result`, `call_id` | Tool returned data |
| `tool_error` | `name`, `error`, `call_id` | Tool raised exception |
| `thinking` | `content` | LLM reasoning text alongside tool calls |
| `final` | `content` | Completed Markdown report |
| `error` | `content` | Agent hit max iterations |

---

### 6.2 Idea Agent (`idea_agent.py`)

The idea agent implements an **adversarial multi-agent loop** to iteratively produce and critique a research proposal.

```
┌───────────────────────────────────────────────────────────────────────────┐
│               stream_idea_agent(gap_text, max_rounds)                     │
│                                                                           │
│   Input: research gap description (text from gap_agent output)           │
│                                                                           │
│   ┌─────────────────────────────────────────────────────────────────┐    │
│   │                    Round  1 … N                                  │    │
│   │                                                                  │    │
│   │   ┌──────────────────────────────────────────────────────────┐  │    │
│   │   │  GENERATOR AGENT                                          │  │    │
│   │   │  • System: proposal writer role                           │  │    │
│   │   │  • Has access to full tool set (13 SQL + 5 graph)         │  │    │
│   │   │  • Calls KG tools to gather supporting evidence           │  │    │
│   │   │  • Produces / revises structured research proposal draft  │  │    │
│   │   └────────────────────────┬─────────────────────────────────┘  │    │
│   │                            │ draft (Markdown)                   │    │
│   │                            ▼                                    │    │
│   │   ┌──────────────────────────────────────────────────────────┐  │    │
│   │   │  CRITIC AGENT                                             │  │    │
│   │   │  • System: adversarial reviewer role                      │  │    │
│   │   │  • Has access to full tool set (fact-checks claims)       │  │    │
│   │   │  • Returns structured feedback JSON:                      │  │    │
│   │   │      score (0–10), dimension_scores, strengths,           │  │    │
│   │   │      critical_issues, revision_priority                   │  │    │
│   │   └────────────────────────┬─────────────────────────────────┘  │    │
│   │                            │ feedback                           │    │
│   │                            ▼                                    │    │
│   │          score >= ACCEPT_SCORE  OR  round == max_rounds?        │    │
│   │              YES ──► finalise          NO ──► next round        │    │
│   └─────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│   Yields: start / round_start / tool_call / tool_result / tool_error /   │
│           thinking / draft / feedback / final / error                     │
└───────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼  final Markdown proposal
                      output/proposal_*.md  (or printed to stdout)
```

**Event stream** (yielded by `stream_idea_agent`):

| Event type | Payload fields | Description |
|---|---|---|
| `start` | `gap_text` | Agent loop initialised |
| `round_start` | `round`, `max_rounds` | New adversarial round started |
| `tool_call` | `role`, `name`, `args`, `call_id` | Generator or Critic called a tool |
| `tool_result` | `role`, `name`, `result`, `call_id` | Tool returned data |
| `tool_error` | `role`, `name`, `error`, `call_id` | Tool raised exception |
| `thinking` | `role`, `content` | LLM reasoning trace |
| `draft` | `round`, `content` | Generator produced a draft |
| `feedback` | `round`, `content`, `score`, `accept`, `dimension_scores`, `strengths`, `critical_issues` | Critic feedback |
| `final` | `content`, `rounds`, `final_score` | Accepted proposal |
| `error` | `content` | Loop limit or error |

---

### 6.3 Tool Layer (`graph_tools.py`)

Five graph traversal tools complement the 13 SQL tools. They share a lazy-loaded cache of two graphs:

| Internal graph | Type | Built from |
|---|---|---|
| `_FULL_GRAPH` | `nx.MultiDiGraph` | Full KG including citation edges (`KGBuilder.build`) |
| `_ENTITY_COOC_GRAPH` | `nx.Graph` (undirected) | Entity co-occurrence within papers (edge weight = shared paper count) |

| Tool | Algorithm | Research gap signal |
|---|---|---|
| `graph_entity_pagerank` | PageRank on entity co-occurrence graph | High PageRank + low paper count → structurally important but under-studied |
| `graph_structural_holes` | Betweenness centrality | High betweenness + low paper count → bridge between research communities |
| `graph_community_gaps` | Louvain community detection | Isolated clusters → cross-community research opportunity |
| `graph_disease_method_reach` | 2-hop BFS reachability | Disease can reach a method in 2 hops but no direct paper → transferable technique |
| `graph_citation_pagerank` | PageRank on citation graph vs raw citation count | High citation PR + low raw citations → hidden gem paper |

All tools return `{"description": str, "data": list[dict]}` compatible with the tool dispatcher in both agents.

---

## 7. Streamlit UI (`gap_ui.py`)

```
streamlit run gap_ui.py
                │
                ▼
┌───────────────────────────────────────────────────┐
│  Sidebar                                           │
│  • Focus keyword input                             │
│  • Top-N recommendations slider                   │
│  • Max adversarial rounds (idea agent)             │
│  • Tool legend / category filter                   │
└───────────────────────┬───────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        │                               │
        ▼                               ▼
┌───────────────────┐          ┌────────────────────────┐
│  Gap Analysis Tab │          │  Idea Generator Tab     │
│                   │          │                         │
│  stream_agent()   │          │  stream_idea_agent()    │
│  ─────────────    │          │  ─────────────────      │
│  Real-time tool   │          │  Round-by-round         │
│  call trace       │          │  draft + critic cards   │
│                   │          │                         │
│  Expandable data  │          │  Score timeline chart   │
│  tables per tool  │          │  Final proposal view    │
│                   │          │                         │
│  Final Markdown   │          │  Download .md button    │
│  report render    │          │                         │
└───────────────────┘          └────────────────────────┘
```

---

## 8. Configuration

All settings are read from environment variables (`.env` file, loaded via `python-dotenv`):

| Variable | Default | Description |
|---|---|---|
| `PUBMED_API_KEY` | `` | NCBI API key (raises rate limit to 10 req/s) |
| `PUBMED_EMAIL` | `your@email.com` | Required by Entrez |
| `S2_API_KEY` | `` | Semantic Scholar key (100 req/s vs 1 req/s) |
| `OPENAI_API_KEY` | `` | LLM API key |
| `OPENAI_API_BASE` | DashScope Qwen endpoint | OpenAI-compatible base URL |
| `LLM_MODEL` | `qwen3-235b-a22b-instruct-2503` | Model identifier |
| `LLM_MAX_TOKENS` | `65536` | Max tokens per LLM response |
| `TOOL_TOP_N` | `30` | SQL tool result row limit |
| `GRAPH_TOP_N` | `25` | Graph tool result row limit |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | localhost defaults | Optional Neo4j export |
| `USE_NEO4J` | `false` | Enable Neo4j sync in `build` step |

Search query groups and date ranges are defined in `search_queries.py`.

---

## 9. Inter-Component Dependency Graph

```
                     ┌──────────────┐
                     │   config.py  │
                     │  search_     │
                     │  queries.py  │
                     └──────┬───────┘
                            │ imported by all modules
                            ▼
                     ┌──────────────┐
                     │  utils/db.py │◄──────────────────────────────┐
                     │  (SQLite)    │                               │
                     └──────┬───────┘                               │
              ┌─────────────┼─────────────────┐                     │
              ▼             ▼                 ▼                     │
  ┌─────────────────┐ ┌──────────────┐ ┌───────────────┐           │
  │ pubmed_fetcher  │ │  s2_fetcher  │ │triple_extractor│           │
  │  (Step 1)       │ │  (Step 2)    │ │  (Step 3)      │           │
  └─────────────────┘ └──────────────┘ └───────────────┘           │
                                              │                     │
                                              ▼                     │
                                   ┌──────────────────┐            │
                                   │  graph/kg_builder │            │
                                   │  (Step 4)         │◄───────────┤
                                   └────────┬──────────┘            │
                                            │ nx.MultiDiGraph        │
                              ┌─────────────┼────────────┐          │
                              ▼             ▼            ▼          │
                    ┌─────────────┐  ┌──────────────┐   │          │
                    │viz/visualize│  │ graph_tools  │   │          │
                    │ (HTML/CSV)  │  │ (5 tools)    │   │          │
                    └─────────────┘  └──────┬───────┘   │          │
                                            │           │          │
                              ┌─────────────┴───────────┘          │
                              ▼                                     │
                    ┌──────────────────┐   ┌──────────────────┐    │
                    │   gap_agent.py   │   │  idea_agent.py   │    │
                    │  (13 SQL tools   │   │ (Generator +     │    │
                    │  + 5 graph tools)│   │  Critic agents)  │    │
                    └────────┬─────────┘   └────────┬─────────┘    │
                             │                      │              │
                             └──────────┬───────────┘              │
                                        ▼                          │
                               ┌─────────────────┐                │
                               │    gap_ui.py     │                │
                               │  (Streamlit UI)  │                │
                               └─────────────────┘                │
                                                                   │
                    ┌──────────────────────────────────────────────┘
                    │  utils/if_importer.py  (optional IF import)
                    │  add_indexes.py        (optional DB indexes)
                    │  db_quality_check.py   (data QA)
                    └──────────────────────────────────────────────
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env   # fill in API keys

# 3. Run full pipeline
python main.py run-all

# 4. Optional: import journal impact factors
python main.py import-if data/journals_if.xlsx

# 5. Launch web UI
streamlit run gap_ui.py

# 6. CLI gap analysis
python gap_agent.py --focus "lung cancer" --top 8 --output output/my_report.md

# 7. CLI proposal generation
python idea_agent.py --gap "No foundation model for gastric cancer pathology" --rounds 3
```
