# 三主题 Review 专题库起步包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本仓新建 MIL、HE→IHC、NPC 三个方法综述专题库起步包（README + screening_protocol + selected_papers.jsonl + 短总览），按 MIL → HE–IHC → NPC 顺序交付。

**Architecture:** 复用 `multimodal-method-summary/` 与 `virtual-staining-method-summary/` 的目录形态；MIL 精选 15 篇并外链旁系逐篇总结；HE–IHC 双轨（虚拟染色 + 非生成式预测）；NPC 以 `npc_focus_pmids.txt` 为核并按任务/证据分级筛选。

**Tech Stack:** Markdown + JSONL；证据来自 `kg_fulltext.db` 与现有 method-summary 库。

## Global Constraints

- 不跨数据集数值排名；不做批量 LLM 新逐篇总结；不自动 git commit。
- 旁系 MIL 根路径：`D:/agent/mil-method-summary/`。
- 每目录至少：README、screening_protocol、selected_papers.jsonl、overview。

---

### Task 1: MIL 起步包

**Files:**
- Create: `mil-method-summary/README.md`
- Create: `mil-method-summary/screening_protocol.md`
- Create: `mil-method-summary/selected_papers.jsonl`
- Create: `mil-method-summary/mil_methods_overview.md`

**Deliverable:** 15 篇精选 + 四阶段短总览。

---

### Task 2: HE→IHC 起步包

**Files:**
- Create: `he-ihc-prediction-method-summary/README.md`
- Create: `he-ihc-prediction-method-summary/screening_protocol.md`
- Create: `he-ihc-prediction-method-summary/selected_papers.jsonl`
- Create: `he-ihc-prediction-method-summary/expansion_candidates.jsonl`
- Create: `he-ihc-prediction-method-summary/he_ihc_prediction_overview.md`

**Deliverable:** 轨 A 虚拟染色 5 篇 + 轨 B 直接预测 6 篇 + 双轨总览。

---

### Task 3: NPC 病理 AI 起步包

**Files:**
- Create: `npc-pathology-ai-method-summary/README.md`
- Create: `npc-pathology-ai-method-summary/screening_protocol.md`
- Create: `npc-pathology-ai-method-summary/selected_papers.jsonl`
- Create: `npc-pathology-ai-method-summary/expansion_candidates.jsonl`
- Create: `npc-pathology-ai-method-summary/npc_pathology_ai_overview.md`

**Deliverable:** 13 篇核心 + 8 篇 Reserve/Exclude 标注 + 任务分轨总览。

---

### Task 4: 清理与验收

- Delete: `_tmp_query_review_libs.py`
- Verify: 三目录文件齐全；jsonl 合法 JSON 行
