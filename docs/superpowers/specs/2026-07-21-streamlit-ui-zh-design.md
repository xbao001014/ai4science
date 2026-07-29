# Streamlit UI 中文化设计

**日期:** 2026-07-21  
**范围:** `gap_ui.py` + `debate_labels.py` + `tab_state.py`（方案 A）

## 目标

将 Gap 分析 Streamlit 界面全部用户可见文案改为中文。

## 核定用词

| 概念 | 中文 |
|------|------|
| Research gap | 研究空白 |
| Persist this run | 记忆本次运行 |
| Final Synthesizer | 综合终审 |
| Opportunity Scout | 机会侦察 |
| Evidence Reviewer | 证据审阅 |
| 公司名 | 方信（非「方欣」） |

## 做法

1. 直接替换展示字符串（不引入 gettext）。
2. 主 Tab：中文显示标签 + **固定英文 slug**（现有 `slugify` 会剥掉非 ASCII）。
3. 难度选项等传给后端的值保持 `easy`/`moderate`/`hard`，仅用 `format_func` 显示中文。
4. 不改：LLM 正文、内部 key、API endpoint、变量名。

## 文件

- `fulltext_workflow/debate_labels.py` — 角色名与报告替换
- `fulltext_workflow/utils/tab_state.py` — label→slug 映射
- `fulltext_workflow/gap_ui.py` — 全部 UI 文案
- `fulltext_workflow/tests/test_tab_state.py` — 同步更新
