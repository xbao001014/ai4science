# Extractor 实体粒度对齐与后处理维护说明

> 维护入口：`extractor/entity_normalize.py`（确定性过滤）+ `extractor/section_extractor.py`（LLM prompt 政策）  
> 单测：`tests/test_entity_normalize.py`  
> 目标：抽取结果贴近病理 AI 科研/临床可用粒度，并与方信可行性（无影像、偏病理亚型）对齐。

---

## 1. 总体策略

抽取分两层：

| 层 | 位置 | 作用 |
|----|------|------|
| Prompt 政策 | `section_extractor._BASE_SYSTEM` / `_SECTION_HINTS` | 引导 LLM 直接产出正确粒度与**本文研究内容** |
| 后处理 | `entity_normalize.postprocess_triples` | 兜底过滤漏网的伞词、训练套路、过粗 Disease、放射影像 Modality；Method 贡献/对比冲突消解 |

**原则**：prompt 定意图；名单/规则可维护、可单测。发现线上噪音时，优先补后处理名单，必要时再改 prompt 正反例。

**研究内容优先（Study-content）**：Paper→X 只保留本文队列、任务、提出/采用方法、实验对比方法、所用模态/数据集、报告指标与作者自述局限；related work / 背景举例不抽。

语料与检索侧（`search_queries.py`）已聚焦病理 AI；`pathomics_radiomics` 默认关闭。粒度政策应与此一致，不鼓励 CT/MRI radiomics 方向。

---

## 2. Method：骨干 + 贡献级（政策 B）

### 2.1 期望粒度

**保留**

- 命名骨干 / 模型：`resnet-50`、`vit`、`u-net`
- 命名算法 / 框架 / 工具：`hover-net`、`clam`、`transmil`、`qupath`
- 论文核心模块 / 算法贡献：`dual-attention mil`、`cross-attention fusion module`

**不保留**

- 领域伞词：`deep learning`、`machine learning`、`AI`、`pathomics`、`digital pathology`…
- 训练 / 工程套路：`early stopping`、`data augmentation`、`adam`、`learning rate schedule`、`mixup`、`dropout`、`transfer learning`（单独出现）等

### 2.2 后处理维护点（`entity_normalize.py`）

| 符号 | 行为 | 何时改 |
|------|------|--------|
| `_GENERIC_METHODS` | 伞词；若同批已有更具体 Method 则丢弃；若仅有伞词则保留但 `confidence≤0.5` | 新伞词反复出现时追加 |
| `_LOW_VALUE_METHODS` | 精确匹配；**一律丢弃**（即使是唯一 Method） | 新训练/工程噪音精确名 |
| `_LOW_VALUE_METHOD_PATTERNS` | 正则匹配；一律丢弃 | 变体拼写（如 `early-stop`、`lr schedule`） |
| `_NO_PAPER_METHOD_SECTIONS` | `discussion` / `future_work` / `introduction` 禁止 `APPLIES_METHOD` 与 `COMPARES_METHOD` | 一般不改 |
| 贡献优先于对比 | 同名 Method 同时有两列时保留 `APPLIES_METHOD`、丢弃 `COMPARES_METHOD` | 一般不改 |

相关函数：`is_generic_method`、`is_low_value_method`。

### 2.3 Method 两列

| Relation | 含义 |
|----------|------|
| `APPLIES_METHOD` | 本文提出或采用的核心方法 |
| `COMPARES_METHOD` | 本文实验中明确对比的 baseline |

仅引用、未参与本文实验的方法：两列都不保留。`repair_triple_relation` 在 object 为 Method 时默认映射到 `APPLIES_METHOD`，**不会**自动发明 `COMPARES_METHOD`。

### 2.4 Prompt 同步

改名单后，检查 `section_extractor` 中 Method 政策与 Examples 是否仍一致（尤其 BAD 例是否覆盖新噪音）。

---

## 3. Disease：亚型 / 分子分型级（政策 C）

### 3.1 期望粒度

**优先（文中明确写出时）**

- 组织学亚型：`lung adenocarcinoma`、`invasive ductal carcinoma`
- 分子 / 临床分型：`her2-positive invasive ductal carcinoma`、`msi-high colorectal adenocarcinoma`、`egfr-mutant lung adenocarcinoma`

**有更细实体时丢弃**

