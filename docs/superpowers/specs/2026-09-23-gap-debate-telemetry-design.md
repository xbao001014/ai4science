# Gap 辩论运行成本观测设计

日期：2026-09-23。范围：`stream_gap_debate_agent` 的三角色辩论及其 Streamlit 展示；不改变研究判断或现有工具预算。

实现记录：已接入逐次 LLM／工具指标、独立 SQLite 表、显式有界 LLM 重试、简洁 UI 汇总与折叠诊断。缓存命中首批只在病种目录缓存可确认时记录；其他工具保持 `unknown`，待各缓存层逐个接入。

## 目标与现状

逐次记录 LLM 实际输入／输出 tokens、LLM 与工具耗时、工具结果体积、可确认的缓存命中及重试原因。用户默认只看会话汇总和异常提示，需要时才展开明细。

目前 `run_tool_agent` 只发出 `llm_request_start`，不记录响应 `usage`；`tool_call` 与 `tool_result` 用于持久化，但没有单次执行耗时。`persist_tool_event` 会截断结果 JSON，不能靠已存文本还原原始体积。模型客户端没有显式设置 SDK 重试次数，现有日志不能分辨内部重试。辩论工具也没有统一的缓存命中返回字段。

## 采集契约

新增与会话关联的轻量 `debate_cost_events` 表；不向现有 `debate_tool_events` 的大结果 JSON 塞指标。每行有 `session_id, round_no, role, event_kind, operation_id, started_at_utc, duration_ms, status`，以及按类别可空的字段：

| 类别 | 记录字段 |
| --- | --- |
| LLM 请求 | `request_seq, model, provider_request_id, prompt_tokens, completion_tokens, total_tokens, usage_source, finish_reason, error_code` |
| 工具调用 | `tool_name, call_id, raw_result_chars, sent_result_chars, result_truncated, cache_hit, cache_source, error_code` |
| 重试 | `parent_operation_id, attempt_no, retry_source, retry_reason_code, retry_after_ms, outcome` |

`operation_id` 在发出请求或执行工具前生成；LLM 的同一逻辑请求使用一个 ID，各次尝试另有 attempt 序号。开始时先插入 `running` 行，完成或失败时更新同一行；进程中断留下的行在续跑时标为 `interrupted`，不记作零耗时或成功。`call_id` 关联已有工具事件。`duration_ms` 用单调时钟测量，UTC 只负责排序。持久化由 `stream_gap_debate_agent` 统一处理，以便会话续跑与普通运行走同一条路径。

**tokens** 只取模型响应 `usage.prompt_tokens` / `completion_tokens`；若提供商未返回，存 `NULL`，界面标“用量未返回”，不拿字符数冒充。可选的推理 tokens 保存在扩展字段中，不混入 completion 以外的自定义估值。失败但收到 usage 的请求也照实记录；汇总按成功与失败分别计数。

**结果字符数** 同时测量工具原始结果序列化长度与实际发给 LLM 的 `compact_json` 长度。截断标志取压缩后的 `evidence_truncated` / `verification_incomplete`；持久化已有结果再次截断与否另记，不用数据库存储长度代替发送长度。不记录提示词、完整工具参数、API key 或患者数据到成本表。

**缓存命中** 为 `true / false / unknown` 三态。只有缓存层明确返回命中信息时才计入命中率；尚未接入观测的缓存记 `unknown`。先在可行性客户端及可迁移机会快照的缓存边界输出元数据，再由工具包装层传递。不能由请求耗时或重复参数推断命中，也不把 LLM 服务端可能存在的缓存算入本地缓存。

**重试原因** 使用有限枚举：`rate_limit, timeout, connection, server_error, invalid_response, manual_resume, other`，同时存状态码和安全的异常类名。要精确观测网络重试，需为此 agent 的 OpenAI 客户端关闭不可见的 SDK 自动重试，改由有上限的显式重试包装器执行；只重试瞬时失败，记录每次尝试与等待。部署前若仍保留 SDK 内部重试，则 `retry_source=sdk_unknown`，不能展示“0 次重试”的确定结论。会话续跑单列为 `manual_resume`，不混入请求重试数。

## 事件接入

1. `analysis/agent_utils.py`：在每次 `chat.completions.create` 前后采样时钟，读取 `response.usage`，发出 `llm_request_finished` 或 `llm_request_failed`；尾部无工具的 finalization 调用同样覆盖。工具执行前后采样，序列化结果与压缩结果后发出 `tool_execution_finished`。异常与预算阻断分别标记，预算阻断不是执行耗时。
2. `analysis/debate_memory.py`、`db/schema.py`：新增小型指标表和插入／更新／聚合查询；保留现有事件与历史会话兼容。新表索引 `(session_id, round_no, role, started_at_utc)`；不迁移旧结果来伪造 tokens 或缓存命中。
3. 临床 API／快照缓存边界：返回内部观测元数据，不改变 LLM 所见的科研数据语义。未接入的普通 SQL 工具显示缓存状态未知。
4. `gap_ui.py`：运行中消费完成事件，结束或载入历史会话时读取同一聚合查询。指标采集失败不阻断辩论，但在诊断区标“观测不完整”。

## 简洁展示

默认只显示一行：`第 1/2 轮 · LLM 8 次 · tokens 42k 入 / 9k 出 · 工具 12 次 / 38 秒 · 缓存 3/5 · 重试 1`。只要有 usage 缺失，就显示 `tokens 部分缺失`；缓存分母只包括可确认命中状态的调用。运行中数字只统计已完成操作。

折叠的“运行诊断”展示按角色汇总及**最慢 5 次工具／LLM 请求**，并列出失败或重试原因；正常调用不逐条刷屏。现有步骤日志保留名称与记录数，默认收起工具参数和长异常；完整科研证据仍在证据页，成本指标不进入研究报告正文。

## 验收

- 用固定响应测试：提供商有 usage、无 usage、工具异常、结果压缩、缓存 hit/miss/unknown、限流后成功与重试耗尽，指标和展示均准确。
- 会话中断续跑后汇总不重复计数；旧会话显示“历史运行未采集”而非零。
- 每项耗时来自单调时钟；`raw_result_chars >= sent_result_chars` 只在发生压缩时成立，不作为所有结果的硬约束。
- 成本表没有 prompt、引文全文、密钥或患者级数据。采集异常不改变原辩论结果。
- 对一轮真实辩论人工核对请求数、工具数和重试；只有提供商返回 usage 时才核对 token 总和。
