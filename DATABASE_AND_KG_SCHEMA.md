# 数据库与知识图谱结构说明

> 最后更新：2026-05-28

---

## 目录

1. [总览](#1-总览)
2. [SQLite 数据库结构](#2-sqlite-数据库结构)
   - 2.1 [journals — 期刊表](#21-journals--期刊表)
   - 2.2 [papers — 论文表](#22-papers--论文表)
   - 2.3 [authors — 作者表](#23-authors--作者表)
   - 2.4 [paper_authors — 论文-作者关联表](#24-paper_authors--论文-作者关联表)
   - 2.5 [entities — 实体注册表](#25-entities--实体注册表)
   - 2.6 [relations — 三元组关系表](#26-relations--三元组关系表)
   - 2.7 [citations — 引用边表](#27-citations--引用边表)
3. [表间关系 (ER 图)](#3-表间关系-er-图)
4. [实体类型说明](#4-实体类型说明)
5. [关系类型说明](#5-关系类型说明)
6. [Study Type 分类体系](#6-study-type-分类体系)
7. [LLM 三元组抽取流程](#7-llm-三元组抽取流程)
8. [NetworkX 知识图谱结构](#8-networkx-知识图谱结构)
   - 8.1 [节点类型与属性](#81-节点类型与属性)
   - 8.2 [边类型与属性](#82-边类型与属性)
   - 8.3 [图构建过程](#83-图构建过程)
   - 8.4 [两种内部图](#84-两种内部图)
9. [节点 ID 命名规则](#9-节点-id-命名规则)
10. [知识图谱可视化与导出](#10-知识图谱可视化与导出)
11. [数据流：从原始文献到知识图谱](#11-数据流从原始文献到知识图谱)

---

## 1. 总览

本项目使用 **双层存储**：

| 层次 | 技术 | 用途 |
|---|---|---|
| 关系型存储 | SQLite（`data/kg.db`） | 持久化全部原始数据、实体、关系、引用 |
| 图存储 | NetworkX `MultiDiGraph` | 内存中的图结构，用于拓扑分析、社区检测、中心性计算 |

SQLite 是唯一的落盘形式；NetworkX 图由 `KGBuilder.build()` 按需从 SQLite 加载，并可选择导出为 GEXF / GraphML，或同步到 Neo4j。

---

## 2. SQLite 数据库结构

数据库文件路径由 `config.DB_PATH` 指定（默认 `data/kg.db`）。  
连接通过 `utils/db.py` 的 `get_conn()` 上下文管理器统一管理，启用 WAL 模式和外键约束。

---

### 2.1 `journals` — 期刊表

每行代表一个唯一期刊，以 ISSN 为主键（优先）或期刊名去重。

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 自增主键 |
| `name` | TEXT NOT NULL | 期刊全名 |
| `abbr` | TEXT | 期刊缩写 |
| `issn` | TEXT UNIQUE | ISSN 号（可为空，唯一约束） |
| `impact_factor` | REAL | 影响因子（由 `if_importer.py` 导入） |
| `if_year` | INTEGER | IF 评估年份 |
| `quartile` | TEXT | 分区（Q1/Q2/Q3/Q4） |
| `created_at` | TIMESTAMP | 记录创建时间 |

---

### 2.2 `papers` — 论文表

每行代表一篇唯一论文，以 `pmid` 为主键（优先），其次为 `doi`。

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 自增主键 |
| `pmid` | TEXT UNIQUE | PubMed ID |
| `doi` | TEXT | DOI |
| `s2id` | TEXT | Semantic Scholar 内部 ID |
| `title` | TEXT NOT NULL | 论文标题 |
| `abstract` | TEXT | 摘要文本（LLM 抽取的输入） |
| `pub_date` | TEXT | 发表日期（ISO 格式 YYYY-MM-DD） |
| `year` | INTEGER | 发表年份（索引列） |
| `journal_id` | INTEGER FK → journals | 关联期刊 |
| `journal_name` | TEXT | 原始期刊名（匹配前暂存） |
| `journal_abbr` | TEXT | 期刊缩写 |
| `issn` | TEXT | 期刊 ISSN |
| `study_type` | TEXT | LLM 分类的研究类型（见第 6 节） |
| `pub_types` | TEXT | JSON 列表，PubMed 出版类型标签 |
| `mesh_terms` | TEXT | JSON 列表，MeSH 术语 |
| `keywords` | TEXT | JSON 列表，作者关键词 |
| `citation_count` | INTEGER | 引用数（来自 Semantic Scholar） |
| `open_access` | INTEGER | 是否开放获取（0/1） |
| `source_queries` | TEXT | JSON 列表，命中的 PubMed 查询组名 |
| `extraction_done` | INTEGER | LLM 三元组抽取完成标志（0/1） |
| `created_at` | TIMESTAMP | 记录创建时间 |

**索引**：`pmid`、`doi`、`year`、`study_type`

---

### 2.3 `authors` — 作者表

以 `(name, affiliation)` 组合去重，一人多机构会产生多行。

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 自增主键 |
| `name` | TEXT NOT NULL | 作者姓名 |
| `affiliation` | TEXT | 所属机构 |
| `orcid` | TEXT | ORCID 号（如有） |
| UNIQUE | (name, affiliation) | 去重约束 |

---

### 2.4 `paper_authors` — 论文-作者关联表

M:N 关联表，同时记录作者顺序。

| 列名 | 类型 | 说明 |
|---|---|---|
| `paper_id` | INTEGER FK → papers | 论文 ID（级联删除） |
| `author_id` | INTEGER FK → authors | 作者 ID（级联删除） |
| `author_order` | INTEGER | 作者在论文中的排名（1-based） |
| PRIMARY KEY | (paper_id, author_id) | 联合主键 |

---

### 2.5 `entities` — 实体注册表

全局去重的实体字典，以 `(name, type)` 为唯一键。  
名称在写入时统一转为小写（`upsert_entity` 中 `normalized = name.strip().lower()`）。

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 自增主键 |
| `name` | TEXT NOT NULL | 实体名称（已规范化，小写） |
| `type` | TEXT NOT NULL | 实体类型（见第 4 节） |
| `cui` | TEXT | UMLS 概念唯一标识符（可选） |
| `aliases` | TEXT | JSON 列表，别名（预留字段） |
| UNIQUE | (name, type) | 去重约束 |

**索引**：`type`、`name`

---

### 2.6 `relations` — 三元组关系表

核心三元组存储，每行表示一条 `(subject) --[relation]--> (object)` 语义关系，并记录来源论文。

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 自增主键 |
| `subject_type` | TEXT NOT NULL | 主语节点类型（`'Paper'` 或实体类型） |
| `subject_id` | INTEGER NOT NULL | 主语节点 ID（指向 papers 或 entities） |
| `relation` | TEXT NOT NULL | 关系类型（见第 5 节） |
| `object_type` | TEXT NOT NULL | 宾语节点类型（均为实体类型） |
| `object_id` | INTEGER NOT NULL | 宾语节点 ID（指向 entities） |
| `metric_value` | TEXT | 可选的指标数值（如 `"AUC=0.95"`） |
| `source_pmid` | TEXT | 来源论文 PMID |
| `confidence` | REAL | 置信度（默认 1.0） |
| `created_at` | TIMESTAMP | 记录创建时间 |

**索引**：`(subject_type, subject_id)`、`(object_type, object_id)`、`relation`

> **注意**：`subject_id` 是多态外键。当 `subject_type='Paper'` 时指向 `papers.id`；其他情况指向 `entities.id`。

---

### 2.7 `citations` — 引用边表

论文间的引用关系，数据来自 Semantic Scholar `/paper/batch` 接口的 references 字段。

| 列名 | 类型 | 说明 |
|---|---|---|
| `citing_pmid` | TEXT NOT NULL | 施引论文 PMID |
| `cited_pmid` | TEXT NOT NULL | 被引论文 PMID |
| PRIMARY KEY | (citing_pmid, cited_pmid) | 防止重复写入 |

---

## 3. 表间关系 (ER 图)

```
journals ──────────────────────────────────────────────────────────────┐
  id (PK)                                                              │
  name, abbr, issn, impact_factor, quartile                           │
                                                                       │ journal_id (FK)
papers ──────────────────────────────────────────────────────────────◄─┘
  id (PK)   pmid (UNIQUE)   doi   s2id
  title     abstract        year  study_type
  citation_count   open_access   extraction_done
  journal_id (FK→journals)   source_queries (JSON)
     │                │
     │ paper_id(FK)   │ pmid
     ▼                ▼
paper_authors       citations
  paper_id (FK)       citing_pmid
  author_id (FK)      cited_pmid
  author_order        (self-referential paper↔paper)
     │
     ▼
authors
  id (PK)
  name, affiliation, orcid

papers ─────────────────────────────────────────────────────────────────┐
  id / pmid                                             source_pmid (FK)│
                                                                        │
relations ──────────────────────────────────────────────────────────────┘
  id (PK)
  subject_type  subject_id ──► papers.id  (when subject_type='Paper')
                        └───► entities.id (when subject_type=entity type)
  relation
  object_type   object_id  ──► entities.id
  metric_value, confidence, source_pmid

entities
  id (PK)
  name (lower-cased), type
  cui, aliases
```

---

## 4. 实体类型说明

LLM 在抽取三元组时严格限定以下 6 种实体类型：

| 类型 | 含义 | 示例 |
|---|---|---|
| `Disease` | 疾病 / 病理状态 | `breast carcinoma`、`colorectal cancer`、`lung adenocarcinoma` |
| `Method` | AI / 计算方法 | `ResNet-50`、`U-Net`、`contrastive learning`、`vision transformer` |
| `Task` | 计算任务 | `tumor segmentation`、`survival prediction`、`grading`、`detection` |
| `Tissue` | 解剖组织 / 器官 | `lung`、`prostate`、`colon`、`lymph node` |
| `Dataset` | 数据集 | `TCGA-LUAD`、`Camelyon16`、`PAIP`、`CPTAC` |
| `Metric` | 性能指标 | `AUC`、`F1-score`、`accuracy`、`Dice coefficient` |

可视化颜色映射（`kg_builder.py` 中 `NODE_COLORS`）：

| 节点类型 | 颜色（HEX） |
|---|---|
| Paper | `#4A90D9`（蓝） |
| Journal | `#7B68EE`（紫蓝） |
| Author | `#95C17B`（绿） |
| Disease | `#E05C5C`（红） |
| Method | `#F0A500`（橙） |
| Task | `#00BCD4`（青） |
| Tissue | `#FF80AB`（粉） |
| Dataset | `#80CBC4`（青绿） |
| Metric | `#FFCC80`（浅橙） |

---

## 5. 关系类型说明

### 论文 → 实体关系（由 LLM 抽取）

| 关系名 | 主语类型 | 宾语类型 | 语义 |
|---|---|---|---|
| `APPLIES_METHOD` | Paper | Method | 该论文使用了此 AI 方法 |
| `TARGETS_DISEASE` | Paper | Disease | 该论文研究此疾病 |
| `OPERATES_ON` | Paper | Tissue | 该论文处理此组织类型 |
| `PERFORMS_TASK` | Paper | Task | 该论文解决此计算任务 |
| `USES_DATASET` | Paper | Dataset | 该论文在此数据集上评估 |
| `ACHIEVES_METRIC` | Paper | Metric | 该论文报告此指标（`metric_value` 存数值） |
| `RELATED_TO` | Method | Method | 两种方法密切相关或被对比 |

### 图构建时添加的结构边

| 关系名 | 主语类型 | 宾语类型 | 来源 |
|---|---|---|---|
| `PUBLISHED_IN` | Paper | Journal | `papers.journal_id` FK |
| `AUTHORED_BY` | Paper | Author | `paper_authors` 连接表 |
| `CITES` | Paper | Paper | `citations` 表 |

---

## 6. Study Type 分类体系

每篇论文的 `study_type` 由 LLM 在步骤 3 自动分类（`triple_extractor.py` 第一步调用）：

| study_type | 含义 | 典型特征 |
|---|---|---|
| `ai_algorithm` | AI / 深度学习算法研究 | 提出新模型架构、训练策略 |
| `clinical_study` | 临床验证 / 应用研究 | 真实患者数据、临床终点评估 |
| `review` | 综述（叙述性） | 系统回顾、非定量汇总 |
| `meta_analysis` | 定量 Meta 分析 | 合并统计量、森林图 |
| `dataset_benchmark` | 数据集构建 / 基准测试 | 标注流程、多模型对比评估 |
| `foundation_model` | 大规模预训练模型 | 自监督 / 对比学习、病理通用模型 |
| `multimodal` | 多模态研究 | 图像 + 基因组 / 文本 / 临床数据融合 |
| `other` | 不属于以上类别 | — |

在可视化中，Paper 节点颜色按 `study_type` 着色（`STUDY_TYPE_COLORS`）：

| study_type | 颜色（HEX） |
|---|---|
| ai_algorithm | `#1565C0`（深蓝） |
| clinical_study | `#2E7D32`（深绿） |
| review | `#6A1B9A`（深紫） |
| meta_analysis | `#AD1457`（玫红） |
| dataset_benchmark | `#E65100`（深橙） |
| foundation_model | `#00695C`（深青绿） |
| multimodal | `#F57F17`（琥珀） |
| other | `#546E7A`（灰蓝） |

---

## 7. LLM 三元组抽取流程

`extractor/triple_extractor.py` 对每篇论文执行两步 LLM 调用：

```
论文摘要（abstract）
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 1 — Study Type 分类（轻量调用）                             │
│                                                                  │
│  输入：title + pub_types + abstract                              │
│  输出：{"study_type": "ai_algorithm"}  (8 选 1)                  │
│  → UPDATE papers SET study_type=?, extraction_done 仍为 0        │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 2 — 三元组抽取（结构化输出）                                │
│                                                                  │
│  输入：title + abstract                                          │
│  输出（Pydantic ExtractionResult）：                             │
│  {                                                               │
│    "triples": [                                                  │
│      {                                                           │
│        "subject": {"name": "U-Net", "type": "Method"},          │
│        "relation": "PERFORMS_TASK",                              │
│        "object":  {"name": "tumor segmentation", "type": "Task"},│
│        "metric_value": null,                                     │
│        "confidence": 1.0                                        │
│      },                                                          │
│      ...  (目标 5~20 条)                                         │
│    ]                                                             │
│  }                                                               │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
              对每条 triple：
              upsert_entity(subject)  →  entities 表
              upsert_entity(object)   →  entities 表
              insert_relation(...)    →  relations 表
              mark_extraction_done()  →  papers.extraction_done = 1
```

抽取支持断点续跑：`extraction_done=1` 的论文自动跳过。

---

## 8. NetworkX 知识图谱结构

由 `graph/kg_builder.py` 的 `KGBuilder.build()` 从 SQLite 构建，返回 `nx.MultiDiGraph`（有向多重图，允许两节点间有多条边）。

---

### 8.1 节点类型与属性

#### Paper 节点

| 属性 | 值类型 | 说明 |
|---|---|---|
| `node_type` | `"Paper"` | 节点类型标识 |
| `label` | str | 标题前 80 字符 |
| `color` | str | 按 study_type 着色（HEX） |
| `pmid` | str | PubMed ID |
| `doi` | str | DOI |
| `year` | int | 发表年份 |
| `pub_date` | str | 发表日期 |
| `journal` | str | 期刊名 |
| `study_type` | str | 研究类型 |
| `citation_count` | int | 引用数 |
| `open_access` | bool | 是否开放获取 |
| `mesh_terms` | list[str] | MeSH 术语 |

#### Journal 节点

| 属性 | 值类型 | 说明 |
|---|---|---|
| `node_type` | `"Journal"` | |
| `label` | str | 期刊名 |
| `abbr` | str | 期刊缩写 |
| `issn` | str | ISSN |
| `impact_factor` | float / None | 影响因子 |
| `quartile` | str | Q1-Q4 |
| `if_year` | int | IF 年份 |

#### Author 节点（可选，`include_authors=True`）

| 属性 | 值类型 | 说明 |
|---|---|---|
| `node_type` | `"Author"` | |
| `label` | str | 作者姓名 |
| `affiliation` | str | 机构 |
| `orcid` | str | ORCID |

#### 实体节点（Disease / Method / Task / Tissue / Dataset / Metric）

| 属性 | 值类型 | 说明 |
|---|---|---|
| `node_type` | str | 实体类型名 |
| `label` | str | 规范化实体名（小写） |
| `color` | str | 按类型着色（HEX） |
| `cui` | str | UMLS CUI（如有） |

---

### 8.2 边类型与属性

| 关系 | 方向 | 主要属性 | 颜色 |
|---|---|---|---|
| `APPLIES_METHOD` | Paper → Method | `source_pmid`, `confidence` | `#888888` |
| `TARGETS_DISEASE` | Paper → Disease | `source_pmid`, `confidence` | `#888888` |
| `OPERATES_ON` | Paper → Tissue | `source_pmid`, `confidence` | `#888888` |
| `PERFORMS_TASK` | Paper → Task | `source_pmid`, `confidence` | `#888888` |
| `USES_DATASET` | Paper → Dataset | `source_pmid`, `confidence` | `#888888` |
| `ACHIEVES_METRIC` | Paper → Metric | `source_pmid`, `metric_value`, `confidence` | `#888888` |
| `RELATED_TO` | Method → Method | `source_pmid`, `confidence` | `#888888` |
| `PUBLISHED_IN` | Paper → Journal | — | `#BDBDBD` |
| `AUTHORED_BY` | Paper → Author | `author_order` | `#C8E6C9` |
| `CITES` | Paper → Paper | — | `#E0E0E0` |

---

### 8.3 图构建过程

```
SQLite
  journals  ──► Journal 节点
  papers    ──► Paper 节点  +  PUBLISHED_IN 边 (Paper→Journal)
  entities  ──► 实体节点 (Disease/Method/Task/Tissue/Dataset/Metric)
  relations ──► 语义关系边 (Paper→Entity 或 Method→Method)
  [authors] ──► Author 节点  +  AUTHORED_BY 边 (optional)
  [citations]──► CITES 边 (Paper→Paper)           (optional)
                                    │
                                    ▼
                        nx.MultiDiGraph
                    (N 节点, E 有向多重边)
```

构建时支持四种过滤参数，可对图进行裁剪：

| 参数 | 含义 |
|---|---|
| `min_citation_count` | 忽略低引用论文（减少噪声） |
| `year_range` | 限制时间窗口 |
| `study_types` | 只保留特定研究类型 |
| `include_authors` | 是否包含作者节点（默认 False，减小图规模） |
| `include_citations` | 是否包含引用边（默认 True） |

---

### 8.4 两种内部图

`graph_tools.py` 在 `GRAPH_TOOLS` 的 5 个工具中维护两个懒加载缓存图：

#### `_FULL_GRAPH`（完整知识图谱）

- 类型：`nx.MultiDiGraph`
- 内容：所有节点 + 所有边（含引用 CITES）
- 用途：`graph_citation_pagerank`（引用网络 PageRank）
- 构建：调用 `KGBuilder().build(include_authors=False, include_citations=True)`

#### `_ENTITY_COOC_GRAPH`（实体共现无向图）

- 类型：`nx.Graph`（无向加权图）
- 内容：仅包含 6 种实体节点（Disease / Method / Task / Tissue / Dataset / Metric）
- 边：若两实体出现在同一篇论文中，则连边；**边权 = 共现论文数**
- 用途：`graph_entity_pagerank`、`graph_structural_holes`、`graph_community_gaps`、`graph_disease_method_reach`

```
实体共现图示意（边权=共现论文数）：

  U-Net ─────(47)───── tumor segmentation
    │                         │
   (12)                      (8)
    │                         │
  ResNet-50 ──(31)──── breast carcinoma
    │
   (5)
    │
  TCGA-LUAD
```

---

## 9. 节点 ID 命名规则

NetworkX 图中每个节点的字符串 ID 按如下规则生成：

| 节点类型 | ID 格式 | 示例 |
|---|---|---|
| Paper | `Paper_{db_id}` | `Paper_1042` |
| Journal | `Journal_{db_id}` | `Journal_7` |
| Author | `Author_{db_id}` | `Author_305` |
| 实体节点 | `{type}_{db_id}` | `Method_88`、`Disease_23` |

`db_id` 对应各表的自增主键 `id`。

---

## 10. 知识图谱可视化与导出

`viz/visualize.py` 提供多种导出格式：

| 输出文件 | 格式 | 说明 |
|---|---|---|
| `output/kg_interactive.html` | Pyvis HTML | 全图（裁剪至前 500 节点），浏览器可交互 |
| `output/kg_entities.html` | Pyvis HTML | 纯实体视图（过滤 Paper/Journal/Author），前 800 节点 |
| `output/kg.gexf` | GEXF | Gephi 可直接打开，完整属性 |
| `output/kg.graphml` | GraphML | 通用图格式，兼容 yEd / Cytoscape |
| `output/kg_stats.csv` | CSV | 各类型节点数、边数等统计 |
| `output/top_entities.csv` | CSV | 各类型 Top 实体（按中心性排名） |
| `output/papers_by_journal.csv` | CSV | 各期刊论文数 / 引用数汇总 |

可选：通过 `KGBuilder.sync_to_neo4j()` 将图同步到 Neo4j（需设置 `USE_NEO4J=true`）。

---

## 11. 数据流：从原始文献到知识图谱

```
PubMed API                   Semantic Scholar API
    │                                │
    │ PMID, title, abstract          │ citation_count, s2id
    │ pub_date, journal, authors     │ open_access, references
    │ MeSH terms, pub_types          │
    ▼                                ▼
┌──────────────────────────────────────────────────────────┐
│                  papers 表（原始论文）                     │
│  extraction_done=0, study_type=NULL, citation_count=N    │
└─────────────────────────┬────────────────────────────────┘
                          │
               LLM 两步抽取（triple_extractor.py）
                          │
          ┌───────────────┴──────────────┐
          │                              │
          ▼                              ▼
  papers.study_type             entities 表 + relations 表
  (8 类标签)                   (实体注册 + 三元组)
          │                              │
          └──────────────┬───────────────┘
                         │
          citations 表 ──┤
          (S2 引用边)     │
                         ▼
              KGBuilder.build()
                         │
                         ▼
           nx.MultiDiGraph（内存）
           ├── Paper 节点 (study_type 着色)
           ├── Entity 节点 (6 类型)
           ├── Journal 节点
           ├── [Author 节点] (可选)
           ├── 语义关系边 (7 种 LLM 抽取)
           ├── PUBLISHED_IN 边
           ├── [AUTHORED_BY 边] (可选)
           └── [CITES 边] (可选)
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
       HTML 交互图   GEXF/GraphML   gap_agent
       (Pyvis)       (导出)        gap 分析 / 空白挖掘
```
