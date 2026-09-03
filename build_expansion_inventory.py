#!/usr/bin/env python3
"""Build reproducible expansion candidates and coverage-gap matrices for topic libraries."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB = ROOT / "fulltext_workflow" / "data" / "kg_fulltext.db"


SEGMENTATION_LOCAL = [
    ("27898306", "P0", "pathology_instance", "method", "DCAN：轮廓感知的组织学实例分割代表作"),
    ("26415167", "P0", "classical_nuclei", "method", "深度学习前后衔接的稳健核分割基线"),
    ("26863654", "P1", "joint_detection_typing", "method", "结肠核检测与分类的早期高引方法"),
    ("28154470", "P1", "tissue_semantic", "method", "上皮—间质区域语义分割代表工作"),
    ("29018612", "P1", "gland_instance", "method", "腺体分割、分类与总变分正则化"),
    ("32903361", "P1", "pathology_instance", "method", "Mask R-CNN式病理核实例分割应用基线"),
    ("32769053", "P0", "interactive_prompt", "method", "NuClick：交互式点击提示分割"),
    ("32712523", "P0", "cross_stain_generalization", "method", "Triple U-Net：苏木精感知与渐进特征聚合"),
    ("32835732", "P1", "tissue_semantic", "external_validation", "多染色肾组织结构分割与评价"),
    ("33154175", "P1", "tissue_semantic", "clinical_pipeline", "实验肾脏病理结构分割和量化流程"),
    ("33216724", "P0", "benchmark", "challenge", "ACDC@LungHP：肺癌组织分割挑战基准"),
    ("33190012", "P1", "pathology_instance", "method", "NucleiSegNet：肝癌核分割专用架构"),
    ("35367734", "P1", "joint_detection_typing", "method", "TSFD-Net：组织特异特征蒸馏"),
    ("36007483", "P1", "cross_stain_generalization", "method", "肾小球边界感知与一对多染色泛化"),
    ("36410209", "P0", "joint_detection_typing", "method", "统一模型同时完成组织学分割与分类"),
    ("36599960", "P1", "tissue_semantic", "dataset_method", "Tubule-U-Net：乳腺管状结构数据集和方法"),
    ("37778210", "P1", "generative_segmentation", "method", "实例感知扩散模型用于腺体分割"),
    ("37788295", "P1", "pathology_instance", "method", "改进U-Net用于宫颈细胞核分割"),
    ("38292472", "P1", "cross_stain_generalization", "external_validation", "训练期随机、测试期确定性染色标准化增强核分割泛化"),
    ("38507894", "P0", "transformer_foundation", "method", "CellViT：Transformer核分割与分类"),
    ("38781811", "P1", "whole_cell", "dataset_method", "Cyto R-CNN与CytoNuke全细胞分割数据集"),
    ("39440549", "P1", "prompt_foundation", "method", "CellSAM：大模型特征蒸馏的细胞分割"),
    ("39528162", "P1", "whole_cell", "method", "CSGO：H&E全细胞边界优化"),
    ("40030236", "P0", "prompt_foundation", "foundation_model", "SegAnyPath：多分辨率、多染色、多任务病理分割基础模型"),
    ("41286516", "P0", "benchmark", "external_validation", "肾病理中Cellpose、StarDist、CellViT的受控评价"),
    ("42581240", "P2", "benchmark", "controlled_benchmark", "CNN、Transformer与混合架构的受控核分割比较；列入观察清单"),
]


VIRTUAL_LOCAL = [
    ("27373749", "P1", "normalization_classical", "method", "StaNoSA稀疏自编码染色标准化"),
    ("29533895", "P0", "unpaired_translation", "method", "Adversarial Stain Transfer：高引染色迁移基线"),
    ("31632974", "P1", "normalization_wsi", "pipeline", "面向WSI的稳健染色标准化系统"),
    ("31872065", "P0", "label_free_to_he", "clinical_feasibility", "多光子无标记虚拟组织学与术中实时性"),
    ("32238879", "P0", "virtual_ihc", "clinical_validation", "SOX10虚拟IHC开发与病理评价"),
    ("33784619", "P0", "unpaired_translation", "method", "病理一致性约束的无配对染色迁移"),
    ("34362386", "P1", "normalization_gan", "method", "CycleGAN用于H&E染色标准化"),
    ("34795202", "P1", "in_vivo_virtual_histology", "clinical_feasibility", "活体皮肤无活检虚拟组织学"),
    ("34805215", "P0", "normalization_fast", "method", "StainNet：快速轻量染色标准化基线"),
    ("35026572", "P1", "unpaired_translation", "method", "解耦特征的GAN染色迁移"),
    ("35810588", "P0", "virtual_multistain", "method", "MVFStain：多种功能染色的特定域映射"),
    ("35877646", "P0", "normalization_contrastive", "method", "StainCUT：对比学习染色标准化"),
    ("36113326", "P1", "normalization_gan", "method", "颜色自适应生成网络"),
    ("36473344", "P1", "normalization_diffusion", "method", "基于score扩散模型的染色标准化"),
    ("36764189", "P1", "unpaired_translation", "method", "先验引导的无配对虚拟染色"),
    ("36801642", "P0", "label_free_to_he", "wsi_pipeline", "未染色组织到H&E的全切片工作流"),
    ("37040684", "P0", "benchmark", "controlled_benchmark", "无配对多光谱虚拟H&E模型比较"),
    ("37852162", "P1", "structure_preservation", "method", "FFPE++：对比式无配对质量增强"),
    ("38198253", "P1", "multi_domain_translation", "method", "风格字典引导的多域渐进染色迁移"),
    ("38574542", "P1", "normalization_wsi", "method", "WSI多域Cycle一致染色标准化"),
    ("39069201", "P0", "clinical_validation", "external_validation", "自体荧光虚拟染色的专家与AI临床级验证"),
    ("39087085", "P0", "clinical_validation", "biomarker_validation", "H&E到Ki-67转换及标记指数实验验证"),
    ("40158294", "P1", "virtual_ihc", "biomarker_validation", "H&E推断肿瘤相关巨噬细胞的虚拟染色平台"),
    ("37932315", "P1", "clinical_validation", "quantitative_validation", "面向单细胞像素级与定量分析的虚拟染色"),
    ("38231822", "P1", "label_free_to_he", "wsi_pipeline", "PARS无标记组织学的自动全切片成像"),
    ("36328671", "P0", "benchmark", "risk_evaluation", "CycleGAN虚拟染色可信性与伪影风险评价"),
]


SEGMENTATION_EXTERNAL = [
    ("fcn-2015", "P1", 2015, "Fully Convolutional Networks for Semantic Segmentation", "generic_semantic", "architecture_baseline", "https://openaccess.thecvf.com/content_cvpr_2015/html/Long_Fully_Convolutional_Networks_2015_CVPR_paper.html"),
    ("unet-2015", "P0", 2015, "U-Net: Convolutional Networks for Biomedical Image Segmentation", "generic_semantic", "architecture_baseline", "https://arxiv.org/abs/1505.04597"),
    ("mask-rcnn-2017", "P0", 2017, "Mask R-CNN", "generic_instance", "architecture_baseline", "https://openaccess.thecvf.com/content_ICCV_2017/html/He_Mask_R-CNN_ICCV_2017_paper.html"),
    ("deeplabv3plus-2018", "P1", 2018, "Encoder-Decoder with Atrous Separable Convolution for Semantic Image Segmentation", "generic_semantic", "architecture_baseline", "https://openaccess.thecvf.com/content_ECCV_2018/html/Liang-Chieh_Chen_Encoder-Decoder_with_Atrous_ECCV_2018_paper.html"),
    ("stardist-2018", "P0", 2018, "StarDist: Object Detection with Star-convex Shapes", "microscopy_instance", "tool_baseline", "https://arxiv.org/abs/1806.03535"),
    ("nnunet-2021", "P1", 2021, "nnU-Net: a self-configuring method for deep learning-based biomedical image segmentation", "auto_config_baseline", "tool_baseline", "https://www.nature.com/articles/s41592-020-01008-z"),
    ("cellpose-2021", "P0", 2021, "Cellpose: a generalist algorithm for cellular segmentation", "microscopy_instance", "tool_baseline", "https://www.nature.com/articles/s41592-020-01018-x"),
    ("mesmer-2022", "P1", 2022, "A deep learning-enabled segmentation of ambiguous bioimages", "whole_cell", "tool_baseline", "https://www.nature.com/articles/s41587-021-01094-0"),
    ("sam-2023", "P1", 2023, "Segment Anything", "prompt_foundation", "architecture_baseline", "https://arxiv.org/abs/2304.02643"),
    ("micro-sam-2025", "P1", 2025, "Segment Anything for Microscopy", "prompt_foundation", "tool_baseline", "https://www.nature.com/articles/s41592-024-02580-4"),
    ("transunet-2021", "P1", 2021, "TransUNet: Transformers Make Strong Encoders for Medical Image Segmentation", "transformer_foundation", "architecture_baseline", "https://arxiv.org/abs/2102.04306"),
    ("swin-unet-2021", "P1", 2021, "Swin-Unet: Unet-like Pure Transformer for Medical Image Segmentation", "transformer_foundation", "architecture_baseline", "https://arxiv.org/abs/2105.05537"),
]


VIRTUAL_EXTERNAL = [
    ("reinhard-2001", "P1", 2001, "Color transfer between images", "normalization_classical", "algorithm_baseline", "https://doi.org/10.1109/38.946629"),
    ("macenko-2009", "P0", 2009, "A method for normalizing histology slides for quantitative analysis", "normalization_classical", "pathology_baseline", "https://doi.org/10.1109/ISBI.2009.5193250"),
    ("vahadane-2016", "P0", 2016, "Structure-Preserving Color Normalization and Sparse Stain Separation for Histological Images", "normalization_classical", "pathology_baseline", "https://doi.org/10.1109/TMI.2016.2529665"),
    ("pix2pix-2017", "P0", 2017, "Image-to-Image Translation with Conditional Adversarial Networks", "paired_translation", "architecture_baseline", "https://openaccess.thecvf.com/content_cvpr_2017/html/Isola_Image-To-Image_Translation_With_CVPR_2017_paper.html"),
    ("cyclegan-2017", "P0", 2017, "Unpaired Image-to-Image Translation using Cycle-Consistent Adversarial Networks", "unpaired_translation", "architecture_baseline", "https://openaccess.thecvf.com/content_ICCV_2017/html/Zhu_Unpaired_Image-To-Image_Translation_ICCV_2017_paper.html"),
    ("staingan-2019", "P0", 2019, "StainGAN: Stain Style Transfer for Digital Histological Images", "normalization_gan", "pathology_baseline", "https://doi.org/10.1109/ISBI.2019.8759152"),
    ("cut-2020", "P1", 2020, "Contrastive Learning for Unpaired Image-to-Image Translation", "unpaired_translation", "architecture_baseline", "https://www.ecva.net/papers/eccv_2020/papers_ECCV/html/3229_ECCV_2020_paper.php"),
]


TRACKS = {
    "segmentation": [
        ("generic_semantic", "通用语义分割基线", 3),
        ("generic_instance", "通用实例分割基线", 1),
        ("classical_nuclei", "早期核分割", 2),
        ("pathology_instance", "病理核/腺体实例分割", 6),
        ("gland_instance", "腺体实例分割", 3),
        ("tissue_semantic", "组织结构语义分割", 5),
        ("joint_detection_typing", "核检测—分割—分类联合建模", 5),
        ("whole_cell", "核与全细胞分割", 3),
        ("interactive_prompt", "交互式/提示式分割", 2),
        ("cross_stain_generalization", "染色感知与跨染色泛化", 3),
        ("transformer_foundation", "Transformer与细胞基础模型", 3),
        ("prompt_foundation", "SAM类病理基础模型", 3),
        ("benchmark", "数据集、挑战与受控基准", 5),
        ("generative_segmentation", "生成式/扩散分割", 1),
    ],
    "virtual-staining": [
        ("normalization_classical", "经典染色标准化", 4),
        ("normalization_gan", "GAN染色标准化", 3),
        ("normalization_fast", "快速轻量标准化", 1),
        ("normalization_contrastive", "对比式标准化", 1),
        ("normalization_diffusion", "扩散式标准化", 1),
        ("normalization_wsi", "全切片标准化", 2),
        ("paired_translation", "配对图像转换基线", 1),
        ("unpaired_translation", "无配对染色转换", 6),
        ("multi_domain_translation", "多域/多对多转换", 3),
        ("structure_preservation", "结构保持与错位鲁棒", 3),
        ("label_free_to_he", "无标记成像到H&E", 8),
        ("in_vivo_virtual_histology", "活体/术中虚拟组织学", 2),
        ("virtual_ihc", "虚拟IHC与标志物", 3),
        ("virtual_multistain", "虚拟多重染色", 3),
        ("clinical_validation", "病理医师与外部验证", 3),
        ("benchmark", "架构与可信性基准", 3),
    ],
}


CURRENT_TRACK_MAP = {
    "segmentation": {
        "nuclei_instance": "pathology_instance", "gland_instance": "gland_instance",
        "multi_object": "tissue_semantic", "nuclei_instance_classification": "joint_detection_typing",
        "weak_supervision": "interactive_prompt", "tissue_structure": "tissue_semantic",
        "nuclei_semantic": "classical_nuclei", "benchmark": "benchmark",
    },
    "virtual-staining": {
        "label_free_to_he": "label_free_to_he", "stain_to_stain": "unpaired_translation",
        "benchmark": "benchmark", "multi_domain_translation": "multi_domain_translation",
        "nonfixed_tissue": "in_vivo_virtual_histology", "virtual_multiplex": "virtual_multistain",
        "virtual_multistain": "virtual_multistain", "misalignment_robust": "structure_preservation",
    },
}


def read_selected(project: Path) -> list[dict]:
    return [json.loads(line) for line in (project / "selected_papers.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def local_records(conn: sqlite3.Connection, specs: list[tuple]) -> list[dict]:
    output = []
    for pmid, priority, track, role, rationale in specs:
        row = conn.execute(
            "SELECT pmid, doi, title, year, citation_count, full_text_status, pmc_id FROM papers WHERE pmid=?",
            (pmid,),
        ).fetchone()
        if row is None:
            output.append({"candidate_id": f"PMID:{pmid}", "pmid": pmid, "priority": priority,
                           "track": track, "role": role, "rationale": rationale,
                           "source": "local_db_expected", "full_text_status": "missing_metadata",
                           "next_action": "重新检索并导入元数据"})
            continue
        item = dict(row)
        status = item.get("full_text_status") or "pending"
        item.update({"candidate_id": f"PMID:{pmid}", "priority": priority, "track": track,
                     "role": role, "rationale": rationale, "source": "local_db"})
        item["next_action"] = "可直接生成总结" if status in {"available", "pdf_available"} else "补充全文后生成总结"
        item["summary_type"] = "full_method_summary"
        output.append(item)
    return output


def external_records(specs: list[tuple]) -> list[dict]:
    return [{
        "candidate_id": candidate_id, "pmid": None, "priority": priority, "year": year,
        "citation_count": None, "title": title, "track": track, "role": role,
        "rationale": "通用或领域基础方法；用于建立公平比较坐标，不与病理专用论文混为一类",
        "source": "external_primary_paper", "source_url": url, "full_text_status": "external",
        "next_action": "导入原始论文或建立精简基线卡", "summary_type": "baseline_card",
    } for candidate_id, priority, year, title, track, role, url in specs]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def build_matrix(topic: str, project: Path, candidates: list[dict]) -> str:
    current = read_selected(project)
    current_counts = Counter(CURRENT_TRACK_MAP[topic].get(row.get("track"), row.get("track")) for row in current)
    candidate_counts = Counter(row["track"] for row in candidates)
    ready_counts = Counter(row["track"] for row in candidates if row.get("full_text_status") in {"available", "pdf_available"})
    lines = [
        f"# {('病理分割' if topic == 'segmentation' else '虚拟染色')}扩充缺口矩阵",
        "",
        "> 统计口径：现有逐篇总结 + 本轮候选。通用模型原始论文作为“基线卡”，病理专用论文才进入完整方法总结，二者不做无条件性能排名。",
        "",
        "| 方法轨道 | 现有 | 新候选 | 其中全文就绪 | 建议最低覆盖 | 扩充后状态 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for key, label, target in TRACKS[topic]:
        now, new, ready = current_counts[key], candidate_counts[key], ready_counts[key]
        total = now + new
        status = "已达目标" if total >= target else f"仍缺 {target-total}"
        lines.append(f"| {label} (`{key}`) | {now} | {new} | {ready} | {target} | {status} |")
    local = [r for r in candidates if r["source"] == "local_db"]
    external = [r for r in candidates if r["source"] == "external_primary_paper"]
    ready = [r for r in local if r["full_text_status"] in {"available", "pdf_available"}]
    manual = [r for r in local if r not in ready]
    lines.extend([
        "", "## 执行批次", "",
        f"- A批：本地全文已就绪 {len(ready)} 篇，可直接追加完整总结。",
        f"- B批：本地有元数据但缺全文 {len(manual)} 篇，先自动抓取或人工补充。",
        f"- C批：外部通用基线 {len(external)} 篇，建议生成精简基线卡，不挤占病理专用高引论文名额。",
        "- P2条目作为观察清单，等引用、复现或外部验证证据积累后再升级。",
        "", "## 当前主要缺口", "",
    ])
    gaps = [(label, max(0, target - current_counts[key])) for key, label, target in TRACKS[topic]]
    for label, gap in sorted(gaps, key=lambda x: x[1], reverse=True)[:6]:
        lines.append(f"- {label}：相对现有库尚需补足约 {gap} 个代表条目。")
    lines.extend(["", "## 证据与比较规则", "",
                  "- 高引用只用于候选排序，不能替代方法创新、全文可核验性和病理适用性。",
                  "- 数据集/挑战论文单列为基准贡献；通用架构单列为基线卡。",
                  "- 分割指标需按语义/实例/检测/分类任务区分；虚拟染色需区分视觉相似、结构保真、下游任务和诊断验证。",
                  "- 不同数据集、组织、染色、扫描仪或划分协议的数值不得直接排名。",
                  ""])
    return "\n".join(lines)


def build_report(topic: str, project: Path, candidates: list[dict]) -> str:
    label = "病理分割" if topic == "segmentation" else "虚拟染色"
    lines = [f"# {label}候选扩充清单", "",
             "候选按 P0（优先补齐主干）、P1（扩大覆盖）、P2（观察）分层。全文状态来自本地数据库当前快照。",
             "", "| 优先级 | 年份 | 候选 | 轨道 | 角色 | 引用 | 全文 | 下一步 |", "|---|---:|---|---|---|---:|---|---|"]
    for row in sorted(candidates, key=lambda r: (r["priority"], -(r.get("citation_count") or 0), r.get("year") or 0)):
        title = str(row.get("title") or row["candidate_id"]).replace("|", "\\|")
        if row.get("source_url"):
            title = f"[{title}]({row['source_url']})"
        elif row.get("pmid"):
            title = f"{title} (PMID {row['pmid']})"
        lines.append(f"| {row['priority']} | {row.get('year') or ''} | {title} | `{row['track']}` | {row['role']} | {row.get('citation_count') or ''} | {row['full_text_status']} | {row['next_action']} |")
    lines.extend(["", f"总候选 {len(candidates)} 项；详细机器可读记录见 `expansion_candidates.jsonl`。", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB)
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    configs = [
        ("segmentation", ROOT / "segmentation-method-summary", SEGMENTATION_LOCAL, SEGMENTATION_EXTERNAL),
        ("virtual-staining", ROOT / "virtual-staining-method-summary", VIRTUAL_LOCAL, VIRTUAL_EXTERNAL),
    ]
    for topic, project, local_specs, external_specs in configs:
        selected_pmids = {str(row["pmid"]) for row in read_selected(project)}
        overlap = selected_pmids.intersection({row[0] for row in local_specs})
        if overlap:
            raise RuntimeError(f"{topic} candidates overlap current selection: {sorted(overlap)}")
        candidates = local_records(conn, local_specs) + external_records(external_specs)
        write_jsonl(project / "expansion_candidates.jsonl", candidates)
        (project / "expansion_candidates.md").write_text(build_report(topic, project, candidates), encoding="utf-8")
        (project / "coverage_gap_matrix.md").write_text(build_matrix(topic, project, candidates), encoding="utf-8")
        print(json.dumps({"topic": topic, "current": len(selected_pmids), "candidates": len(candidates),
                          "ready": sum(r.get("full_text_status") in {"available", "pdf_available"} for r in candidates)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
