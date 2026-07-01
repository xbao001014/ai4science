"""
Central configuration for the Pathology AI Knowledge Graph pipeline.
All API keys, query groups, model settings, and constants are defined here.
Copy .env.example to .env and fill in your credentials.
"""
from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Search queries are maintained in search_queries.py
# ─────────────────────────────────────────────────────────────────────────────
from search_queries import (
    PUBMED_QUERY_GROUPS,
    SEARCH_YEAR_START,
    SEARCH_YEAR_END,
    MAX_RESULTS_PER_QUERY,
    get_enabled_groups,
)

# ─────────────────────────────────────────────────────────────────────────────
# API Keys & Endpoints
# ─────────────────────────────────────────────────────────────────────────────
PUBMED_API_KEY: str = os.getenv("PUBMED_API_KEY", "")
PUBMED_EMAIL: str = os.getenv("PUBMED_EMAIL", "your@email.com")

S2_API_KEY: str = os.getenv("S2_API_KEY", "")

# OpenAI-compatible endpoint (百炼 DashScope default; DeepSeek direct: api.deepseek.com)
OPENAI_API_BASE: str = os.getenv(
    "OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
OPENAI_API_KEY: str = (
    os.getenv("DASHSCOPE_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("DEEPSEEK_API_KEY", "")
)
LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-v4-flash")
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "16384"))
# ~200k tokens input budget (chars); tool results use LLM_MAX_TOOL_RESULT_CHARS
LLM_MAX_INPUT_CHARS: int = int(os.getenv("LLM_MAX_INPUT_CHARS", "800000"))
LLM_MAX_TOOL_RESULT_CHARS: int = int(
    os.getenv("LLM_MAX_TOOL_RESULT_CHARS", "100000")
)
TOOL_TOP_N: int = int(os.getenv("TOOL_TOP_N", "30"))   # SQL tool result limit
GRAPH_TOP_N: int = int(os.getenv("GRAPH_TOP_N", "25"))  # Graph tool result limit

# Neo4j (optional – set USE_NEO4J=true to enable)
NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")
USE_NEO4J: bool = os.getenv("USE_NEO4J", "false").lower() == "true"

# Search settings are now in search_queries.py (imported above)

# Semantic Scholar field sets to request
S2_FIELDS: str = (
    "paperId,externalIds,title,abstract,year,publicationDate,"
    "journal,authors,citationCount,isOpenAccess,publicationTypes,"
    "references"
)

# ─────────────────────────────────────────────────────────────────────────────
# Study Type Enum
# ─────────────────────────────────────────────────────────────────────────────
STUDY_TYPES: list[str] = [
    "ai_algorithm",       # AI/深度学习算法研究
    "clinical_study",     # 临床验证/应用研究
    "review",             # 综述
    "meta_analysis",      # Meta分析
    "dataset_benchmark",  # 数据集构建/基准测试
    "foundation_model",   # 基础模型/预训练模型
    "multimodal",         # 多模态研究
    "other",              # 其他
]

# ─────────────────────────────────────────────────────────────────────────────
# Entity & Relation Types for KG Schema
# ─────────────────────────────────────────────────────────────────────────────
ENTITY_TYPES: list[str] = [
    "Disease",
    "Method",
    "Task",
    "Tissue",
    "Dataset",
    "Metric",
]

RELATION_TYPES: list[str] = [
    "APPLIES_METHOD",      # Paper → Method
    "TARGETS_DISEASE",     # Paper → Disease
    "OPERATES_ON",         # Paper → Tissue
    "PERFORMS_TASK",       # Paper → Task
    "USES_DATASET",        # Paper → Dataset
    "ACHIEVES_METRIC",     # Paper → Metric (with value)
    "CO_OCCURS_WITH",      # Entity ↔ Entity
    "RELATED_TO",          # Method → Method (variant/evolution)
]

# ─────────────────────────────────────────────────────────────────────────────
# File Paths
# ─────────────────────────────────────────────────────────────────────────────
DB_PATH: str = "data/kg_papers.db"
OUTPUT_DIR: str = "output"
DATA_DIR: str = "data"

# ─────────────────────────────────────────────────────────────────────────────
# LLM Extraction Settings (LLM_MAX_TOKENS defined above from env)
# ─────────────────────────────────────────────────────────────────────────────
LLM_TEMPERATURE: float = 0.0      # deterministic for extraction
LLM_BATCH_SIZE: int = 1           # abstracts per LLM call (1 = safest)
LLM_RETRY_ATTEMPTS: int = 3
LLM_RETRY_DELAY: float = 2.0      # seconds between retries

# Fuzzy match threshold for journal name matching (0–100)
JOURNAL_FUZZY_THRESHOLD: int = 85
