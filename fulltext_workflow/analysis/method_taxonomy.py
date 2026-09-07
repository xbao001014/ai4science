"""Versioned method-family catalog, prototypes, and shadow classification."""
from __future__ import annotations

import hashlib
import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Sequence
from pathlib import Path

import config
from analysis.embedding_client import EmbeddingClient, EmbeddingItem
from analysis.embedding_inputs import MethodEmbeddingInput
from analysis.embedding_service import embed_with_cache
from analysis.embedding_store import get_cached_vectors
from db.schema import get_conn


@dataclass(frozen=True)
class MethodFamily:
    family_id: str
    zh: str
    en: str
    description: str
    seeds: tuple[str, ...]
    negatives: tuple[str, ...] = ()


FAMILIES: tuple[MethodFamily, ...] = (
    MethodFamily("mil", "多实例学习", "Multiple-instance learning", "Weakly supervised learning over bags of image patches or instances, with instance-to-bag aggregation for slide-level prediction.", ("ABMIL attention-based multiple instance learning", "CLAM clustering-constrained attention MIL", "TransMIL transformer multiple instance learning", "DSMIL dual-stream MIL")),
    MethodFamily("cnn", "卷积神经网络", "Convolutional neural network", "Convolution-based deep neural architectures for image feature extraction, classification, detection, or segmentation.", ("ResNet convolutional residual network", "DenseNet convolutional network", "U-Net encoder-decoder segmentation", "EfficientNet convolutional architecture")),
    MethodFamily("transformer", "Transformer", "Transformer", "Attention-based transformer architectures for visual, sequence, or slide representations.", ("Vision Transformer ViT", "Swin Transformer", "TransUNet transformer segmentation", "self-attention transformer encoder")),
    MethodFamily("foundation_model", "基础模型", "Foundation model", "Large pretrained pathology or biomedical foundation models used for transferable representations, prompting, or adaptation.", ("UNI pathology foundation model", "CONCH vision-language foundation model", "Prov-GigaPath whole-slide foundation model", "Virchow pathology foundation model")),
    MethodFamily("graph_neural_network", "图神经网络", "Graph neural network", "Graph-based learning over cells, tissue regions, patches, or molecular interaction networks.", ("graph convolutional network GCN", "graph attention network GAT", "message-passing neural network", "cell graph neural network")),
    MethodFamily("representation_learning", "表征学习", "Representation learning", "Self-supervised, contrastive, metric, or unsupervised learning of reusable feature representations.", ("contrastive learning", "self-supervised learning", "metric learning", "knowledge distillation")),
    MethodFamily("generative_model", "生成模型", "Generative model", "Models that synthesize, translate, reconstruct, or generate images or features.", ("generative adversarial network GAN", "diffusion model", "variational autoencoder VAE", "image-to-image translation CycleGAN")),
    MethodFamily("classical_statistics", "传统统计与机器学习", "Classical statistics and machine learning", "Regression, survival analysis, hypothesis testing, feature selection, and non-deep classical machine-learning models.", ("support vector machine SVM", "random forest", "Cox proportional hazards regression", "logistic regression", "LASSO feature selection")),
    MethodFamily("bioinformatics_omics", "生物信息学与组学", "Bioinformatics and omics", "Gene-expression, pathway, cell-composition, spatial-omics, and multi-omics computational analysis.", ("gene set enrichment analysis GSEA", "weighted gene co-expression network analysis WGCNA", "CIBERSORT immune deconvolution", "single-cell RNA sequencing analysis", "spatial transcriptomics")),
    MethodFamily("image_processing", "图像处理", "Image processing", "Non-model or handcrafted image processing, stain normalization, morphology, registration, and feature engineering.", ("stain normalization", "color deconvolution", "image registration", "morphological image processing", "handcrafted radiomics features")),
    MethodFamily("multimodal_fusion", "多模态融合", "Multimodal fusion", "Fusion of pathology images with genomics, radiology, clinical variables, text, or other modalities.", ("multimodal feature fusion", "pathology genomics fusion", "vision-language alignment", "cross-modal attention")),
    MethodFamily("explainability", "可解释性", "Explainability", "Post-hoc or intrinsic interpretation, attribution, visualization, and model explanation methods.", ("SHAP Shapley additive explanations", "Grad-CAM class activation mapping", "integrated gradients", "attention visualization")),
    MethodFamily("other_tooling", "分析工具与平台", "Analysis tooling", "Named software tools, annotation platforms, viewers, workflow engines, and utilities that are not themselves modeling families.", ("QuPath digital pathology software", "ImageJ image analysis tool", "VOSviewer bibliometric software", "CellProfiler image analysis platform")),
)


