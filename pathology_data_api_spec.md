# 病理信息系统数据对接接口规范

> **文档用途**：供方信医疗病理信息系统（LIS/PAIS）开发团队参考，说明研究院侧的知识图谱与 Idea 挖掘 Agent 需要哪些数据查询能力，以实现「研究空白 → 数据可行性核验 → 假说生成」的自动化闭环。  
> **数据安全原则**：所有接口均为**只读查询**，仅返回统计/元数据，不涉及原始病理图像或患者可识别信息（PII）传输。数据不出域，研究院侧通过 API 调用获取聚合结果。

---

## 一、接口总览

| 模块 | 接口编号 | 接口名称 | 用途 |
|------|----------|----------|------|
| 数据目录 | D-01 | 病种目录查询 | 获取全量可用病种与分类体系 |
| 数据目录 | D-02 | 任务类型查询 | 获取每个病种支持的 AI 任务类型 |
| 数据规模 | S-01 | 病种样本量统计 | 按病种返回病例数、切片数 |
| 数据规模 | S-02 | 时间分布查询 | 样本时间跨度与年份分布 |
| 数据规模 | S-03 | 队列人口学分布 | 性别/年龄/地区分布（脱敏聚合） |
| 标注状态 | A-01 | 标注类型目录 | 每个病种的标注维度清单 |
| 标注状态 | A-02 | 标注完整率查询 | 各标注字段的覆盖率统计 |
| 标注状态 | A-03 | 标注质量指标 | 标注一致性/来源等质量属性 |
| 随访数据 | F-01 | 随访字段目录 | 可用随访指标（OS/DFS/复发等） |
| 随访数据 | F-02 | 随访完整率查询 | 随访数据覆盖率与时长分布 |
| 分子数据 | M-01 | 分子标记目录 | 可用基因/蛋白标记物列表 |
| 分子数据 | M-02 | 多模态配对查询 | 与 WSI 配对的分子数据比例 |
| 可行性核验 | V-01 | 研究假说可行性评估 | 给定条件，返回可用样本量 |
| 可行性核验 | V-02 | 数据缺口分析 | 指出假说所需但缺失的数据项 |
| 图像规格 | I-01 | WSI 技术参数查询 | 扫描仪型号、分辨率、染色类型 |
| 图像规格 | I-02 | 切片质量分布 | 对焦质量/伪影比例统计 |

---

## 二、接口详细说明

### 模块 D：数据目录

#### D-01 病种目录查询

**目的**：让 Idea Agent 知道图谱中哪些病种在方信数据库有实际数据支撑，确保生成假说的数据可行性。

```
GET /api/v1/catalog/diseases
```

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| organ_system | string | 否 | 系统筛选：`digestive` / `respiratory` / `urological` / `gynecological` / `hematological` / `neural` 等 |
| min_cases | integer | 否 | 最小病例数阈值，过滤样本量不足的病种（建议默认 50） |

**响应示例**

```json
{
  "total_disease_types": 87,
  "diseases": [
    {
      "disease_id": "GC-ADC",
      "name_zh": "胃腺癌",
      "name_en": "Gastric Adenocarcinoma",
      "organ_system": "digestive",
      "icd10_code": "C16.9",
      "total_cases": 3240,
      "total_wsi_slides": 8917,
      "has_ihc": true,
      "has_molecular": true,
      "has_followup": true,
      "data_since_year": 2016
    }
  ]
}
```

**知识图谱用途**：与图谱中 `Task.disease_type` 节点对齐，生成「已有充足数据 × 文献研究空白」的交叉矩阵。

---

#### D-02 任务类型查询

**目的**：了解每个病种支持哪些 AI 任务（分类/分割/生存预测等），与知识图谱 `Task` 节点匹配。

