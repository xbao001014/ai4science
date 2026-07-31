# Inline Provenance UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace「证据与文献」selectbox pickers with compact per-row「溯源」buttons and full titles/quotes.

**Architecture:** Pure helpers partition rows (visible ≤30 / overflow), build stable button keys, and open selections; `render_evidence_literature_section` renders Streamlit column rows instead of `safe_table` + selectbox. Viewer embed path stays unchanged.

**Tech Stack:** Python 3, Streamlit, pytest.

**Spec:** `docs/superpowers/specs/2026-07-31-evidence-inline-provenance-ux-design.md`

## Global Constraints

- Per-row「溯源」in a compact list; remove evidence/paper selectboxes.
- Full titles / entity labels and readable quotes (no 40-char picker truncation).
- Cap: first 30 rows visible; remainder under expander「更多证据」/「更多论文」.
- Viewer payload / soft errors / embed behavior unchanged (`make_evidence_viewer_selection`, `load_paper_for_viewer`, `components.html`).
- Button keys stable (PMID + hash of quote/title), not positional indices.
- Run pytest from `fulltext_workflow/`.
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/gap_ui.py` | Helpers + rewrite `render_evidence_literature_section`; stop clipping evidence titles to 80 for display |
| `fulltext_workflow/tests/test_evidence_viewer_ui.py` | Replace selectbox test with row-key / partition / no-PMID tests; keep warning + quote tests |

---

### Task 1: Pure helpers + title display fix

**Files:**
- Modify: `fulltext_workflow/gap_ui.py`
- Modify: `fulltext_workflow/tests/test_evidence_viewer_ui.py`

**Interfaces:**
- Produces: `PROVENANCE_LIST_LIMIT: int = 30`
- Produces: `provenance_row_key(kind: str, pmid: str, *parts: str) -> str`
- Produces: `partition_provenance_rows(rows: list[dict], *, limit: int = PROVENANCE_LIST_LIMIT) -> tuple[list[dict], list[dict]]` — rows **with** non-empty PMID only for the openable lists; callers pass already-filtered lists
- Produces: evidence title in `extract_evidence` uses full `str(title)` (no `[:80]`); quote stays `[:240]`

- [ ] **Step 1: Write failing tests**

Replace `test_evidence_viewer_selectboxes_use_stable_string_ids` and add helpers tests in `tests/test_evidence_viewer_ui.py`:

```python
def test_provenance_row_key_stable_and_distinct():
    from gap_ui import provenance_row_key

    a = provenance_row_key("evidence", "123", "title", "quote one")
    b = provenance_row_key("evidence", "123", "title", "quote two")
    c = provenance_row_key("paper", "123", "Same Title")
    assert a != b
    assert a.startswith("evidence_123_")
    assert c.startswith("paper_123_")
    assert provenance_row_key("evidence", "123", "title", "quote one") == a


def test_partition_provenance_rows_caps_at_30():
    from gap_ui import PROVENANCE_LIST_LIMIT, partition_provenance_rows

    rows = [{"PMID": str(i)} for i in range(35)]
    head, tail = partition_provenance_rows(rows)
    assert len(head) == PROVENANCE_LIST_LIMIT == 30
    assert len(tail) == 5
    assert head[0]["PMID"] == "0"
    assert tail[0]["PMID"] == "30"


def test_extract_evidence_keeps_full_title():
    from gap_ui import extract_evidence

    long_title = "T" * 120
    events = [{
        "type": "tool_result",
        "name": "author_stated_gaps",
        "result": {
            "data": [{
                "source_pmid": "1",
                "title": long_title,
                "evidence_section": "discussion",
                "evidence_quote": "q",
            }]
        },
    }]
    rows = extract_evidence(events)
    assert rows[0]["标题/实体"] == long_title