def sync_family_catalog(taxonomy_version: str = config.METHOD_TAXONOMY_VERSION) -> int:
    with get_conn() as conn:
        for family in FAMILIES:
            conn.execute(
                """INSERT INTO method_taxonomy_families
                   (family_id, taxonomy_version, display_name_zh, display_name_en,
                    description, seed_methods_json, negative_examples_json, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(family_id, taxonomy_version) DO UPDATE SET
                     display_name_zh=excluded.display_name_zh,
                     display_name_en=excluded.display_name_en,
                     description=excluded.description,
                     seed_methods_json=excluded.seed_methods_json,
                     negative_examples_json=excluded.negative_examples_json,
                     active=1, updated_at=CURRENT_TIMESTAMP""",
                (
                    family.family_id,
                    taxonomy_version,
                    family.zh,
                    family.en,
                    family.description,
                    json.dumps(family.seeds, ensure_ascii=False),
                    json.dumps(family.negatives, ensure_ascii=False),
                ),
            )
        marks = ",".join("?" for _ in FAMILIES)
        conn.execute(
            f"""UPDATE method_taxonomy_families SET active=0, updated_at=CURRENT_TIMESTAMP
                WHERE taxonomy_version=? AND family_id NOT IN ({marks})""",
            (taxonomy_version, *(family.family_id for family in FAMILIES)),
        )
    return len(FAMILIES)


def prototype_embedding_items(
    taxonomy_version: str = config.METHOD_TAXONOMY_VERSION,
) -> tuple[list[EmbeddingItem], dict[str, str]]:
    items: list[EmbeddingItem] = []
    family_by_item: dict[str, str] = {}
    for family in FAMILIES:
        texts = (
            f"taxonomy: {taxonomy_version}\nfamily: {family.en}\ndescription: {family.description}",
            *(f"taxonomy: {taxonomy_version}\npositive method example: {seed}" for seed in family.seeds),
        )
        for index, text in enumerate(texts):
            item_id = f"{family.family_id}:{index}"
            items.append(
                EmbeddingItem(
                    item_id=item_id,
                    input_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    text=text,
                )
            )
            family_by_item[item_id] = family.family_id
    return items, family_by_item