- 器官级：`breast cancer`、`nsclc`、`colorectal cancer`
- 裸伞词：`cancer`、`tumor`、`malignancy`、`carcinoma`（单独）

**仅当文中无亚型时**

- 可保留器官级：`breast cancer`、`nsclc`

**禁止推断**：文未写 HER2/MSI/EGFR 等，不得补全。

### 3.2 后处理维护点

| 符号 | 行为 | 何时改 |
|------|------|--------|
| `_GENERIC_DISEASES` | 裸伞词，**一律丢弃** | 新泛词（如 `lesion` 滥用） |
| `_ORGAN_LEVEL_DISEASES` | 器官级名单；同批有更细同器官 Disease 时丢弃 | 新器官大类别名 |
| `_ORGAN_LEVEL_PATTERN` | 形如 `<site> cancer/carcinoma/tumor` 的启发式器官级 | 误伤亚型时收紧 |
| `_ORGAN_HINTS` | 器官关键词 → 用于同器官配对 | 新部位 / 别名 |
| `_HISTOLOGY_TO_ORGAN` | 组织学短语暗示器官（如 IDC → breast），用于「名称不含 breast」时仍能丢掉 `breast cancer` | 新「省略器官」的病理学术语 |
| `_SUBTYPE_MARKERS` | 含这些标记则**不视为**器官级 | 新分子/组织学标记词 |

相关函数：`is_generic_disease`、`is_organ_level_disease`、`has_more_specific_disease`、`should_drop_disease`。

### 3.3 同批配对逻辑（简图）

```
同 section 的 Disease 集合 cohort
  ├─ 在 _GENERIC_DISEASES           → 丢弃
  ├─ 是器官级，且 cohort 中存在更细同器官/包含关系 → 丢弃
  └─ 否则保留（含「仅有器官级」的情况）
```

「更细」判定要点：

1. 粗名是细名的真子串（`breast cancer` ⊂ `her2-positive breast cancer`）
2. 共享器官（`_ORGAN_HINTS` / `_HISTOLOGY_TO_ORGAN`），且粗为器官级、细非器官级

### 3.4 与方信可行性的关系

后处理**不**做 DiseaseCode 映射；映射仍在 `feasibility/disease_mapper.py` / `analysis/disease_synonyms.py`。  
粒度对齐的目标是让 KG 中的 Disease 字符串更接近可映射的亚型，而不是在抽取阶段写死方信编码。

---

## 4. Modality：仅病理数据模态

### 4.1 期望粒度

**保留**

- 病理 / 数字病理数据模态：`wsi`、`h&e`、`ihc`、`cytology`、`spatial transcriptomics`、多重免疫荧光等

**不保留**

- 放射影像：`ct`、`mri`、`pet`、`ultrasound`、`mammography`、`radiomics`、`medical imaging`…
- 过细工程信息：扫描仪品牌/型号、放大倍数、像素尺寸

### 4.2 后处理维护点

| 符号 | 行为 | 何时改 |
|------|------|--------|
| `_RADIOLOGY_MODALITIES` | 精确匹配放射/影像伞词，**一律丢弃** | 新影像噪音名 |
| `_RADIOLOGY_MODALITY_PATTERNS` | 正则匹配变体 | 拼写变体 |
| `_MODALITY_ALIASES` | 规范化（`whole slide image` → `wsi`，`immunohistochemistry` → `ihc`） | 常见同义写法 |

相关函数：`is_radiology_modality`；`normalize_entity_name(..., "Modality")`。

### 4.3 Prompt 同步

`section_extractor` 中 Modality policy 与 Examples（含 CT/MRI BAD 例）需与名单一致。

---

## 5. Relation ↔ Object Type 一致性

入库时除 `RELATED_TO` 外，subject 恒为 Paper；**object.type 必须与 relation 对齐**。

| Relation | 期望 object.type |
|----------|------------------|
| `APPLIES_METHOD` | Method |
| `COMPARES_METHOD` | Method |
| `PERFORMS_TASK` | Task |
| `TARGETS_DISEASE` | Disease |
| `OPERATES_ON` | Tissue |
| `USES_DATASET` | Dataset |
| `ACHIEVES_METRIC` | Metric |
| `USES_MODALITY` | Modality |
| `REPORTS_LIMITATION` | Limitation |
| `RELATED_TO` | Method→Method |

**根因**：旧 prompt JSON 示例曾写成 `APPLIES_METHOD` + object `Task`，导致大量误用。