```
GET /api/v1/catalog/tasks
```

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| disease_id | string | 否 | 指定病种，不填则返回全量 |

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "supported_tasks": [
    {
      "task_type": "survival_prediction",
      "label_field": "overall_survival_months",
      "label_completeness": 0.91,
      "has_event_indicator": true,
      "min_followup_months": 6,
      "cohort_size": 2856
    },
    {
      "task_type": "molecular_subtype_classification",
      "label_field": "lauren_classification",
      "label_completeness": 0.78,
      "classes": ["intestinal", "diffuse", "mixed"],
      "cohort_size": 2530
    },
    {
      "task_type": "grade_classification",
      "label_field": "who_grade",
      "label_completeness": 0.99,
      "classes": ["G1", "G2", "G3"],
      "cohort_size": 3205
    },
    {
      "task_type": "region_segmentation",
      "annotation_type": "polygon",
      "annotated_slides": 420,
      "categories": ["tumor", "stroma", "necrosis", "normal"]
    }
  ]
}
```

**知识图谱用途**：Generator Agent 筛选「方信有标注数据」的任务，避免生成数据不可行的假说。

---

### 模块 S：数据规模

#### S-01 病种样本量统计

**目的**：提供精确的样本量数字，支持 Idea Agent 的可行性评估（统计功效计算）。

```
GET /api/v1/stats/sample-size
```

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| disease_id | string | 是 | 病种 ID |
| task_type | string | 否 | 任务类型过滤 |
| label_field | string | 否 | 指定标注字段 |

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "task_type": "survival_prediction",
  "total_cases": 2856,
  "total_slides": 7203,
  "slides_per_case_median": 2.4,
  "class_distribution": {
    "event_occurred": 1623,
    "censored": 1233
  },
  "estimated_trainable_size": 2284,
  "note": "排除质量不达标切片后的可用样本估算"
}
```

---

#### S-02 时间分布查询

**目的**：了解数据时间跨度，判断是否适合时序分析或多中心泛化研究。

```
GET /api/v1/stats/temporal-distribution
```

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "year_distribution": {
    "2016": 287,
    "2017": 334,
    "2018": 412,
    "2019": 489,
    "2020": 501,
    "2021": 563,
    "2022": 654
  },
  "earliest_case": "2016-01",
  "latest_case": "2023-11",
  "multi_center": false,
  "hospital_count": 1
}
```

---

#### S-03 队列人口学分布

**目的**：支持「华南/中国人群」独特性声明，这是方信私有数据的核心竞争力。

```
GET /api/v1/stats/demographics
```

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "total_cases": 3240,
  "sex": { "male": 2105, "female": 1135 },
  "age_group": {
    "under_40": 124,
    "40_59": 1287,
    "60_79": 1641,
    "80_plus": 188
  },
  "ethnicity_note": "以华南汉族为主，符合华南地区流行病学分布",
  "province": "Guangdong"
}
```

---

### 模块 A：标注状态

#### A-01 标注类型目录

**目的**：明确每个病种有哪些维度的标注，避免 Agent 生成依赖不存在标注的假说。

```
GET /api/v1/annotations/types
```

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "annotation_dimensions": [
    {
      "field_name": "lauren_classification",
      "field_type": "categorical",
      "categories": ["intestinal", "diffuse", "mixed"],
      "annotation_source": "pathologist_report",
      "annotated_cases": 2530,
      "coverage_rate": 0.78
    },
    {
      "field_name": "her2_status",
      "field_type": "categorical",
      "categories": ["positive", "negative", "equivocal"],
      "annotation_source": "ihc_report",
      "annotated_cases": 1890,
      "coverage_rate": 0.58
    },
    {
      "field_name": "tumor_budding_grade",
      "field_type": "ordinal",
      "categories": ["Bd1", "Bd2", "Bd3"],
      "annotation_source": "manual_pathologist",
      "annotated_cases": 380,
      "coverage_rate": 0.12,
      "note": "仅专项研究队列有此标注"
    }
  ]
}
```

---

#### A-02 标注完整率查询

**目的**：精确了解各字段覆盖率，为 Critic Agent 的可行性打分提供依据。

```
GET /api/v1/annotations/completeness
```

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| disease_id | string | 是 | 病种 ID |
| fields | array[string] | 否 | 指定字段列表，不填返回全部 |

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "fields_completeness": [
    { "field": "overall_survival_months", "coverage": 0.91, "missing_pattern": "random" },
    { "field": "disease_free_survival_months", "coverage": 0.83, "missing_pattern": "random" },
    { "field": "tnm_stage", "coverage": 0.97, "missing_pattern": "random" },
    { "field": "msi_status", "coverage": 0.41, "missing_pattern": "systematic",
      "note": "仅2020年后病例常规检测" }
  ]
}
```

