# 三主题 Review 专题库起步包

**日期:** 2026-08-25  
**范围:** 按优先级建设三套可周更的方法综述专题库起步包（筛选协议 + 入选清单 + 短总览），服务：① MIL 小综述；② HE→Ki67/类似 IHC；③ 鼻咽癌病理 AI。

## 问题

需要三份可汇报、可扩库的 review 材料，但现有资产成熟度不均：

| 主题 | 已有资产 | 缺口 |
|------|----------|------|
| MIL | 旁系 `D:\agent\mil-method-summary\`：约 62 篇总结 + 长总览 | 本仓无精选短总览与筛选边界 |
| HE→Ki67/IHC | `virtual-staining-method-summary/` 含 Ki-67 / 虚拟 IHC 多篇 | 未单独立题；缺「非生成式 biomarker 预测」轨 |
| 鼻咽癌病理 AI | 查询组、`npc_focus_pmids.txt`（22 PMID）、病种同义词/Gap focus | 无专题库与总览 |

既往「三专题」PPT（多模态/分割/虚拟染色）与本需求无关，勿混用。

## 决策

采用**专题库起步包**（非仅大纲、非旁系独占）：在本仓新建三个目录，复用多模态/虚拟染色的产物形态；本轮**不**批量重写逐篇全文总结，**不**改 pipeline 代码（除非后续发现查询明显缺漏）。

### 目录与必交付物

每个主题目录至少包含：

| 文件 | 作用 |
|------|------|
| `README.md` | 范围、证据边界、与现有库/旁系的关系 |
| `screening_protocol.md` | 纳入/排除/优先级 |
| `selected_papers.jsonl` | 入选记录（可含 `summary_file` 外链） |
| `*_methods_overview.md` 或等价短总览 | 可汇报用短综述 |

可选：`expansion_candidates.jsonl` / `.md`（第二轨或待补全文时）。

`selected_papers.jsonl` 每行建议字段（缺省可空，但不得发明数值排名）：

`priority`, `pmid`（可空）, `title`, `year`, `track` / `stage`, `role`, `selection_rationale`, `summary_file`（本仓或旁系相对文件名）, `evidence_source`, `next_action`。

| 本仓目录 | 证据源策略 |
|----------|------------|
| `mil-method-summary/` | 精选 12–15 篇；`summary_file` 指向旁系绝对或相对路径说明；短总览压缩旁系长稿四阶段框架 |
| `he-ihc-prediction-method-summary/` | 优先链接 `virtual-staining-method-summary/method_summaries/`；另列非生成式候选（摘要级可入清单，全文总结可暂缓） |
| `npc-pathology-ai-method-summary/` | 以 `fulltext_workflow/data/npc_focus_pmids.txt` 为核；用 `kg_fulltext.db` 补元数据；首批可为清单+任务分轨短总览，逐篇总结后置 |

### 主题边界

**1. MIL（优先级最高，本轮先交付）**

- 范围：计算病理 WSI 弱监督 / 多实例学习聚合与相关鲁棒训练。
- 叙事：注意力与聚类 → 图/上下文 → 长序列（Transformer/SSM）→ 鲁棒性与基础模型融合。
- 精选原则：每阶段 2–4 个代表方法（如 AB-MIL、CLAM、DSMIL、TransMIL、Patch-GCN、DTFD、MambaMIL、IBMIL/CIMIL、Prov-GigaPath 等），覆盖基线与演进，而非穷尽 62 篇。
- 禁止：跨数据集数值排名；把材料科学误收入库的 REMIX 等非病理条目纳入比较。

**2. HE→Ki67 / 类似 IHC**

- **轨 A（虚拟染色）**：H&E→IHC/功能染色图像，再计 labeling index 等（代表：PMID 39087085、33784619；SOX10/CD163 等作类似 IHC）。
- **轨 B（非生成式预测）**：H&E 直接回归/分类 Ki-67 分数、阳性状态或类似标志物，不要求生成染色图；来源优先 `ihc_biomarker_prediction_ai` 查询与本地库检索。
- 排除：纯 stain normalization、无病理意义的颜色迁移、综述-only（可作引用背景，不入逐篇清单核心）。

**3. 鼻咽癌病理 AI**

- 纳入：病理/组织学/数字病理/WSI + AI/DL，诊断、分割、分级、预后、分子或 IHC 相关预测等。
- 降级/排除：纯放射组学或无病理图像的影像学 AI（可记 Reserve，不进首批核心）；非 NPC 主病种。
- 首批核：`npc_focus_pmids.txt`；可用 Gap focus=`nasopharyngeal carcinoma` / `NPC` 扩候选但不强制本轮写完所有逐篇总结。

### 交付顺序

1. MIL 起步包（短总览 + 精选 jsonl + protocol + README）  
2. HE–IHC 起步包（双轨 protocol + 入选/候选 + 短总览）  
3. NPC 起步包（protocol + focus 核清单 + 任务分轨短总览）

### 明确不做（本轮）

- 不复制旁系 62 篇 markdown 到本仓  
- 不批量 LLM 新写逐篇方法总结（缺证据条目仅清单标注 `next_action`）  
- 不改动 `search_queries.py` / pipeline，除非验收时发现 NPC 或 IHC 检索明显漏检且用户确认补查询  
- 不自动 git commit（需用户另行要求）

## 验收

- 三个目录均可独立打开，README 写清证据边界与外链关系  
- 各有 `screening_protocol.md` 与非空 `selected_papers.jsonl`  
- 各有一份短总览，长度适合汇报引用（MIL 压缩版；另两题为第一阶段地图，非宣称完备系统综述）  
- HE–IHC 总览显式区分轨 A / 轨 B  
- NPC 总览至少覆盖 focus 核 PMID 的任务分轨（诊断/分割/预后等，以库内可得信息为准）  
- 交叉链接：HE–IHC → 虚拟染色总结；MIL → 旁系路径说明  

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 旁系路径在他人机器不可用 | README 写明旁系根路径；jsonl 用稳定方法名 + 旁系相对文件名 |
| 轨 B / NPC 全文不足 | 清单标 `full_text_status` / `next_action`；总览用证据分级措辞 |
| 与虚拟染色库范围重叠 | HE–IHC README 声明为「应用切面」，不替代虚拟染色全库 |
