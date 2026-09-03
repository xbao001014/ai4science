#!/usr/bin/env python3
"""Build the multimodal expansion candidate list and coverage-gap matrix."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "multimodal-method-summary"
DB = ROOT / "fulltext_workflow" / "data" / "kg_fulltext.db"

LOCAL = [
    ("40051298", "P0", "pathology_genomics_interaction", "method", "桥接组织学与基因组学的可解释泛癌生存融合"),
    ("42332139", "P0", "missing_modality", "method", "NSCLC多模态生存预测中的缺失模态处理"),
    ("41870128", "P1", "missing_modality", "method", "癌种感知的缺失模态稳健生存预测"),
    ("41554842", "P1", "missing_modality", "method", "UroFusion-X：诊断、分型和预后的统一多模态框架"),
    ("35358054", "P1", "pathology_vqa_benchmark", "dataset_method", "病理视觉问答的可解释Vision-Language Transformer"),
    ("38742142", "P0", "pathology_text_dataset", "dataset", "Quilt-1M病理图文对数据集"),
    ("38778098", "P1", "unimodal_wsi_control", "baseline_control", "Prov-GigaPath：多模态研究所需的强WSI单模态对照"),
    ("38504018", "P1", "unimodal_wsi_control", "baseline_control", "UNI：通用病理视觉编码器对照"),
    ("39232164", "P1", "unimodal_wsi_control", "baseline_control", "CHIEF：癌症诊断与预后的病理基础模型对照"),
    ("40463538", "P2", "controlled_benchmark", "benchmark", "病理基础模型表征相似性的受控比较"),
]

EXTERNAL = [
    ("mcat-2021", "P0", 2021, "Multimodal Co-Attention Transformer for Survival Prediction in Gigapixel Whole Slide Images", "pathology_genomics_interaction", "pathology_method", "https://openaccess.thecvf.com/content/ICCV2021/html/Chen_Multimodal_Co-Attention_Transformer_for_Survival_Prediction_in_Gigapixel_Whole_Slide_ICCV_2021_paper.html"),
    ("motcat-2023", "P0", 2023, "Multimodal Optimal Transport-based Co-Attention Transformer with Global Structure Consistency for Survival Prediction", "pathology_genomics_interaction", "pathology_method", "https://openaccess.thecvf.com/content/ICCV2023/html/Xu_Multimodal_Optimal_Transport-based_Co-Attention_Transformer_with_Global_Structure_Consistency_for_ICCV_2023_paper.html"),
    ("survpath-2024", "P0", 2024, "Modeling Dense Multimodal Interactions Between Biological Pathways and Histology for Survival Prediction", "pathology_genomics_interaction", "pathology_method", "https://openaccess.thecvf.com/content/CVPR2024/html/Jaume_Modeling_Dense_Multimodal_Interactions_Between_Biological_Pathways_and_Histology_for_CVPR_2024_paper.html"),
    ("clip-2021", "P0", 2021, "Learning Transferable Visual Models From Natural Language Supervision", "generic_vlm", "architecture_baseline", "https://arxiv.org/abs/2103.00020"),
    ("coca-2022", "P1", 2022, "CoCa: Contrastive Captioners are Image-Text Foundation Models", "generic_vlm", "architecture_baseline", "https://arxiv.org/abs/2205.01917"),
    ("llava-2023", "P1", 2023, "Visual Instruction Tuning", "generic_vlm", "architecture_baseline", "https://arxiv.org/abs/2304.08485"),
    ("tfn-2017", "P1", 2017, "Tensor Fusion Network for Multimodal Sentiment Analysis", "fusion_operator", "architecture_baseline", "https://aclanthology.org/D17-1115/"),
    ("abmil-2018", "P0", 2018, "Attention-based Deep Multiple Instance Learning", "unimodal_mil_control", "baseline_control", "https://arxiv.org/abs/1802.04712"),
    ("clam-2021", "P0", 2021, "Data-efficient and weakly supervised computational pathology on whole-slide images", "unimodal_mil_control", "baseline_control", "https://www.nature.com/articles/s41551-020-00682-w"),
    ("transmil-2021", "P1", 2021, "TransMIL: Transformer based Correlated Multiple Instance Learning for Whole Slide Image Classification", "unimodal_mil_control", "baseline_control", "https://proceedings.neurips.cc/paper/2021/hash/10c272d06794d3e5785d5e7c5356e9ff-Abstract.html"),
]

TRACKS = [
    ("pathology_genomics_interaction", "病理—组学交互主干", 6),
    ("missing_modality", "缺失模态与鲁棒融合", 4),
    ("generic_vlm", "通用视觉语言架构基线", 3),
    ("pathology_text_dataset", "病理图文数据集", 2),
    ("pathology_vqa_benchmark", "病理VQA/生成式评价", 2),
    ("fusion_operator", "通用融合算子", 3),
    ("unimodal_mil_control", "病理单模态MIL对照", 3),
    ("unimodal_wsi_control", "病理视觉基础模型对照", 3),
    ("controlled_benchmark", "公平比较与受控基准", 3),
]

def read_selected() -> list[dict]:
    return [json.loads(x) for x in (PROJECT / "selected_papers.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

def local_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = []
    for pmid, priority, track, role, rationale in LOCAL:
        row = conn.execute("SELECT pmid,doi,title,year,citation_count,full_text_status,pmc_id FROM papers WHERE pmid=?", (pmid,)).fetchone()
        if row is None:
            raise RuntimeError(f"missing local metadata: PMID {pmid}")
        item = dict(row)
        status = item.get("full_text_status") or "pending"
        item.update({"candidate_id": f"PMID:{pmid}", "priority": priority, "track": track, "role": role,
                     "rationale": rationale, "source": "local_db", "summary_type": "full_method_summary"})
        item["next_action"] = "可直接生成总结" if status in {"available", "pdf_available"} else "补充全文后生成总结"
        rows.append(item)
    return rows

def external_rows() -> list[dict]:
    return [{"candidate_id": cid, "pmid": None, "priority": priority, "year": year, "citation_count": None,
             "title": title, "track": track, "role": role,
             "rationale": "补齐公平比较坐标；通用基线和病理专用方法分角色记录",
             "source": "external_primary_paper", "source_url": url, "full_text_status": "external",
             "next_action": "导入原始论文或建立精简基线卡",
             "summary_type": "full_method_summary" if role == "pathology_method" else "baseline_card"}
            for cid, priority, year, title, track, role, url in EXTERNAL]

def current_counts(selected: list[dict]) -> Counter:
    counts = Counter()
    for row in selected:
        track = row.get("track", "")
        if track in {"pathology_genomics", "pathology_text_genomics", "pathology_spatial_omics"}:
            counts["pathology_genomics_interaction"] += 1
        if track == "pathology_text": counts["pathology_vqa_benchmark"] += 1
        if row.get("pmid") in {"31510656", "36038778"}: counts["missing_modality"] += 1
        if row.get("pmid") in {"33838393", "36991216"}: counts["controlled_benchmark"] += 1
    return counts

def build_report(rows: list[dict]) -> str:
    lines = ["# 病理多模态候选扩充清单", "",
             "本轮重点不是继续堆叠视觉语言基础模型，而是补齐病理—组学方法主干、单模态对照、通用融合基线、缺失模态和公平评价。",
             "", "| 优先级 | 年份 | 候选 | 填充方向 | 角色 | 引用 | 全文 | 下一步 |", "|---|---:|---|---|---|---:|---|---|"]
    for row in sorted(rows, key=lambda x: (x["priority"], -(x.get("citation_count") or 0), x.get("year") or 0)):
        title = row["title"].replace("|", "\\|")
        title = f"[{title}]({row['source_url']})" if row.get("source_url") else f"{title} (PMID {row['pmid']})"
        lines.append(f"| {row['priority']} | {row.get('year') or ''} | {title} | `{row['track']}` | {row['role']} | {row.get('citation_count') or ''} | {row['full_text_status']} | {row['next_action']} |")
    lines.extend(["", f"共 {len(rows)} 项候选。通用方法生成精简基线卡；病理专用方法生成完整总结。", ""])
    return "\n".join(lines)

def build_matrix(rows: list[dict], selected: list[dict]) -> str:
    now, new = current_counts(selected), Counter(r["track"] for r in rows)
    ready = Counter(r["track"] for r in rows if r["full_text_status"] in {"available", "pdf_available"})
    lines = ["# 病理多模态扩充缺口矩阵", "", "> 多模态现有25篇代表作已具备较强覆盖，本轮扩充主要建立公平比较坐标。", "",
             "| 填充方向 | 现有代表 | 新候选 | 全文就绪 | 建议最低覆盖 | 扩充后状态 |", "|---|---:|---:|---:|---:|---|"]
    for key, label, target in TRACKS:
        total = now[key] + new[key]
        lines.append(f"| {label} (`{key}`) | {now[key]} | {new[key]} | {ready[key]} | {target} | {'已达目标' if total >= target else f'仍缺 {target-total}'} |")
    local = [r for r in rows if r["source"] == "local_db"]
    ready_rows = [r for r in local if r["full_text_status"] in {"available", "pdf_available"}]
    lines.extend(["", "## 执行批次", "", f"- A批：本地全文就绪 {len(ready_rows)} 篇。",
                  f"- B批：本地有元数据但待补全文 {len(local)-len(ready_rows)} 篇。",
                  f"- C批：外部原始论文/通用基线 {len(rows)-len(local)} 项。",
                  "- MCAT、MOTCat和SurvPath生成完整总结；CLIP、CoCa、LLaVA及MIL模型作为基线卡。",
                  "", "## 比较规则", "",
                  "- 每个多模态模型至少对比相同编码器下的单模态、简单拼接和参数量匹配对照。",
                  "- 缺失模态必须报告缺失模式、缺失比例、训练与测试缺失是否一致。",
                  "- 图文模型区分patch级、WSI级、检索、分类、VQA和生成任务，不跨任务排名。",
                  "- TCGA内部划分与独立临床队列分开记录。", ""])
    return "\n".join(lines)

def main() -> int:
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    selected = read_selected()
    overlap = {str(r["pmid"]) for r in selected}.intersection({r[0] for r in LOCAL})
    if overlap: raise RuntimeError(f"candidates overlap current selection: {sorted(overlap)}")
    rows = local_rows(conn) + external_rows()
    (PROJECT / "expansion_candidates.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (PROJECT / "expansion_candidates.md").write_text(build_report(rows), encoding="utf-8")
    (PROJECT / "coverage_gap_matrix.md").write_text(build_matrix(rows, selected), encoding="utf-8")
    print(json.dumps({"current": len(selected), "candidates": len(rows), "ready": sum(r["full_text_status"] in {"available", "pdf_available"} for r in rows)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
