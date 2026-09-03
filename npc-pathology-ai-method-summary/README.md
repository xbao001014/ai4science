# 鼻咽癌（NPC）病理 AI 方法库（起步包）

本目录积累 **鼻咽癌相关病理 / 数字病理 / WSI AI** 的筛选协议、首批入选清单与任务分轨短总览。

## 证据起点

- Focus PMID 核：`../fulltext_workflow/data/npc_focus_pmids.txt`（22 条）
- 病种概念 / Gap focus：`nasopharyngeal carcinoma`、`NPC`、`鼻咽癌`（`disease_synonyms.py`，方信 `BY_BNAI`）
- 检索查询组：`search_queries.py` → `nasopharyngeal_carcinoma_pathology_ai`

## 目录说明

| 文件 | 用途 |
|------|------|
| `screening_protocol.md` | 病理 AI 纳入/排除与任务分轨 |
| `selected_papers.jsonl` | 13 篇核心病理/WSI 入选 |
| `expansion_candidates.jsonl` | 影像为主、临床 ML、综述等待扩条目 |
| `npc_pathology_ai_overview.md` | 第一阶段任务地图 |

## 边界

- **核心：** 病理图像 / WSI / IHC 数字分析为主模态。
- **Reserve：** PET/MRI 放射组学为主、仅用 WSI 做相关性解释者。
- **Exclude：** 致编辑信、纯临床 SEER 预测、无组织病理的筛查模态（如血清 IFA）。

逐篇 method_summary 后置；本轮以清单 + 总览为主。