```

Keep existing `test_evidence_viewer_selection_payload`, `test_extract_evidence_keeps_longer_quote`, `test_viewer_load_warning_includes_error_code`.

- [ ] **Step 2: Run tests — expect FAIL**

```
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer_ui.py -v
```

Expected: FAIL on missing symbols / title still clipped / old selectbox test if not yet replaced.

- [ ] **Step 3: Implement helpers + title fix**

In `gap_ui.py` near `make_evidence_viewer_selection`:

```python
import hashlib

PROVENANCE_LIST_LIMIT = 30


def provenance_row_key(kind: str, pmid: str, *parts: str) -> str:
    pid = str(pmid or "").strip()
    digest = hashlib.sha1(
        "\x1f".join(str(p) for p in parts).encode("utf-8", errors="replace")
    ).hexdigest()[:10]
    return f"{kind}_{pid}_{digest}"


def partition_provenance_rows(
    rows: list[dict],
    *,
    limit: int = PROVENANCE_LIST_LIMIT,
) -> tuple[list[dict], list[dict]]:
    return rows[:limit], rows[limit:]
```

In `extract_evidence`, change `"标题/实体": str(title)[:80]` → `"标题/实体": str(title)`.

- [ ] **Step 4: Run tests — expect PASS for Task 1 tests**

```
..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer_ui.py -v
```

(Warning test may still pass; selectbox test must already be removed/replaced.)

- [ ] **Step 5: Commit** (if commits enabled)

```bash
git add fulltext_workflow/gap_ui.py fulltext_workflow/tests/test_evidence_viewer_ui.py
git commit -m "feat: add provenance row helpers and full evidence titles"
```

---

### Task 2: Compact row UI + update render tests

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (`render_evidence_literature_section`)
- Modify: `fulltext_workflow/tests/test_evidence_viewer_ui.py`

**Interfaces:**
- Consumes: Task 1 helpers, `make_evidence_viewer_selection`
- Produces: rewritten section UI; no selectboxes

- [ ] **Step 1: Write failing UI render test**

```python
def test_render_evidence_literature_uses_row_buttons_not_selectbox(monkeypatch):
    import gap_ui

    buttons = []
    selectbox_calls = []

    class FakeStreamlit:
        session_state = {}

        @staticmethod
        def subheader(*_a, **_k):
            pass

        @staticmethod
        def info(*_a, **_k):
            pass

        @staticmethod
        def caption(*_a, **_k):
            pass

        @staticmethod
        def divider():
            pass

        @staticmethod
        def markdown(*_a, **_k):
            pass

        @staticmethod
        def columns(spec):
            class _Col:
                def __enter__(self):
                    return self

                def __exit__(self, *_exc):
                    return False

            n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
            return [_Col() for _ in range(n)]

        @staticmethod
        def button(label, **kwargs):
            buttons.append({"label": label, "key": kwargs.get("key")})
            return False

        @staticmethod
        def selectbox(*_a, **_k):
            selectbox_calls.append(True)
            raise AssertionError("selectbox must not be used for provenance pickers")

        @staticmethod
        def expander(label, **_k):
            class _Exp:
                def __enter__(self):
                    return self

                def __exit__(self, *_exc):
                    return False

            return _Exp()

    evidence = [
        {
            "PMID": "123",
            "标题/实体": "Full evidence title without clipping",
            "证据章节": "discussion",
            "摘录": "long quote text",
            "工具": "作者自述空白",
        },
        {
            "PMID": "",
            "标题/实体": "No pmid row",
            "证据章节": "",
            "摘录": "x",
            "工具": "t",
        },
    ]
    papers = [
        {
            "PMID": "456",
            "标题": "A complete paper title that must remain intact",
            "年份": 2025,
            "期刊": "J",
            "研究类型": "ai_algorithm",
            "来源": "语料焦点匹配",
        }
    ]
    monkeypatch.setattr(gap_ui, "st", FakeStreamlit)
    monkeypatch.setattr(gap_ui, "extract_evidence", lambda _e: evidence)
    monkeypatch.setattr(
        gap_ui,
        "resolve_evidence_literature_papers",
        lambda _e, _f, limit: (papers, "corpus_focus"),
    )

    gap_ui.render_evidence_literature_section([], "breast")

    assert not selectbox_calls
    assert any(b["label"] == "溯源" for b in buttons)
    assert any(
        b["key"] and str(b["key"]).startswith("open_evidence_") for b in buttons
    )
    assert any(
        b["key"] and str(b["key"]).startswith("open_paper_") for b in buttons
    )
