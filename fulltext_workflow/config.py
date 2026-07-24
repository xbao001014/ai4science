"""Configuration for the isolated full-text workflow sandbox."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _ROOT.parent

# override=True: project .env wins over stale shell env for keys defined in the file
load_dotenv(_REPO_ROOT / ".env", override=True)
load_dotenv(_ROOT / ".env", override=True)
_ENV_FILE = {
    **dotenv_values(_REPO_ROOT / ".env"),
    **{k: v for k, v in dotenv_values(_ROOT / ".env").items() if v},
}


def _env_first(*names: str, default: str = "") -> str:
    """Prefer values from project .env over inherited shell environment."""
    for name in names:
        val = _ENV_FILE.get(name) or os.getenv(name)
        if val:
            return val
    return default

# Reuse main-project PubMed query groups and year range (search_queries.py)
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from search_queries import (  # noqa: E402
    MAX_RESULTS_PER_QUERY,
    PUBMED_QUERY_GROUPS,
    SEARCH_YEAR_END,
    SEARCH_YEAR_START,
    get_enabled_groups,
)

# ── Paths (all relative to fulltext_workflow/) ───────────────────────────────
DB_PATH: str = str(_ROOT / "data" / "kg_fulltext.db")
OUTPUT_DIR: str = str(_ROOT / "output")
DATA_DIR: str = str(_ROOT / "data")
RAW_PMC_DIR: str = str(_ROOT / "raw" / "pmc_xml")
RAW_PDF_DIR: str = str(_ROOT / "raw" / "pdfs")
MINERU_OUTPUT_DIR: str = str(_ROOT / "raw" / "mineru_output")

# ── PDF fallback (ScanSci + MinerU) ──────────────────────────────────────────
SCANSCI_STRATEGY: str = os.getenv("SCANSCI_STRATEGY", "oa_first")
SCANSCI_RATE_DELAY: float = float(os.getenv("SCANSCI_RATE_DELAY", "1.0"))
MINERU_BACKEND: str = os.getenv("MINERU_BACKEND", "pipeline")
MINERU_MODEL_SOURCE: str = os.getenv("MINERU_MODEL_SOURCE", "modelscope")
MINERU_LANG: str = os.getenv("MINERU_LANG", "en")
# auto: CUDA if available, else CPU; override with cuda | cpu
MINERU_DEVICE: str = os.getenv("MINERU_DEVICE", "auto")

# ── Citation / IF enrichment (gap research weighting) ────────────────────────
S2_API_KEY: str = os.getenv("S2_API_KEY", "")
# auto: try S2 if key works, else OpenAlex | openalex | semantic_scholar
CITATION_PROVIDER: str = os.getenv("CITATION_PROVIDER", "auto")
JCR_IF_PATH: str = str(_ROOT / "data" / "jcr.csv")
JCR_IF_YEAR: int = int(os.getenv("JCR_IF_YEAR", "2024"))
JOURNAL_FUZZY_THRESHOLD: int = int(os.getenv("JOURNAL_FUZZY_THRESHOLD", "85"))
GAP_WEIGHT_EVIDENCE: float = float(os.getenv("GAP_WEIGHT_EVIDENCE", "1.0"))
GAP_WEIGHT_IMPACT: float = float(os.getenv("GAP_WEIGHT_IMPACT", "1.0"))
GAP_WEIGHT_FEASIBILITY: float = float(os.getenv("GAP_WEIGHT_FEASIBILITY", "1.0"))
GAP_RECENT_YEARS: int = int(os.getenv("GAP_RECENT_YEARS", "3"))
# Max age (as_of_year - first_year) to still count as emerging; default = GAP_RECENT_YEARS
GAP_EMERGING_MAX_AGE: int = int(
    os.getenv("GAP_EMERGING_MAX_AGE", str(GAP_RECENT_YEARS))
)
# Papers with year <= first_year + GAP_EARLY_YEARS count as early (proposal window)
GAP_EARLY_YEARS: int = int(os.getenv("GAP_EARLY_YEARS", "1"))
GAP_PERSISTENT_RATIO: float = float(os.getenv("GAP_PERSISTENT_RATIO", "0.3"))
GAP_RESOLUTION_MIN_FOLLOWUP: int = int(os.getenv("GAP_RESOLUTION_MIN_FOLLOWUP", "2"))
# Batch resolution: skip emerging (recent-only limitations); comma-separated statuses
GAP_LIFECYCLE_RESOLUTION_STATUSES: frozenset[str] = frozenset(
    s.strip()
    for s in os.getenv(
        "GAP_LIFECYCLE_RESOLUTION_STATUSES", "persistent,declining"
    ).split(",")
    if s.strip()
)
GAP_LIFECYCLE_UPSERT_CHUNK: int = int(os.getenv("GAP_LIFECYCLE_UPSERT_CHUNK", "2000"))

# ── Search scope (from repo-root search_queries.py) ──────────────────────────
# Override years via env if needed, e.g. FULLTEXT_SEARCH_YEAR_START=2024
SEARCH_YEAR_START = int(os.getenv("FULLTEXT_SEARCH_YEAR_START", str(SEARCH_YEAR_START)))
SEARCH_YEAR_END = int(os.getenv("FULLTEXT_SEARCH_YEAR_END", str(SEARCH_YEAR_END)))

# Weekly incremental fetch: limit PubMed search to recently indexed records (EDAT).
# 0 = disabled (full year-window search). CLI --since-days overrides this.
FETCH_EDAT_DAYS: int = int(os.getenv("FETCH_EDAT_DAYS", "0"))

# Weekly hotspot detection (papers.pub_date publication window; day/month precision)
def _default_hotspot_window() -> int:
    explicit = os.getenv("HOTSPOT_WINDOW_DAYS")
    if explicit:
        return int(explicit)
    if FETCH_EDAT_DAYS > 0:
        return FETCH_EDAT_DAYS
    return 14


HOTSPOT_WINDOW_DAYS: int = _default_hotspot_window()
HOTSPOT_PRIOR_WINDOW_DAYS: int = int(os.getenv("HOTSPOT_PRIOR_WINDOW_DAYS", "14"))
HOTSPOT_MIN_RECENT_PAPERS: int = int(os.getenv("HOTSPOT_MIN_RECENT_PAPERS", "2"))
HOTSPOT_TOP_N: int = int(os.getenv("HOTSPOT_TOP_N", "20"))

# Weekly ops memory (gap soft-dedup + persist)
OPS_MEMORY_ENABLED: bool = os.getenv("OPS_MEMORY_ENABLED", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
OPS_MEMORY_LOOKBACK_RUNS: int = int(os.getenv("OPS_MEMORY_LOOKBACK_RUNS", "4"))
OPS_MEMORY_JACCARD_THRESHOLD: float = float(
    os.getenv("OPS_MEMORY_JACCARD_THRESHOLD", "0.55")
)
OPS_MEMORY_SECTION_MAX_CHARS: int = int(
    os.getenv("OPS_MEMORY_SECTION_MAX_CHARS", "8192")
)


def search_scope_label() -> str:
    n = len(get_enabled_groups())
    return f"pathology AI ({n} groups, {SEARCH_YEAR_START}-{SEARCH_YEAR_END})"

# ── API keys ─────────────────────────────────────────────────────────────────
PUBMED_API_KEY: str = os.getenv("PUBMED_API_KEY", "")
PUBMED_EMAIL: str = os.getenv("PUBMED_EMAIL", "your@email.com")

OPENAI_API_BASE: str = _env_first(
    "OPENAI_API_BASE", default="https://dashscope.aliyuncs.com/compatible-mode/v1"
)
OPENAI_API_KEY: str = _env_first(
    "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY"
)
LLM_MODEL: str = _env_first("LLM_MODEL", default="deepseek-v4-flash")
# extract: section triple extraction; agent: gap-debate / idea-pipeline / gap_ui
LLM_MODEL_EXTRACT: str = _env_first("LLM_MODEL_EXTRACT", default=LLM_MODEL)
LLM_MODEL_AGENT: str = _env_first("LLM_MODEL_AGENT", default="qwen3.7-plus")
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "16384"))
LLM_MAX_INPUT_CHARS: int = int(os.getenv("LLM_MAX_INPUT_CHARS", "800000"))
LLM_MAX_TOOL_RESULT_CHARS: int = int(
    os.getenv("LLM_MAX_TOOL_RESULT_CHARS", "100000")
)
LLM_TEMPERATURE: float = 0.0
LLM_RETRY_ATTEMPTS: int = int(os.getenv("LLM_RETRY_ATTEMPTS", "6"))
LLM_RETRY_DELAY: float = float(os.getenv("LLM_RETRY_DELAY", "3.0"))
LLM_REQUEST_TIMEOUT: float = float(os.getenv("LLM_REQUEST_TIMEOUT", "180"))
# Global throttle for 百炼/DashScope (avoid 429 / connection resets)
LLM_MIN_INTERVAL: float = float(os.getenv("LLM_MIN_INTERVAL", "2.0"))
LLM_MAX_CONCURRENT: int = int(os.getenv("LLM_MAX_CONCURRENT", "1"))
LLM_RATE_LIMIT_COOLDOWN: float = float(os.getenv("LLM_RATE_LIMIT_COOLDOWN", "45"))

DEFAULT_EXTRACT_LIMIT: int = 30
# Extraction speed: core sections ~6 calls/paper vs all ~22 (skip other/intro)
EXTRACT_CORE_ONLY: bool = os.getenv("EXTRACT_CORE_ONLY", "true").lower() == "true"
# When core sections are empty/empty-yield, promote long `other` body as discussion
EXTRACT_OTHER_FALLBACK_MIN_CHARS: int = int(
    os.getenv("EXTRACT_OTHER_FALLBACK_MIN_CHARS", "1500")
)
EXTRACT_SECTION_WORKERS: int = int(os.getenv("EXTRACT_SECTION_WORKERS", "1"))
EXTRACT_PAPER_WORKERS: int = int(os.getenv("EXTRACT_PAPER_WORKERS", "1"))
EXTRACT_MAX_SECTION_CHARS: int = int(os.getenv("EXTRACT_MAX_SECTION_CHARS", "12000"))
EXTRACT_SKIP_STUDY_LLM: bool = os.getenv("EXTRACT_SKIP_STUDY_LLM", "false").lower() == "true"
TOOL_TOP_N: int = int(os.getenv("TOOL_TOP_N", "30"))
GRAPH_TOP_N: int = int(os.getenv("GRAPH_TOP_N", "25"))
GRAPH_REACH_PAPER_SAMPLE: int = int(os.getenv("GRAPH_REACH_PAPER_SAMPLE", "40"))
# Cap co-occurrence clique size per paper (O(k^2) edges); keeps PR quality for hubs
GRAPH_MAX_ENTITIES_PER_PAPER: int = int(os.getenv("GRAPH_MAX_ENTITIES_PER_PAPER", "40"))

STUDY_TYPES: list[str] = [
    "ai_algorithm",
    "clinical_study",
    "review",
    "meta_analysis",
    "dataset_benchmark",
    "foundation_model",
    "multimodal",
    "other",
]

ENTITY_TYPES: list[str] = [
    "Disease",
    "Method",
    "Task",
    "Tissue",
    "Dataset",
    "Metric",
    "Modality",
    "Limitation",
]

SECTION_TYPES: list[str] = [
    "abstract",
    "introduction",
    "methods",
    "results",
    "discussion",
    "limitations",
    "future_work",
    "other",
]

SECTIONS_FOR_EXTRACTION: dict[str, list[str]] = {
    "methods": ["Method", "Dataset", "Task", "Modality"],
    "results": ["Metric", "Method", "Dataset"],
    "discussion": ["Limitation", "Modality", "Disease", "Task"],
    "limitations": ["Limitation"],
    "future_work": ["Limitation", "Task"],
}

# ── Pathology data feasibility (Fangxin LIS API) ─────────────────────────────
PATHOLOGY_API_BASE_URL: str = os.getenv(
    "PATHOLOGY_API_BASE_URL", "http://ai.gzfxyl.cn/api/v1/pathology"
)
PATHOLOGY_API_KEY: str = os.getenv("PATHOLOGY_API_KEY", "")
PATHOLOGY_API_TIMEOUT: float = float(os.getenv("PATHOLOGY_API_TIMEOUT", "60"))
PATHOLOGY_API_RETRIES: int = int(os.getenv("PATHOLOGY_API_RETRIES", "3"))
# api = live Fangxin API; mock = offline landscape.json fixtures (tests)
PATHOLOGY_DATA_PROVIDER: str = os.getenv("PATHOLOGY_DATA_PROVIDER", "api")
PATHOLOGY_BOOTSTRAP_MIN_CASES: int = int(os.getenv("PATHOLOGY_BOOTSTRAP_MIN_CASES", "1"))
PATHOLOGY_BOOTSTRAP_MAX_DISEASES: int = int(os.getenv("PATHOLOGY_BOOTSTRAP_MAX_DISEASES", "30"))
MOCK_DATA_DIR: str = str(_ROOT / "feasibility" / "mock_data")
FEASIBILITY_SCORE_APPROVE: float = 0.8
FEASIBILITY_SCORE_REJECT: float = 0.2
FEASIBILITY_SCORE_MARGINAL: float = 0.5

# Implementation difficulty (proposal target / assessed)
DIFFICULTY_Q1_HARD: float = float(os.getenv("DIFFICULTY_Q1_HARD", "0.55"))
DIFFICULTY_Q1_MODERATE: float = float(os.getenv("DIFFICULTY_Q1_MODERATE", "0.25"))
DIFFICULTY_IF_HARD: float = float(os.getenv("DIFFICULTY_IF_HARD", "8.0"))
DIFFICULTY_IF_MODERATE: float = float(os.getenv("DIFFICULTY_IF_MODERATE", "3.0"))
DIFFICULTY_Q_COVERAGE_LOW: float = float(os.getenv("DIFFICULTY_Q_COVERAGE_LOW", "0.4"))
DIFFICULTY_FX_EASY_SCORE: float = float(os.getenv("DIFFICULTY_FX_EASY_SCORE", "0.8"))
DIFFICULTY_FX_EASY_COHORT: int = int(os.getenv("DIFFICULTY_FX_EASY_COHORT", "500"))
DIFFICULTY_FX_MOD_SCORE: float = float(os.getenv("DIFFICULTY_FX_MOD_SCORE", "0.5"))
DIFFICULTY_FX_MOD_COHORT: int = int(os.getenv("DIFFICULTY_FX_MOD_COHORT", "200"))

# Public dataset feasibility (V-03) — parallel to Fangxin V-01
V03_OK_MIN_PAPERS: int = int(os.getenv("V03_OK_MIN_PAPERS", "3"))
V03_SCORE_ALIAS_BONUS: float = float(os.getenv("V03_SCORE_ALIAS_BONUS", "0.25"))
V03_SCORE_PER_PUBLIC: float = float(os.getenv("V03_SCORE_PER_PUBLIC", "0.15"))
V03_SCORE_COVERAGE_CAP: float = float(os.getenv("V03_SCORE_COVERAGE_CAP", "1.0"))
V03_EXAMPLE_PMIDS: int = int(os.getenv("V03_EXAMPLE_PMIDS", "3"))
V03_MAX_PUBLIC_FOR_SCORE: int = int(os.getenv("V03_MAX_PUBLIC_FOR_SCORE", "4"))
