"""Method maturity for weekly hotspot novelty gating."""
from __future__ import annotations

import config
from db.schema import get_conn
from extractor.entity_normalize import _norm_key, is_generic_method

_ESTABLISHED_METHOD_ALIASES = frozenset({
    "large language model",
    "large language models",
    "llm",
    "svm",
    "support vector machine",
    "support vector machines",
    "cnn",
    "convolutional neural network",
    "convolutional neural networks",
    "random forest",
    "logistic regression",
    "xgboost",
    "extreme gradient boosting",
    "resnet",
    "resnet-50",
    "resnet50",
    "resnet-18",
    "resnet18",
})


def is_established_blacklist(name: str) -> bool:
    key = _norm_key(name)
    if key in _ESTABLISHED_METHOD_ALIASES:
        return True
    return is_generic_method(name)


def classify_method_maturity(
    name: str,
    corpus_paper_cnt: int,
    *,
    established_min: int | None = None,
) -> str:
    if is_established_blacklist(name):
        return "established"
    threshold = (
        established_min
        if established_min is not None
        else config.HOTSPOT_ESTABLISHED_MIN_PAPERS
    )
    n = int(corpus_paper_cnt or 0)
    if n >= threshold:
        return "established"
    if n <= 2:
        return "nascent"
    return "emerging"


def corpus_applies_method_counts() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS n
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type = 'Method'
              AND r.relation = 'APPLIES_METHOD'
              AND COALESCE(r.status, 'active') = 'active'
            GROUP BY e.id
            """
        ).fetchall()
    return {str(r["name"]): int(r["n"]) for r in rows}


def annotate_method_rows(
    rows: list[dict],
    *,
    name_key: str = "name",
    counts: dict[str, int] | None = None,
) -> list[dict]:
    counts = counts if counts is not None else corpus_applies_method_counts()
    for row in rows:
        name = str(row.get(name_key) or "")
        n = int(counts.get(name, 0))
        row["corpus_paper_cnt"] = n
        row["method_maturity"] = classify_method_maturity(name, n)
    return rows


def context_novelty_bonus(
    literature_paper_cnt: int,
    *,
    first_in_recent_window: bool = False,
) -> float:
    base = 1.5 if int(literature_paper_cnt) <= 0 else 0.5
    if first_in_recent_window:
        base += 0.5
    return base


def maturity_penalty(maturity: str) -> float:
    return 2.0 if maturity == "established" else 0.0


def nascent_bonus(maturity: str) -> float:
    return 0.5 if maturity == "nascent" else 0.0