**修复**：

1. Prompt 写明 relation→object 对照，并给出正确示例  
2. `repair_triple_relation`：不一致时**按 object.type 改写 relation**（实体类型通常更可信）；非法 `RELATED_TO` 丢弃  

维护：改 schema 时同步 `_RELATION_EXPECTED_OBJECT` / `_OBJECT_CANONICAL_RELATION` 与 prompt。

---

## 6. Limitation

| 符号 | 行为 |
|------|------|
| `_LIMITATION_ALIASES` | 规范化常见 limitation 措辞（如 `limited sample size` → `small sample size`） |

粒度政策主要在 prompt；别名表按需追加即可。

---

## 7. Dataset：公开 / 私有（access_class）

关系仍为 `USES_DATASET`。实体列 `entities.access_class` ∈ `public|private|unknown`。

| 来源 | 行为 |
|------|------|
| `PUBLIC_DATASET_ALIASES`（`extractor/dataset_access.py`） | 命中 → **强制 public** |
| 私有线索（in-house / institutional / our hospital…） | → private（未命中公开名单时） |
| LLM `access_hint` | 名单未命中时采用 |
| 默认 | unknown |

冲突升级：`public` > `private` > `unknown`（`upsert_entity` 合并）。

Proposal：方信为主队列；公开数据集可作预训练/外验/对比，正文必须标注 `public dataset: <name>`；方信可行时不得仅用公开数据替代。

下游消费：**V-03**（`analysis/public_dataset_feasibility.py` / 工具 `public_dataset_assess`）按 focus 相关论文选出 `access_class=public` 的数据集，供 idea-pipeline / gap_ui / Research Proposal 并行参考（不并入方信 `feasibility_score`）。

维护：新基准数据集追加到 `PUBLIC_DATASET_ALIASES`，并补 `tests/test_dataset_access.py`。

---

## 8. 维护工作流（推荐）

1. **复现噪音**：从 `relations` 找出不良实体名，或 `relation`/`object_type` 不一致行。
2. **先改后处理**：追加名单 / 关系修复规则；在 `tests/test_entity_normalize.py` 增加用例。
3. **再改 prompt**（可选）：在 Examples 的 BAD/GOOD 中补一条。
4. **回归**：

```powershell
cd fulltext_workflow
& ..\.venv\Scripts\python.exe -m pytest tests/test_entity_normalize.py -q
```

5. **重抽验证**（小样本）见 `scripts/reset_extraction.py` / `bootstrap_raw_sample.py`。

---

## 9. 相关文件索引

| 文件 | 内容 |
|------|------|
| `extractor/section_extractor.py` | Method / Disease / Modality / Relation / Dataset prompt |
| `extractor/entity_normalize.py` | 粒度后处理 + `repair_triple_relation` |
| `extractor/dataset_access.py` | Dataset `access_class` 公开名单与解析 |
| `analysis/public_dataset_feasibility.py` | V-03 公开数据集可行性（消费 access_class） |
| `extractor/study_classifier.py` | 研究类型分类 prompt |
| `tests/test_entity_normalize.py` | 粒度与关系修复单测 |
| `tests/test_dataset_access.py` | Dataset 公开/私有解析单测 |
| `tests/test_public_dataset_feasibility.py` | V-03 状态与论文中介选集 |
| `../search_queries.py` | PubMed 检索主题（病理 AI，14 组启用） |
| `scripts/bootstrap_raw_sample.py` | 从 `raw/` 装载样本并抽取 |
| `scripts/reset_extraction.py` | 重置已抽取结果以便重抽 |

---

## 10. 变更记录（摘要）

| 日期 | 变更 |
|------|------|
| 2026-07-18 | Method 政策 B：prompt + 低价值 Method 黑名单 |
| 2026-07-18 | Disease 政策 C：prompt + 泛词/器官级后处理与组织学→器官启发式 |
| 2026-07-18 | 检索与 agent 措辞对齐病理 AI；`pathomics_radiomics` 默认关闭 |
| 2026-07-18 | Modality：仅病理模态；放射影像黑名单 + 别名规范化 |
| 2026-07-18 | Relation 误用修复：prompt 对照表 + `repair_triple_relation` |
| 2026-07-19 | Dataset `access_class`：公开名单优先；proposal 方信优先 + 公开数据须标注 |