def _centroid(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    if not vectors:
        raise ValueError("Cannot build a centroid without vectors")
    dimensions = len(vectors[0])
    if any(len(vector) != dimensions for vector in vectors):
        raise ValueError("Prototype vector dimensions do not match")
    values = [sum(vector[i] for vector in vectors) / len(vectors) for i in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0 or not math.isfinite(norm):
        raise ValueError("Prototype centroid is invalid")
    return tuple(value / norm for value in values)


def ensure_prototype_centroids(
    client: EmbeddingClient,
    *,
    provider: str = config.EMBEDDING_PROVIDER,
    model: str = config.EMBEDDING_MODEL,
    dimensions: int = config.EMBEDDING_DIMENSIONS,
    taxonomy_version: str = config.METHOD_TAXONOMY_VERSION,
) -> tuple[dict[str, tuple[float, ...]], dict[str, int | str]]:
    sync_family_catalog(taxonomy_version)
    items, family_by_item = prototype_embedding_items(taxonomy_version)
    result = embed_with_cache(
        client,
        items,
        provider=provider,
        model=model,
        dimensions=dimensions,
        job_type="taxonomy_prototypes",
        item_type="prototype",
        context_quality="curated",
    )
    grouped: dict[str, list[tuple[float, ...]]] = {}
    for vector in result.vectors:
        grouped.setdefault(family_by_item[vector.item_id], []).append(vector.values)
    centroids = {family_id: _centroid(vectors) for family_id, vectors in grouped.items()}
    if len(centroids) != len(FAMILIES):
        raise ValueError("Not all method-family prototypes were embedded")
    return centroids, {
        "job_id": result.job_id,
        "prototype_inputs": len(items),
        "cache_hits": result.cache_hits,
        "requested_items": result.requested_items,
        "actual_tokens": result.actual_tokens,
    }


def load_prototype_centroids_from_cache(
    *,
    provider: str = config.EMBEDDING_PROVIDER,
    model: str = config.EMBEDDING_MODEL,
    dimensions: int = config.EMBEDDING_DIMENSIONS,
    taxonomy_version: str = config.METHOD_TAXONOMY_VERSION,
) -> dict[str, tuple[float, ...]]:
    items, family_by_item = prototype_embedding_items(taxonomy_version)
    cached = get_cached_vectors(
        [item.input_sha256 for item in items],
        provider=provider,
        model=model,
        dimensions=dimensions,
        touch=False,
    )
    grouped: dict[str, list[tuple[float, ...]]] = {}
    for item in items:
        vector = cached.get(item.input_sha256)
        if vector is not None:
            grouped.setdefault(family_by_item[item.item_id], []).append(vector.values)
    expected = Counter(family_by_item.values())
    if any(len(grouped.get(family_id, ())) != count for family_id, count in expected.items()):
        return {}
    return {family_id: _centroid(vectors) for family_id, vectors in grouped.items()}


def _cosine_against_normalized(vector: Sequence[float], centroid: Sequence[float]) -> float:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0 or len(vector) != len(centroid):
        raise ValueError("Method vector is invalid")
    return sum(value * other for value, other in zip(vector, centroid)) / norm


_LEXICAL_CUES: dict[str, tuple[str, ...]] = {
    "mil": ("multiple instance", "abmil", "transmil", "dsmil", "clam-sb", "clam-mb", "attention mil"),
    "cnn": ("cnn", "convolution", "resnet", "densenet", "efficientnet", "mobilenet", "vgg", "xception", "u-net", "unet", "deeplab", "convnext", "yolo", "hover-net", "r2u-net"),
    "transformer": ("transformer", "vision transformer", "swin", "transunet", " vit "),
    "foundation_model": ("foundation model", "pathology foundation", " uni ", "conch", "gigapath", "virchow", "chief"),
    "graph_neural_network": ("graph neural", "graph convolution", "graph attention", " gcn", " gat", "message passing"),
    "representation_learning": ("contrastive", "self-supervised", "self supervised", "moco", "simclr", "metric learning", "distillation"),
    "generative_model": ("generative", " gan", "diffusion", "variational autoencoder", " vae", "cyclegan", "autoencoder"),
    "classical_statistics": ("support vector", " svm", "random forest", "regression", "cox", "lasso", "xgboost", "lightgbm", "k-means", "knn", "principal component", "nomogram"),
    "bioinformatics_omics": ("transcriptom", "genomic", "multi-omics", "proteomic", "gsea", "wgcna", "cibersort", "rna-seq", "single-cell", "spatial transcript", "qpcr", "q-pcr"),
    "image_processing": ("threshold", "stain", "color deconvolution", "registration", "morpholog", "radiomic", "handcrafted", "otsu", "image filter"),
    "multimodal_fusion": ("multimodal", "multi-modal", "vision-language", "cross-modal", "feature fusion", "pathology-genomic"),
    "explainability": ("shap", "lime", "gradcam", "grad-cam", "score-cam", "explain", "permutation importance", "relevance propagation", "integrated gradient"),
    "other_tooling": ("qupath", "imagej", "vosviewer", "citespace", "bibliometrix", "cellprofiler", "software tool", "analysis platform"),
}


def _method_name_and_role(item: MethodEmbeddingInput) -> tuple[str, str]:
    name = ""
    role = "unknown"
    for line in item.text.splitlines():
        if line.startswith("method: "):
            name = line.removeprefix("method: ").strip().lower()
        elif line.startswith("role: "):
            role = line.removeprefix("role: ").strip().lower()
    return f" {re.sub(r'[^a-z0-9+_-]+', ' ', name)} ", role


def _lexical_adjustments(item: MethodEmbeddingInput) -> dict[str, float]:
    name, role = _method_name_and_role(item)
    adjustments: dict[str, float] = {}
    matched: set[str] = set()
    for family_id, cues in _LEXICAL_CUES.items():
        if any(cue in name for cue in cues):
            matched.add(family_id)
            adjustments[family_id] = 0.16
    # Generic occurrences of "model" in paper context must not imply a foundation model.
    if "foundation_model" not in matched:
        adjustments["foundation_model"] = -0.10
    if role == "classical_ml" and not matched.intersection(
        {"cnn", "transformer", "mil", "foundation_model"}
    ):
        adjustments["classical_statistics"] = adjustments.get("classical_statistics", 0.0) + 0.06
    if role == "aggregator":
        adjustments["mil"] = adjustments.get("mil", 0.0) + 0.05
    return adjustments


def shadow_classify_cached_methods(
    inputs: Sequence[MethodEmbeddingInput],
    centroids: dict[str, tuple[float, ...]],
    *,
    provider: str = config.EMBEDDING_PROVIDER,
    model: str = config.EMBEDDING_MODEL,
    dimensions: int = config.EMBEDDING_DIMENSIONS,
    taxonomy_version: str = config.METHOD_TAXONOMY_VERSION,
    top_k: int = config.METHOD_FAMILY_TOP_K,
) -> dict[str, object]:
    if set(centroids) != {family.family_id for family in FAMILIES}:
        raise ValueError("Complete family centroids are required")
    cached = get_cached_vectors(
        [item.input_sha256 for item in inputs],
        provider=provider,
        model=model,
        dimensions=dimensions,
        touch=False,
    )
    classified = 0
    missing = 0
    primary_counts: Counter[str] = Counter()
    similarities: list[float] = []
    margins: list[float] = []
    with get_conn() as conn:
        for item in inputs:
            cached_vector = cached.get(item.input_sha256)
            if cached_vector is None:
                missing += 1
                continue
            adjustments = _lexical_adjustments(item)
            scored = []
            for family_id, centroid in centroids.items():
                similarity = _cosine_against_normalized(cached_vector.values, centroid)
                ranking_score = similarity + adjustments.get(family_id, 0.0)
                scored.append((ranking_score, family_id, similarity))
            ranked = sorted(scored, reverse=True)
            top = ranked[: max(1, min(top_k, len(ranked)))]
            margin = top[0][0] - ranked[1][0] if len(ranked) > 1 else top[0][0]
            conn.execute(
                """UPDATE method_family_assignments SET status='stale', updated_at=CURRENT_TIMESTAMP
                   WHERE method_entity_id=? AND taxonomy_version=?
                     AND provider=? AND model=? AND dimensions=?""",
                (item.method_entity_id, taxonomy_version, provider, model, dimensions),
            )
            for rank, (ranking_score, family_id, similarity) in enumerate(top, start=1):
                conn.execute(
                    """INSERT INTO method_family_assignments
                       (method_entity_id, family_id, taxonomy_version, candidate_rank,
                        is_primary, confidence, similarity, margin, source, status,
                        input_sha256, provider, model, dimensions)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'embedding_shadow', 'review',
                               ?, ?, ?, ?)
                       ON CONFLICT(method_entity_id, family_id, taxonomy_version) DO UPDATE SET
                         candidate_rank=excluded.candidate_rank,
                         is_primary=excluded.is_primary,
                         confidence=excluded.confidence,
                         similarity=excluded.similarity,
                         margin=excluded.margin,
                         source=excluded.source,
                         status='review', input_sha256=excluded.input_sha256,
                         provider=excluded.provider, model=excluded.model,
                         dimensions=excluded.dimensions, updated_at=CURRENT_TIMESTAMP""",
                    (
                        item.method_entity_id,
                        family_id,
                        taxonomy_version,
                        rank,
                        1 if rank == 1 else 0,
                        ranking_score,
                        similarity,
                        margin,
                        item.input_sha256,
                        provider,
                        model,
                        dimensions,
                    ),
                )
            classified += 1
            primary_counts[top[0][1]] += 1
            similarities.append(top[0][2])
            margins.append(margin)
    return {
        "taxonomy_version": taxonomy_version,
        "status": "review",
        "input_methods": len(inputs),
        "classified_methods": classified,
        "missing_vectors": missing,
        "primary_family_counts": dict(sorted(primary_counts.items())),
        "top1_similarity_mean": round(sum(similarities) / len(similarities), 6) if similarities else None,
        "margin_mean": round(sum(margins) / len(margins), 6) if margins else None,
    }


def export_gold_template(path: str | Path, *, size: int = 400) -> dict[str, object]:
    """Export a deterministic stratified review sheet; gold labels remain blank."""
    size = max(1, min(int(size), 1000))
    with get_conn() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT e.id AS method_entity_id, e.name AS method_name,
                          COALESCE(e.method_role, 'unknown') AS method_role,
                          COUNT(DISTINCT r.source_pmid) AS paper_count,
                          MIN(p.year) AS first_year, MAX(p.year) AS last_year,
                          a.family_id AS suggested_primary,
                          a.similarity AS top1_similarity, a.confidence AS ranking_score,
                          a.margin
                   FROM entities e
                   JOIN relations r ON r.object_id=e.id
                     AND r.object_type='Method' AND r.relation='APPLIES_METHOD'
                     AND COALESCE(r.status, 'active')='active'
                   LEFT JOIN papers p ON p.pmid=r.source_pmid
                   LEFT JOIN method_family_assignments a ON a.method_entity_id=e.id
                     AND a.taxonomy_version=? AND a.candidate_rank=1
                     AND a.status='review'
                   WHERE e.type='Method'
                   GROUP BY e.id
                   ORDER BY e.id""",
                (config.METHOD_TAXONOMY_VERSION,),
            ).fetchall()
        ]
        top_rows = conn.execute(
            """SELECT method_entity_id, family_id, candidate_rank
               FROM method_family_assignments
               WHERE taxonomy_version=? AND status='review'
               ORDER BY method_entity_id, candidate_rank""",
            (config.METHOD_TAXONOMY_VERSION,),
        ).fetchall()
    top3: dict[int, list[str]] = {}
    for row in top_rows:
        top3.setdefault(int(row["method_entity_id"]), []).append(str(row["family_id"]))

    def opaque(row: dict) -> bool:
        name = str(row["method_name"] or "")
        return len(name) <= 14 and len(name.split()) == 1

    strata = (
        sorted(rows, key=lambda row: (-int(row["paper_count"]), int(row["method_entity_id"]))),
        [row for row in rows if row["method_role"] == "unknown"],
        [row for row in rows if opaque(row)],
        sorted(rows, key=lambda row: (-(int(row["last_year"] or 0)), int(row["method_entity_id"]))),
    )
    selected: list[dict] = []
    seen: set[int] = set()
    quota = math.ceil(size / len(strata))
    for stratum in strata:
        taken = 0
        for row in stratum:
            method_id = int(row["method_entity_id"])
            if method_id in seen:
                continue
            selected.append(row)
            seen.add(method_id)
            taken += 1
            if taken >= quota or len(selected) >= size:
                break
    if len(selected) < size:
        for row in rows:
            method_id = int(row["method_entity_id"])
            if method_id not in seen:
                selected.append(row)
                seen.add(method_id)
                if len(selected) >= size:
                    break

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "method_entity_id", "method_name", "method_role", "paper_count",
        "first_year", "last_year", "suggested_primary", "top1_similarity",
        "ranking_score", "margin", "suggested_top3", "gold_primary",
        "gold_secondary", "review_notes",
    )
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            output = {field: row.get(field, "") for field in fields}
            output["suggested_top3"] = "|".join(top3.get(int(row["method_entity_id"]), []))
            output["gold_primary"] = ""
            output["gold_secondary"] = ""
            output["review_notes"] = ""
            writer.writerow(output)
    return {
        "output": str(target),
        "rows": len(selected),
        "taxonomy_version": config.METHOD_TAXONOMY_VERSION,
        "labeled_rows": 0,
    }
