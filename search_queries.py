"""
search_queries.py
─────────────────────────────────────────────────────────────────────────────
PubMed 搜索关键字配置文件，独立于 config.py，方便单独维护和扩展。

使用方式：
  from search_queries import PUBMED_QUERY_GROUPS, SEARCH_YEAR_START, SEARCH_YEAR_END

新增查询组只需在 PUBMED_QUERY_GROUPS 末尾追加一个字典：
  {
      "name": "唯一标识符（英文下划线）",
      "query": "PubMed 检索式（支持 Title/Abstract、MeSH 等字段标签）",
      "max_results": 2000,   # 可选，覆盖全局默认值
      "enabled": True,       # 可选，False 时跳过此组
  }
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# 时间范围（会覆盖 config.py 中的同名变量，如果直接从本文件 import）
# ─────────────────────────────────────────────────────────────────────────────
SEARCH_YEAR_START: int = 2015
SEARCH_YEAR_END: int   = 2025

MAX_RESULTS_PER_QUERY: int = 2000   # 全局默认，可被各组的 max_results 覆盖

# ─────────────────────────────────────────────────────────────────────────────
# 查询组列表
# ─────────────────────────────────────────────────────────────────────────────
PUBMED_QUERY_GROUPS: list[dict] = [

    # ── 核心：计算病理 + 深度学习 ────────────────────────────────────────────
    {
        "name": "computational_pathology_dl",
        "query": (
            "(computational pathology[Title/Abstract] OR digital pathology[Title/Abstract])"
            " AND (deep learning[Title/Abstract] OR neural network[Title/Abstract])"
        ),
    },

    # ── 全切片图像（WSI）分类/分割/检测 ─────────────────────────────────────
    {
        "name": "wsi_classification_segmentation",
        "query": (
            "(whole slide image[Title/Abstract] OR WSI[Title/Abstract])"
            " AND (classification[Title/Abstract] OR segmentation[Title/Abstract]"
            " OR detection[Title/Abstract])"
        ),
    },

    # ── 基础模型 / 自监督 / Vision Transformer ───────────────────────────────
    {
        "name": "pathology_foundation_model",
        "query": (
            "(pathology[Title/Abstract])"
            " AND (foundation model[Title/Abstract] OR self-supervised[Title/Abstract]"
            " OR contrastive learning[Title/Abstract] OR vision transformer[Title/Abstract])"
        ),
    },

    # ── 癌症分级 AI（Gleason、Ki-67、HER2、PD-L1 等）───────────────────────
    {
        "name": "cancer_grading_staging_ai",
        "query": (
            "(cancer grading[Title/Abstract] OR tumor grading[Title/Abstract]"
            " OR Gleason[Title/Abstract] OR tumor staging[Title/Abstract])"
            " AND (pathology[Title/Abstract] OR histopathology[Title/Abstract]"
            " OR digital pathology[Title/Abstract])"
            " AND (artificial intelligence[Title/Abstract] OR machine learning[Title/Abstract]"
            " OR deep learning[Title/Abstract])"
        ),
    },

    # ── 免疫组化 / 生物标志物预测 AI ─────────────────────────────────────────
    {
        "name": "ihc_biomarker_prediction_ai",
        "query": (
            "(HER2[Title/Abstract] OR PD-L1[Title/Abstract] OR Ki-67[Title/Abstract]"
            " OR ER[Title/Abstract] OR PR[Title/Abstract]"
            " OR MSI[Title/Abstract] OR microsatellite instability[Title/Abstract]"
            " OR TMB[Title/Abstract] OR tumor mutational burden[Title/Abstract]"
            " OR EGFR[Title/Abstract] OR ALK[Title/Abstract] OR KRAS[Title/Abstract]"
            " OR MMR[Title/Abstract] OR mismatch repair[Title/Abstract])"
            " AND (pathology[Title/Abstract] OR histopathology[Title/Abstract])"
            " AND (deep learning[Title/Abstract] OR artificial intelligence[Title/Abstract]"
            " OR machine learning[Title/Abstract])"
        ),
    },

    # ── 组织病理学 + AI + 临床结局 ───────────────────────────────────────────
    {
        "name": "histology_ai_clinical",
        "query": (
            "(histology[Title/Abstract] OR histopathology[Title/Abstract])"
            " AND (artificial intelligence[Title/Abstract] OR deep learning[Title/Abstract])"
            " AND (clinical[Title/Abstract] OR patient outcome[Title/Abstract]"
            " OR prognosis[Title/Abstract])"
        ),
    },

    # ── 多模态 + 基因组学 ────────────────────────────────────────────────────
    {
        "name": "pathology_multimodal_genomics",
        "query": (
            "(pathology[Title/Abstract])"
            " AND (multimodal[Title/Abstract] OR genomics[Title/Abstract]"
            " OR transcriptomics[Title/Abstract])"
            " AND (deep learning[Title/Abstract] OR artificial intelligence[Title/Abstract])"
            " NOT (radiomics[Title/Abstract] OR CT[Title/Abstract] OR MRI[Title/Abstract])"
        ),
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 以下为扩展查询组（如需抓取可将 "enabled": False 改为 True）
    # ═══════════════════════════════════════════════════════════════════════

    # ── 细胞/核/组织/肿瘤分割 ────────────────────────────────────────────────
    {
        "name": "segmentation_pathology",
        "enabled": True,
        "query": (
            "(cell segmentation[Title/Abstract] OR nuclei segmentation[Title/Abstract]"
            " OR nucleus segmentation[Title/Abstract]"
            " OR tissue segmentation[Title/Abstract] OR tumor segmentation[Title/Abstract]"
            " OR tumour segmentation[Title/Abstract]"
            " OR gland segmentation[Title/Abstract] OR lesion segmentation[Title/Abstract]"
            " OR instance segmentation[Title/Abstract] OR semantic segmentation[Title/Abstract])"
            " AND (pathology[Title/Abstract] OR histology[Title/Abstract]"
            " OR histopathology[Title/Abstract] OR whole slide image[Title/Abstract])"
            " AND (deep learning[Title/Abstract] OR neural network[Title/Abstract]"
            " OR convolutional[Title/Abstract])"
        ),
    },

    # ── 细胞病理学 AI（宫颈细胞学、痰液、FNAC、尿液细胞学等）────────────────
    {
        "name": "cytopathology_ai",
        "enabled": True,
        "query": (
            "(cytopathology[Title/Abstract] OR cytology[Title/Abstract]"
            " OR cervical cytology[Title/Abstract] OR Pap smear[Title/Abstract]"
            " OR Pap test[Title/Abstract] OR ThinPrep[Title/Abstract]"
            " OR fine needle aspiration[Title/Abstract] OR FNAC[Title/Abstract]"
            " OR sputum cytology[Title/Abstract] OR urine cytology[Title/Abstract]"
            " OR liquid-based cytology[Title/Abstract]"
            " OR exfoliative cytology[Title/Abstract])"
            " AND (deep learning[Title/Abstract] OR artificial intelligence[Title/Abstract]"
            " OR machine learning[Title/Abstract] OR neural network[Title/Abstract]"
            " OR automated[Title/Abstract])"
        ),
    },

    # ── 空间转录组学 + AI ────────────────────────────────────────────────────
    {
        "name": "spatial_transcriptomics_ai",
        "enabled": True,
        "query": (
            "(spatial transcriptomics[Title/Abstract] OR spatial omics[Title/Abstract])"
            " AND (deep learning[Title/Abstract] OR machine learning[Title/Abstract]"
            " OR artificial intelligence[Title/Abstract])"
        ),
    },

    # ── 大语言模型 / VLM / 病理报告生成 ─────────────────────────────────────
    {
        "name": "llm_vlm_pathology",
        "enabled": True,
        "query": (
            "(large language model[Title/Abstract] OR GPT[Title/Abstract]"
            " OR ChatGPT[Title/Abstract] OR generative AI[Title/Abstract]"
            " OR vision language model[Title/Abstract] OR multimodal large language[Title/Abstract]"
            " OR CLIP[Title/Abstract] OR report generation[Title/Abstract])"
            " AND (pathology[Title/Abstract] OR histopathology[Title/Abstract]"
            " OR cytopathology[Title/Abstract] OR digital pathology[Title/Abstract])"
        ),
    },

    # ── 肿瘤微环境 + AI ──────────────────────────────────────────────────────
    {
        "name": "tumor_microenvironment_ai",
        "enabled": True,
        "query": (
            "(tumor microenvironment[Title/Abstract] OR tumour microenvironment[Title/Abstract]"
            " OR TIL[Title/Abstract] OR tumor infiltrating lymphocyte[Title/Abstract]"
            " OR tumor stroma[Title/Abstract] OR immune cell[Title/Abstract]"
            " OR spatial immune[Title/Abstract] OR immune landscape[Title/Abstract])"
            " AND (pathology[Title/Abstract] OR histopathology[Title/Abstract]"
            " OR whole slide image[Title/Abstract])"
            " AND (deep learning[Title/Abstract] OR artificial intelligence[Title/Abstract]"
            " OR machine learning[Title/Abstract])"
        ),
    },

    # ── 病理 + 影像组学（方信无影像数据，默认关闭；需要时可改 enabled）────
    {
        "name": "pathomics_radiomics",
        "enabled": False,
        "query": (
            "(pathomics[Title/Abstract] OR radiomics[Title/Abstract])"
            " AND (deep learning[Title/Abstract] OR machine learning[Title/Abstract])"
            " AND (pathology[Title/Abstract] OR cancer[Title/Abstract])"
        ),
    },

    # ── 联邦学习 / 隐私保护病理 AI ──────────────────────────────────────────
    {
        "name": "federated_learning_pathology",
        "enabled": True,
        "query": (
            "(federated learning[Title/Abstract] OR privacy-preserving[Title/Abstract])"
            " AND (pathology[Title/Abstract] OR histopathology[Title/Abstract]"
            " OR whole slide image[Title/Abstract] OR digital pathology[Title/Abstract])"
        ),
    },

    # ── 息肉 / 腺瘤 / 肠炎病理 AI（对齐方信高体量病种）──────────────────────
    {
        "name": "polyp_adenoma_colitis_pathology_ai",
        "enabled": True,
        "query": (
            "(colorectal polyp[Title/Abstract] OR colonic polyp[Title/Abstract]"
            " OR gastric polyp[Title/Abstract] OR intestinal polyp[Title/Abstract]"
            " OR colorectal adenoma[Title/Abstract] OR colonic adenoma[Title/Abstract]"
            " OR tubular adenoma[Title/Abstract] OR villous adenoma[Title/Abstract]"
            " OR colitis[Title/Abstract] OR ulcerative colitis[Title/Abstract]"
            " OR inflammatory bowel disease[Title/Abstract])"
            " AND (pathology[Title/Abstract] OR histopathology[Title/Abstract]"
            " OR histology[Title/Abstract] OR whole slide image[Title/Abstract]"
            " OR digital pathology[Title/Abstract])"
            " AND (deep learning[Title/Abstract] OR artificial intelligence[Title/Abstract]"
            " OR machine learning[Title/Abstract] OR neural network[Title/Abstract])"
        ),
    },
]


def get_enabled_groups() -> list[dict]:
    """返回所有 enabled=True（默认）的查询组，用于实际抓取。"""
    return [g for g in PUBMED_QUERY_GROUPS if g.get("enabled", True)]
