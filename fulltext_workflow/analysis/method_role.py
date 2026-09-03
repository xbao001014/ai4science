"""Method architecture role for weekly hotspot display."""
from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from analysis.method_synonyms import resolve_method_canonical
from extractor.entity_normalize import _norm_key

MethodRole = Literal["backbone", "aggregator", "classical_ml", "tool", "unknown"]
VALID_METHOD_ROLES = frozenset(
    {"backbone", "aggregator", "classical_ml", "tool", "unknown"}
)

# Exact aliases after _norm_key. If a name appears in both tables, aggregator wins.
_BACKBONE_ALIASES = frozenset({
    "resnet",
    "resnet-18",
    "resnet18",
    "resnet-50",
    "resnet50",
    "resnet-101",
    "resnet101",
    "vit",
    "vision transformer",
    "swin",
    "swin transformer",
    "efficientnet",
    "densenet",
    "densenet-121",
    "densenet121",
    "uni",
    "uni foundation model",
    "conch",
    "ctranspath",
    "hibou",
    "virchow",
    "phikon",
    "gigapath",
    "h-optimus",
    "hoptimus",
    "attention u-net",
    "attention-unet",
    "u-net",
    "unet",
    "nnunet",
    "nnu-net",
    "hover-net",
    "segformer",
    "dinov2",
    "simclr",
    "cnn",
    "convolutional neural network",
    "convolutional neural networks",
    "xception",
    "prov-gigapath",
    "googlenet",
    "squeezenet",
    "cyclegan",
    "autoencoder",
    "stardist",
    "mask r-cnn",
    "maskrcnn",
    "faster r-cnn",
    "faster rcnn",
    "deeplabv3",
    "deeplabv3+",
    "deeplab",
    "retinanet",
})

_AGGREGATOR_ALIASES = frozenset({
    # Common MIL framework names assigned to the aggregator role.
    "abmil",
    "clam",
    "dsmil",
    "transmil",
})

_CLASSICAL_ML_ALIASES = frozenset({
    "random forest",
    "random survival forest",
    "random survival forests",
    "support vector machine",
    "svm",
    "xgboost",
    "lightgbm",
    "logistic regression",
    "cox proportional hazards regression",
    "lasso",
    "lasso regression",
    "decision tree",
    "knn",
    "k-nearest neighbors",
    "k-nearest neighbor",
    "pca",
    "principal component analysis",
    "gbm",
    "gradient boosting machine",
    "nomogram",
    "adaboost",
    "coxboost",
    "linear discriminant analysis",
    "smote",
    "t-sne",
    "tsne",
    "multilayer perceptron",
    "multi-layer perceptron",
    "mlp",
    "machine learning",
    "deep learning",
    "linear regression",
    "chi-square test",
    "univariate analysis",
    "large language model",
    "llm",
})

_TOOL_ALIASES = frozenset({
    "qupath",
    "seurat",
    "gsva",
    "vosviewer",
    "limma",
    "cibersort",
    "cellchat",
    "wgcna",
    "ssgsea",
    "gsea",
    "shap",
    "grad-cam",
    "gradcam",
    "lime",
    "cellprofiler",
    "infercnv",
    "cytotrace",
    "ucell",
    "spatial transcriptomics",
    "molecular docking",
    "mendelian randomization",
    "western blot",
    "rt-qpcr",
    "qrt-pcr",
    "immunohistochemistry",
})

# Aggregator cues — no bare \battention\b.
_AGGREGATOR_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\baggregator\b",
        r"\bmil\b",
        r"multiple\s+instance\s+learning",
        r"attention\s*pool",
        r"\bpooling\b",
        r"fusion\s+(?:module|model|network|block)?",
        r"\bfusion\b",
        r"bag[\s\-]?level",
        r"instance[\s\-]?aggregat",
        r"\bclam\b",
    )
)

_BACKBONE_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bresnet",
        r"\bvit\b",
        r"\bswin",
        r"\befficientnet",
        r"\bdensenet",
        r"\bvgg",
        r"\binception",
        r"\balexnet",
        r"\bmobilenet",
        r"\bconvnext",
        r"\bencoder\b",
        r"\bbackbone\b",
        r"\b(?:nn)?u[\s\-]?net\b",
        r"\b(?:resunet|transunet|doubleu[\s\-]?net|hover[\s\-]?net)\b",
        r"\btransformer\b",
        r"\byolo(?:v?\d+)?\b",
        r"\b(?:mask|faster)\s*r[\s\-]?cnn\b",
        r"\bdeeplab",
        r"\bretinanet\b",
        r"\bcyclegan\b",
        r"\bautoencoder\b",
        r"\bstardist\b",
        r"\bsimclr\b",
        r"\bgooglenet\b",
        r"\bsqueezenet\b",
        r"\bresnest\b",
        r"\bkimianet\b",
        r"\bgraph\s+neural\b|\bgcn\b|\bgat\b|\bgnn\b",
        r"\bgan\b|\bdiffusion\s+model\b",
        r"\bself[\s\-]?supervised\b",
    )
)

