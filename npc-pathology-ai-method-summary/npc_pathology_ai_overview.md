# 鼻咽癌病理 AI 短总览（第一阶段）

**证据范围：** 基于 `npc_focus_pmids.txt` 22 条 PMID 筛查；**13 篇核心病理/WSI** 入选，8 篇 Reserve、1 篇 Exclude 见 `expansion_candidates.jsonl`。**非完备系统综述**；逐篇 method_summary 待补。

## 1. 领域背景

鼻咽癌（NPC）在华南高发，病理以 **非角化型** 为主，间质富含淋巴细胞，与 EBV 感染密切相关。病理 AI 的难点包括：肿瘤与炎症/淋巴组织鉴别、WSI 尺度巨大、弱标注成本高、以及 **TIL/免疫微环境** 与预后/免疫治疗的强关联。

## 2. 任务分轨地图

### 轨 1：诊断 / 分类（活检 patch → WSI）

| PMID | 年 | 要点 |
|------|-----|------|
| 32098314 | 2020 | 早期 NPC 活检 patch/slide CNN，AUC≈0.99，奠定可行性 |
| 42225742 | 2026 | 马来多中心 WSI 四类（normal/LHP/NPI/NPC），MobileNet/EfficientNet 融合 |

**趋势：** 从 patch 活检到 WSI 多类；类别不平衡与东南亚人群外部验证是落地关键。

### 轨 2：弱监督 WSI

| PMID | 年 | 要点 |
|------|-----|------|
| 38959144 | 2024 | WS-T2T-ViT；802 张单中心 WSI；每张随机 500 tiles 继承 slide 标签；多分辨率 + 多尺度注意力 |

**与 MIL 库衔接：** 弱监督 WSI 分类可对照 `mil-method-summary/` 中 AB-MIL、CLAM、TransMIL 叙事；38959144 采用 tile 继承 slide 标签的经典弱监督 Transformer，而非经典 MIL 头。其五折验证均来自同一 NPC 中心，CAMELYON16 只证明跨任务可迁移性，不能替代独立 NPC 外部验证。

### 轨 3：TIL / 肿瘤微环境

| PMID | 年 | 要点 |
|------|-----|------|
| 40614660 | 2025 | TILDL% 自 H&E WSI，多队列预后 + ICB 转移队列 |
| 38136336 | 2023 | 核检测 + TIL 聚类 → 12 维分数 → locoregional recurrence 风险 |
| 35637194 | 2022 | lncRNA 免疫签名（组学为主）+ 数字病理验证浸润 |

**要点：** NPC 富 TIL，H&E 直接量化 TIL 比额外 IHC 更具临床转化潜力；40614660 已将 TILDL 与 CD3/CD8/CD20 IHC 做相关验证。

### 轨 4：虚拟染色 / IHC 辅助 / 蛋白定量

| PMID | 年 | 要点 |
|------|-----|------|
| 39061821 | 2024 | H&E→EBER 虚拟染色 + 先验驱动分类，免人工标注 |
| 38132269 | 2023 | Pan-CK/EBER 辅助非病理医生标注 H&E |
| 39869565 | 2025 | G3BP1 IHC WSI 自动定量 + 预后 |

**与 HE-IHC 库衔接：** 39061821 是 NPC 特异的「H&E→功能染色」案例；39869565 属于 IHC 数字定量而非从 H&E 预测。

### 轨 5：Pathomics / Radiopathomics

| PMID | 年 | 要点 |
|------|-----|------|
| 33403013 | 2020 | WSI 病理签名 + MRI 放射组学 nomogram（FFS） |
| 39249584 | 2024 | Swin pathomics + MRI → PFS |
| 40409367 | 2025 | WSI 自注意力 + MRI 融合 → OS |
| 40556946 | 2025 | MRI 放射组学为主，WSI/IHC 做 radiology-pathology 相关解释 |

**边界：** 40556946 等以影像建模为主，病理侧用于生物学解释；纳入 P1 但须在汇报中区分 **预测输入** vs **解释性关联**。

## 3. Reserve 说明（未进核心 13 篇）

- **影像为主：** 42180916、40641917、40357637、35090572、31338709（PET/MRI 放射组学）。
- **临床 ML：** 37268685（SEER 生存，无病理图）。
- **非组织病理：** 35750258（血清 IFA）。
- **综述：** 38276183。
- **Exclude：** 36334695（致编辑信）。

## 4. 共性挑战（写 review 时可作讨论节）

1. **组织学相似性：** NPC 与淋巴增生/炎症鉴别困难 → 需多中心 WSI 与 hard negative。
2. **EBV 轴：** EBER 虚拟染色（39061821）与 EBV 血清学/分子标志物如何协同尚未形成统一 pipeline。
3. **TIL 作为 hub 生物标志物：** 40614660、38136336 显示 H&E TIL 可链预后与 ICB；与 HE→IHC 库中「微环境 IHC 代理」方向一致。
4. **证据分级：** 13 篇核心中多篇单中心或内部验证；外部验证与前瞻性研究仍偏少。
5. **H&E→Ki67/IHC 在 NPC 的空白：** 当前 focus 核中 **未见** NPC 专用 Ki-67 虚拟染色或 H&E→Ki67 预测；可借 HE-IHC 库泛癌方法 + 本地 `ihc_biomarker_prediction_ai` 查询补候选。

## 5. 下一步扩库

1. 用 Gap UI focus=`nasopharyngeal carcinoma` 扩 PMID 并更新 jsonl。
2. 对 P0 七篇按需补 `method_summaries/`（32098314、42225742、38959144、39061821、38132269、40614660、38136336）；38959144 全文已位于 `fulltext_workflow/raw/manual/`。
3. 交叉引用：`mil-method-summary/`（弱监督 WSI）、`he-ihc-prediction-method-summary/`（IHC 代理）。

## 6. 索引

- 核心清单：`selected_papers.jsonl`（13 篇）
- 待扩/Reserve：`expansion_candidates.jsonl`
- Focus 核：`../fulltext_workflow/data/npc_focus_pmids.txt`