---

#### A-03 标注质量指标

**目的**：评估标注可靠性，支持论文方法章节的数据质量描述。

```
GET /api/v1/annotations/quality
```

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "field": "lauren_classification",
  "annotation_source": "pathologist_report",
  "inter_annotator_agreement": {
    "available": false,
    "note": "单病理医生报告，无双重标注"
  },
  "pathologist_count": 12,
  "senior_pathologist_reviewed": true,
  "qc_protocol": "科室主任复核疑难病例",
  "label_noise_estimate": "low"
}
```

---

### 模块 F：随访数据

#### F-01 随访字段目录

**目的**：判断是否支持生存分析类研究（Cox 模型/深度生存网络），这是高分论文的重要方向。

```
GET /api/v1/followup/fields
```

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "followup_available": true,
  "fields": [
    {
      "field_name": "overall_survival_months",
      "event_field": "death_event",
      "available_cases": 2945,
      "median_followup_months": 42.3,
      "min_followup_months": 1,
      "max_followup_months": 96
    },
    {
      "field_name": "recurrence_free_survival_months",
      "event_field": "recurrence_event",
      "available_cases": 2210,
      "median_followup_months": 38.1
    }
  ],
  "followup_source": "医院电子病历系统（定期更新）",
  "last_updated": "2024-09"
}
```

---

#### F-02 随访完整率查询

```
GET /api/v1/followup/completeness
```

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "cases_with_any_followup": 2945,
  "cases_with_minimum_1year_followup": 2601,
  "cases_with_minimum_3year_followup": 1890,
  "cases_with_minimum_5year_followup": 1124,
  "lost_to_followup_rate": 0.09
}
```

---

### 模块 M：分子/多组学数据

#### M-01 分子标记目录

**目的**：支持「形态学 × 分子标记」多模态融合研究假说的可行性判断。

```
GET /api/v1/molecular/markers
```

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "molecular_markers": [
    {
      "marker_name": "HER2",
      "marker_type": "ihc",
      "assay_method": "immunohistochemistry",
      "available_cases": 1890,
      "result_format": "categorical",
      "categories": ["0", "1+", "2+", "3+"]
    },
    {
      "marker_name": "MSI_status",
      "marker_type": "molecular",
      "assay_method": "pcr_or_ngs",
      "available_cases": 1320,
      "result_format": "categorical",
      "categories": ["MSI-H", "MSS"]
    },
    {
      "marker_name": "EBV_status",
      "marker_type": "ish",
      "available_cases": 980,
      "result_format": "binary"
    },
    {
      "marker_name": "PD_L1_CPS",
      "marker_type": "ihc",
      "available_cases": 760,
      "result_format": "continuous",
      "unit": "CPS score"
    }
  ]
}
```

---

#### M-02 多模态配对查询

**目的**：确定 WSI 与分子数据的配对比例，评估多模态研究可用队列大小。