_CLASSICAL_ML_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\brandom\s+forest",
        r"\bxgboost\b",
        r"\blightgbm\b",
        r"\bcatboost\b",
        r"\badaboost\b",
        r"\blogistic\s+regression",
        r"\bsupport\s+vector|\bsvm\b",
        r"\bcox(?!-?\d)\b(?:\s|$).*?(?:regression|proportional\s+hazards?|ph\s+model|boost)",
        r"\bcoxboost\b",
        r"\bkaplan[\s\-]?meier",
        r"\bnaive\s+bayes",
        r"\belastic\s+net\b",
        r"\bgradient\s+boost",
        r"\brandom\s+survival\s+forests?\b",
        r"\blasso\b",
        r"least\s+absolute\s+shrinkage",
        r"\bk[\s\-]?means\b",
        r"\bconsensus\s+clustering\b",
        r"\bhierarchical\s+clustering\b",
        r"\bunsupervised\s+clustering\b",
        r"\bmultilayer\s+perceptron\b|\bmulti[\s\-]?layer\s+perceptron\b|\bmlp\b",
        r"\blinear\s+discriminant\b",
        r"\blinear\s+regression\b",
        r"\bsmote\b",
        r"\brfe\b|recursive\s+feature\s+elimination",
        r"\bmachine\s+learning\b",
        r"\bdeep\s+learning\b",
        r"\bensemble\s+(?:model|learning|classifier)\b",
        r"\bchi[\s\-]?square\b",
        r"\bunivariate\s+analysis\b",
        r"\bnmf\b|non[\s\-]?negative\s+matrix\s+factorization",
        r"\blarge\s+language\s+model\b|\bllm\b",
    )
)

_TOOL_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bqupath\b",
        r"\bseurat\b",
        r"\bvosviewer\b",
        r"\bcitespace\b",
        r"\bwgcna\b|\bhdwgcna\b",
        r"weighted\s+gene\s+co[\s\-]?expression",
        r"\bgsea\b|\bssgsea\b|gene\s+set\s+enrichment",
        r"\bshap\b|shapley\s+additive",
        r"\bgrad[\s\-]?cam\b",
        r"\blime\b",
        r"spatial\s+transcriptomics",
        r"single[\s\-]?cell\s+(?:rna|analysis|transcript)",
        r"\bmolecular\s+docking\b",
        r"\bmendelian\s+randomization\b",
        r"\bcellprofiler\b",
        r"\binfercnv\b",
        r"\bcytotrace\b",
        r"\bucell\b",
        r"\bscissor\b",
        r"differential\s+expression",
        r"\bpseudotime\b",
        r"\bwestern\s+blot\b",
        r"\b(?:rt[\s\-]?q|qrt[\s\-]?)pcr\b",
        r"\bimmunohistochemistry\b|\bihc\b",
    )
)


def classify_method_role(name: str) -> MethodRole:
    key = _norm_key(resolve_method_canonical(name))
    if key in _AGGREGATOR_ALIASES:
        return "aggregator"
    if key in _BACKBONE_ALIASES:
        return "backbone"
    if key in _CLASSICAL_ML_ALIASES:
        return "classical_ml"
    if key in _TOOL_ALIASES:
        return "tool"
    if any(p.search(key) for p in _AGGREGATOR_PATTERNS):
        return "aggregator"
    if any(p.search(key) for p in _BACKBONE_PATTERNS):
        return "backbone"
    if any(p.search(key) for p in _CLASSICAL_ML_PATTERNS):
        return "classical_ml"
    if any(p.search(key) for p in _TOOL_PATTERNS):
        return "tool"
    return "unknown"


def resolve_method_role(name: str, llm_role: str | None = None) -> MethodRole:
    rule = classify_method_role(name)
    if rule != "unknown":
        return rule
    if isinstance(llm_role, str):
        hint = llm_role.strip().lower()
        if hint in VALID_METHOD_ROLES:
            return hint  # type: ignore[return-value]
    return "unknown"


def load_method_roles() -> dict[str, str]:
    from db.schema import get_conn

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT name, method_role FROM entities
            WHERE type='Method' AND method_role IS NOT NULL AND method_role != ''
            ORDER BY id
            """
        ).fetchall()
    roles: dict[str, str] = {}
    for row in rows:
        name = str(row["name"])
        role = str(row["method_role"])
        raw_key = _norm_key(name)
        canonical_key = _norm_key(resolve_method_canonical(name))
        for key in (canonical_key, raw_key):
            if key in roles:
                # Prefer a known role over unknown; between conflicting known
                # aliases, preserve the first DB row's role deterministically.
                if roles[key] == "unknown" and role != "unknown":
                    roles[key] = role
            else:
                roles[key] = role
    return roles


def backfill_method_roles(*, force: bool = False) -> dict[str, int]:
    from db.schema import get_conn

    counts: Counter[str] = Counter()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, method_role FROM entities WHERE type='Method'"
        ).fetchall()
        for row in rows:
            role = classify_method_role(str(row["name"]))
            existing = row["method_role"]
            if force or role != "unknown" or not str(existing or "").strip():
                conn.execute(
                    "UPDATE entities SET method_role=? WHERE id=?",
                    (role, row["id"]),
                )
            counts[role] += 1
    return dict(counts)


def annotate_method_role(
    rows: list[dict],
    *,
    name_key: str = "name",
    role_by_name: dict[str, str] | None = None,
) -> list[dict]:
    role_by_name = role_by_name or {}
    for row in rows:
        raw = str(row.get(name_key) or "")
        key = _norm_key(resolve_method_canonical(raw))
        db = role_by_name.get(key) or role_by_name.get(raw)
        db_or_none = db if db in VALID_METHOD_ROLES else None
        row["method_role"] = resolve_method_role(raw, db_or_none)
    return rows
