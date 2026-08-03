# Final whole-branch review fixes

## 2026-08-03

### Changes

- Exported `normalize_feasibility_field_lists` from `analysis/feasibility_tools.py`
  and reused it for feasibility requests and baseline canonicalization.
- Canonical feasibility specs now normalize aliases, case, ordering, duplicates,
  and omit `hypothesis_id`.
- `feasibility_assess` cache reads/writes now use canonical specs; equivalent
  alias/case/order/hypothesis-ID calls share one cache entry.
- Reset `session_guards.relaxed_seen` at each Critic-round boundary, preserving
  rejection in the observing round without poisoning later rounds.
- Added alias-equivalence, true tighter-annotation, immutable-baseline,
  canonical-cache, bare `tool_error`, and per-round accept-gate regressions.

### Test output

```text
> .venv\Scripts\python.exe -m pytest tests/test_idea_session_guards.py tests/test_idea_agent_baseline_accept.py tests/test_idea_agent_tool_slim.py -v
collected 29 items
============================= 29 passed in 3.98s ==============================

> .venv\Scripts\python.exe -m pytest tests/test_feasibility.py -v
collected 18 items
============================= 18 passed in 3.66s ==============================
```