```
GET /api/v1/molecular/pairing-rate
```

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| disease_id | string | 是 | 病种 ID |
| markers | array[string] | 是 | 需要配对的分子标记列表 |

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "query_markers": ["HER2", "MSI_status"],
  "wsi_only": 3240,
  "wsi_with_HER2": 1890,
  "wsi_with_MSI_status": 1320,
  "wsi_with_all_markers": 980,
  "fully_paired_cohort_size": 980,
  "feasibility_note": "980例完整配对样本，满足多模态融合研究基本要求（建议≥500例）"
}
```

---

### 模块 V：研究可行性核验（Idea Agent 核心接口）

#### V-01 研究假说可行性评估

**目的**：Critic Agent 在评估每条假说时调用，返回「该假说在方信数据库中可用的样本量」。这是整个 Idea 挖掘闭环的关键数据输入。

```
POST /api/v1/feasibility/assess
```

**请求体**

```json
{
  "hypothesis_id": "H-2024-0312",
  "disease_id": "GC-ADC",
  "task_type": "survival_prediction",
  "required_labels": ["overall_survival_months", "death_event"],
  "required_molecular_markers": ["MSI_status"],
  "required_annotations": ["tnm_stage"],
  "min_followup_months": 12,
  "subgroup_filters": {
    "stage": ["III", "IV"]
  }
}
```

**响应示例**

```json
{
  "hypothesis_id": "H-2024-0312",
  "feasibility_score": 0.82,
  "available_cohort_size": 743,
  "breakdown": {
    "has_wsi": 3240,
    "has_survival_label": 2856,
    "has_msi_status": 1320,
    "has_tnm_stage": 3138,
    "meets_followup_threshold": 2601,
    "in_target_stage": 1187,
    "all_criteria_met": 743
  },
  "recommendation": "FEASIBLE",
  "note": "743例满足全部条件，建议80/20训练测试划分后训练集594例，可支撑深度学习建模"
}
```

**可行性评分规则（供参考）**

| 可行性得分 | 可用样本量 | 建议 |
|------------|------------|------|
| ≥ 0.8 | ≥ 500 | 直接推荐启动 |
| 0.5–0.8 | 200–499 | 可行，建议结合迁移学习或数据增强 |
| 0.2–0.5 | 50–199 | 风险较高，建议调整假说范围 |
| < 0.2 | < 50 | 数据不足，Idea 降级或舍弃 |

---

#### V-02 数据缺口分析

**目的**：当假说可行性不足时，精确指出缺少哪些数据，供 Evolution Agent 调整假说方向。

```
POST /api/v1/feasibility/gap-analysis
```

**请求体**（同 V-01）

**响应示例**

```json
{
  "hypothesis_id": "H-2024-0312",
  "gaps": [
    {
      "field": "msi_status",
      "current_coverage": 0.41,
      "required_coverage": 0.70,
      "bottleneck_severity": "HIGH",
      "suggestion": "可降级为不依赖MSI的形态学预测任务，或限定2020年后病例作为研究队列"
    },
    {
      "field": "min_followup_12months",
      "current_eligible": 2601,
      "after_msi_filter": 743,
      "bottleneck_severity": "MEDIUM",
      "suggestion": "样本量可接受，非主要瓶颈"
    }
  ],
  "alternative_hypothesis_suggestions": [
    "去除MSI条件，聚焦纯形态学生存预测（可用样本2601例）",
    "限定2020–2023年队列，MSI覆盖率升至0.76（可用样本489例）"
  ]
}
```

---

### 模块 I：图像规格

#### I-01 WSI 技术参数查询

**目的**：确认切片扫描参数，用于方法章节描述及判断是否需要多分辨率处理策略。

```
GET /api/v1/wsi/specs
```

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "scanners": [
    {
      "scanner_model": "Leica Aperio AT2",
      "slide_count": 5210,
      "magnification": "40x",
      "resolution_mpp": 0.2520,
      "format": "SVS",
      "staining": ["HE"]
    },
    {
      "scanner_model": "3DHISTECH Pannoramic 250",
      "slide_count": 2707,
      "magnification": "20x",
      "resolution_mpp": 0.4830,
      "format": "MRXS",
      "staining": ["HE", "IHC"]
    }
  ],
  "staining_types": {
    "HE": 7890,
    "IHC_HER2": 1240,
    "IHC_PD_L1": 760,
    "FISH": 320
  }
}
```

---

#### I-02 切片质量分布

**目的**：了解切片质控状态，方法章节需说明数据预处理与质量筛选流程。

```
GET /api/v1/wsi/quality-distribution
```

**响应示例**

```json
{
  "disease_id": "GC-ADC",
  "total_slides": 7917,
  "qc_status": {
    "passed": 7203,
    "failed_blur": 312,
    "failed_tissue_coverage": 198,
    "failed_staining_artifact": 204
  },
  "pass_rate": 0.910,
  "tissue_coverage_median": 0.68,
  "pen_marking_rate": 0.03,
  "air_bubble_rate": 0.02
}
```

---

## 三、接口调用场景与 Agent 对接逻辑

### 场景 A：Idea 生成前的数据地图构建（Phase 0 一次性调用）

```
D-01 → D-02 → S-01 → A-01 → F-01 → M-01
```

构建「方信数据全景图」，存入知识图谱的 `Dataset` 节点，作为所有后续 Idea 生成的数据可行性基底。