```

- [ ] **Step 2: Run test — expect FAIL** (selectbox still present or AssertionError)

- [ ] **Step 3: Rewrite `render_evidence_literature_section`**

Remove `safe_table` + both selectboxes. Pattern:

```python
def _render_evidence_rows(rows: list[dict], *, key_prefix: str) -> None:
    for row in rows:
        pmid = str(row.get("PMID") or "").strip()
        left, right = st.columns([5, 1])
        with left:
            title = str(row.get("标题/实体") or "")
            st.markdown(f"**{title}**" if title else "_（无标题）_")
            meta = " · ".join(
                p for p in [
                    f"PMID `{pmid}`" if pmid else "",
                    str(row.get("工具") or ""),
                    str(row.get("证据章节") or ""),
                ] if p
            )
            if meta:
                st.caption(meta)
            quote = str(row.get("摘录") or "")
            if quote:
                st.markdown(quote)
            if not pmid:
                st.caption("缺 PMID，无法溯源")
        with right:
            if pmid:
                btn_key = provenance_row_key(
                    "evidence", pmid, title, quote
                )
                if st.button("溯源", key=f"open_{btn_key}"):
                    st.session_state["evidence_viewer"] = (
                        make_evidence_viewer_selection(pmid, quote)
                    )


def _render_paper_rows(rows: list[dict]) -> None:
    for row in rows:
        pmid = str(row.get("PMID") or "").strip()
        left, right = st.columns([5, 1])
        with left:
            title = str(row.get("标题") or "")
            st.markdown(f"**{title}**" if title else "_（无标题）_")
            meta = " · ".join(
                str(x) for x in [
                    f"PMID `{pmid}`" if pmid else "",
                    row.get("年份") or "",
                    row.get("期刊") or "",
                    row.get("研究类型") or "",
                    row.get("来源") or "",
                ] if x
            )
            if meta:
                st.caption(meta)
            if not pmid:
                st.caption("缺 PMID，无法溯源")
        with right:
            if pmid:
                btn_key = provenance_row_key("paper", pmid, title)
                if st.button("溯源", key=f"open_{btn_key}"):
                    st.session_state["evidence_viewer"] = (
                        make_evidence_viewer_selection(pmid)
                    )
```

In `render_evidence_literature_section`:

- Evidence: split into `with_pmid` / `without_pmid`; show without_pmid as text-only rows (or include in list with caption); `head, tail = partition_provenance_rows(with_pmid)`; render head; if tail: `with st.expander(f"更多证据（{len(tail)}）"):` render tail.
- Papers: same with `partition_provenance_rows` on PMID-backed papers; expander「更多论文」.
- Keep corpus strategy caption.
- Keep viewer block at bottom unchanged (warning format, height=720, close button).

Escape note: titles/quotes may contain markdown characters; prefer `st.write` / plain text over raw untrusted HTML. Using `st.markdown` with user text is pre-existing risk; do not introduce `unsafe_allow_html` for these fields.

- [ ] **Step 4: Run tests**

```
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer_ui.py tests/test_evidence_viewer.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit** (if enabled)

```bash
git add fulltext_workflow/gap_ui.py fulltext_workflow/tests/test_evidence_viewer_ui.py
git commit -m "feat: use per-row 溯源 buttons on 证据与文献 tab"
```

---

## Self-review (plan vs spec)

| Spec item | Task |
|-----------|------|
| Remove selectboxes | Task 2 |
| Full titles / no 40-char clip | Task 1 title + Task 2 markdown |
| Cap 30 + expander | Task 1 partition + Task 2 |
| Stable keys | Task 1 `provenance_row_key` |
| Viewer unchanged | Task 2 keeps bottom block |
| Tests updated | Tasks 1–2 |