```python
# 伪代码示意
data_landscape = {}
for disease in get_diseases(min_cases=200):          # D-01
    data_landscape[disease.id] = {
        "tasks": get_tasks(disease.id),              # D-02
        "sample_size": get_sample_size(disease.id),  # S-01
        "annotations": get_annotation_types(disease.id),  # A-01
        "followup": get_followup_fields(disease.id), # F-01
        "molecular": get_molecular_markers(disease.id)    # M-01
    }
# 存入 Neo4j Dataset 节点
graph.upsert_dataset_nodes(data_landscape)
```

---

### 场景 B：Critic Agent 对每条假说的实时可行性核验

```
V-01 → （可行性不足时）→ V-02 → Evolution Agent 调整假说
```

```python
def assess_idea(hypothesis):
    result = api.post("/feasibility/assess", hypothesis.to_request())   # V-01
    
    if result.feasibility_score >= 0.8:
        hypothesis.feasibility_status = "APPROVED"
        hypothesis.available_n = result.available_cohort_size
        
    elif result.feasibility_score >= 0.5:
        gap = api.post("/feasibility/gap-analysis", hypothesis.to_request())  # V-02
        hypothesis = evolution_agent.refine(hypothesis, gap.alternative_hypothesis_suggestions)
        hypothesis.feasibility_status = "REFINED"
        
    else:
        hypothesis.feasibility_status = "REJECTED_DATA_INSUFFICIENT"
    
    return hypothesis
```

---

### 场景 C：算法 Agent 确认多模态实验队列

```
M-02 → S-03 → I-01
```

在确定多模态融合实验时，需精确知道配对样本量、人口学分布（用于论文 Table 1）和图像技术参数（用于方法章节）。

---

## 四、接口实现建议

### 认证方式
建议采用 API Key + IP 白名单双重认证，所有请求通过 HTTPS 传输。研究院侧 IP 固定，方信侧配置白名单。

### 数据安全
- 所有接口仅返回**聚合统计数据**，不返回单个病例信息
- 响应中不包含任何患者姓名、ID、出生日期等 PII
- 建议对小样本（< 5 例）的分组数据返回 `"<5"` 而非精确数字（K-匿名保护）

### 更新频率
| 接口类型 | 建议更新频率 |
|----------|--------------|
| D-01, D-02（目录类） | 季度更新 |
| S-01, S-02, S-03（规模类） | 月度更新 |
| A-01, A-02, A-03（标注类） | 月度更新 |
| F-01, F-02（随访类） | 季度更新（随访本身更新慢） |
| M-01, M-02（分子类） | 月度更新 |
| V-01, V-02（可行性类） | 实时查询（依赖上述数据实时计算） |
| I-01, I-02（图像规格类） | 半年更新（扫描设备较稳定） |

### 错误码规范

| HTTP 状态码 | 含义 |
|-------------|------|
| 200 | 成功 |
| 400 | 请求参数错误（disease_id 不存在等） |
| 403 | 认证失败或 IP 不在白名单 |
| 404 | 指定病种/字段不存在 |
| 429 | 请求频率超限（建议限制 60 次/分钟） |
| 500 | 服务器内部错误 |

---

## 五、Phase 0 优先级排序

按项目路线图，Phase 0（M1–M2）需在 2–3 周内完成数据规格说明书。建议方信按以下优先级开放接口：

| 优先级 | 接口 | 原因 |
|--------|------|------|
| P0 必须 | D-01, D-02, S-01, A-01, A-02 | 构建数据地图的最小必要集合，直接影响 Idea Agent v1 启动 |
| P0 必须 | F-01, F-02 | 生存分析类研究是高分论文主方向，必须早期确认数据可行性 |
| P0 必须 | V-01 | Critic Agent 核心依赖，无此接口则可行性评估全部为人工 |
| P1 重要 | M-01, M-02 | 多模态融合研究（M5+ 启动）前需确认，可在 P0 后 2 周内完成 |
| P1 重要 | I-01, I-02 | 算法实验设计前需了解图像规格，影响 Patch 提取策略 |
| P2 补充 | S-02, S-03, A-03, V-02 | 提升 Idea 评估精度与论文方法章节质量，非阻塞性 |

---

*文档版本：v1.0 | 编写方：深圳市大数据研究院 | 供方信医疗技术有限公司对接参考*
