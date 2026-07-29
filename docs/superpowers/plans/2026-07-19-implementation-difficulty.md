# Implementation Difficulty (Target + Assessed) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users pick `easy|moderate|hard` before proposal generation, deterministically assess difficulty from journal quartile/IF + Fangxin/public data, and show color-coded target vs assessed (annotate only, no gate).

**Architecture:** Pure scoring in `analysis/difficulty_scoring.py`; gather supporting papers (with journal Q/IF) and public datasets in a small helper; `stream_idea_agent` injects target, emits `difficulty_assessed`, prepends Markdown summary; Gap UI selectbox + colored pills; persist columns on `ops_proposals`.

**Tech Stack:** Python 3, SQLite, pytest, Streamlit (`gap_ui.py`), existing `impact_scoring` / `feasibility_assess` / `datasets_for_topic` / `access_class`.

**Spec:** `docs/superpowers/specs/2026-07-19-implementation-difficulty-design.md`

## Global Constraints

- Levels only: `easy` | `moderate` | `hard` (ordinal 0/1/2).
- `assessed = max(research_bar, engineering_bar)`; mismatch is **annotate-only** (no Critic accept gate on `difficulty_delta`).
- Fangxin primary; public `access_class=public` may relieve engineering by at most one tier; `private`/`unknown` never relieve.
- No extractor schema changes; re-extract (separate work) refreshes `access_class`.
- Do **not** commit unless the user explicitly asks.
- Working directory for commands: `fulltext_workflow/` with `..\.venv\Scripts\python.exe -m pytest …`.

## File map

| File | Role |
|------|------|
| `fulltext_workflow/analysis/difficulty_scoring.py` | Pure scoring + color + Markdown header helper |
| `fulltext_workflow/tests/test_difficulty_scoring.py` | Unit tests for scoring |
| `fulltext_workflow/config.py` | Tunable thresholds |
| `fulltext_workflow/idea_agent.py` | Target inject, gather inputs, emit event, header |
| `fulltext_workflow/db/schema.py` | `ops_proposals` difficulty columns + migration |
| `fulltext_workflow/analysis/ops_memory.py` | Pass-through on `persist_proposal` |
| `fulltext_workflow/gap_ui.py` | Selectbox + color pills + persist fields |
| `fulltext_workflow/tests/test_ops_memory.py` | Persist new columns (extend existing) |

---

### Task 1: Config + pure difficulty scoring (TDD)

**Files:**
- Create: `fulltext_workflow/analysis/difficulty_scoring.py`
- Create: `fulltext_workflow/tests/test_difficulty_scoring.py`
- Modify: `fulltext_workflow/config.py`

**Interfaces:**
- Produces:
  - `DIFFICULTY_LEVELS = ("easy", "moderate", "hard")`
  - `difficulty_ordinal(level: str) -> int`
  - `difficulty_color(delta: int) -> str`  # `"green"|"amber"|"red"`
  - `research_bar_from_papers(papers: list[dict]) -> dict`  # includes `research_bar`, `q1_ratio`, `avg_if`, `q_coverage`, `q_coverage_low`
  - `fangxin_tier(feasibility_score: float | None, cohort: int | None) -> str`
  - `apply_public_relief(fangxin_tier: str, public_datasets: list[str]) -> tuple[str, list[str]]`
  - `assess_implementation_difficulty(*, target_difficulty: str, papers: list[dict], feasibility_score: float | None, available_cohort_size: int | None, public_datasets: list[str]) -> dict`

- [ ] **Step 1: Add config thresholds**

Append to `fulltext_workflow/config.py`:

```python
# Implementation difficulty (proposal target / assessed)
DIFFICULTY_Q1_HARD: float = float(os.getenv("DIFFICULTY_Q1_HARD", "0.55"))
DIFFICULTY_Q1_MODERATE: float = float(os.getenv("DIFFICULTY_Q1_MODERATE", "0.25"))
DIFFICULTY_IF_HARD: float = float(os.getenv("DIFFICULTY_IF_HARD", "8.0"))
DIFFICULTY_IF_MODERATE: float = float(os.getenv("DIFFICULTY_IF_MODERATE", "3.0"))
DIFFICULTY_Q_COVERAGE_LOW: float = float(os.getenv("DIFFICULTY_Q_COVERAGE_LOW", "0.4"))
DIFFICULTY_FX_EASY_SCORE: float = float(os.getenv("DIFFICULTY_FX_EASY_SCORE", "0.8"))
DIFFICULTY_FX_EASY_COHORT: int = int(os.getenv("DIFFICULTY_FX_EASY_COHORT", "500"))
DIFFICULTY_FX_MOD_SCORE: float = float(os.getenv("DIFFICULTY_FX_MOD_SCORE", "0.5"))
DIFFICULTY_FX_MOD_COHORT: int = int(os.getenv("DIFFICULTY_FX_MOD_COHORT", "200"))
```

- [ ] **Step 2: Write failing tests**

Create `fulltext_workflow/tests/test_difficulty_scoring.py`:

```python
from analysis.difficulty_scoring import (
    assess_implementation_difficulty,
    difficulty_color,
    difficulty_ordinal,
    fangxin_tier,
    research_bar_from_papers,
    apply_public_relief,
)


def test_ordinal_and_color():
    assert difficulty_ordinal("easy") == 0
    assert difficulty_ordinal("hard") == 2
    assert difficulty_color(0) == "green"
    assert difficulty_color(1) == "amber"
    assert difficulty_color(-2) == "red"


def test_research_bar_hard_on_q1():
    papers = [{"quartile": "Q1", "impact_factor": 4.0}] * 6 + [
        {"quartile": "Q3", "impact_factor": 1.0}
    ] * 2
    out = research_bar_from_papers(papers)
    assert out["research_bar"] == "hard"
    assert out["q1_ratio"] >= 0.55


def test_research_bar_missing_q_is_easy_and_low_coverage():
    papers = [{"quartile": None, "impact_factor": None}] * 5
    out = research_bar_from_papers(papers)
    assert out["research_bar"] == "easy"
    assert out["q_coverage_low"] is True


def test_preprint_not_q1():
    papers = [
        {"quartile": "Q1", "impact_factor": 10.0, "journal_abbr": "bioRxiv"},
        {"quartile": "Q1", "impact_factor": 10.0, "journal_name": "medRxiv"},
    ]
    out = research_bar_from_papers(papers)
    assert out["q1_ratio"] == 0.0


def test_fangxin_tier_and_public_relief():
    assert fangxin_tier(0.9, 600) == "easy"
    assert fangxin_tier(0.2, 50) == "hard"
    eng, used = apply_public_relief("hard", ["Camelyon17"])
    assert eng == "moderate"
    assert used == ["Camelyon17"]
    eng2, used2 = apply_public_relief("hard", [])
    assert eng2 == "hard"
    assert used2 == []


def test_assess_max_combine_and_delta():
    papers = [{"quartile": "Q1", "impact_factor": 12.0}] * 10
    result = assess_implementation_difficulty(
        target_difficulty="easy",
        papers=papers,
        feasibility_score=0.9,
        available_cohort_size=800,
        public_datasets=[],
    )
    assert result["research_bar"] == "hard"
    assert result["engineering_bar"] == "easy"
    assert result["assessed_difficulty"] == "hard"
    assert result["difficulty_delta"] == 2
    assert result["color"] == "red"
```

- [ ] **Step 3: Run tests — expect FAIL**

```powershell
cd D:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_difficulty_scoring.py -v
```

Expected: import / collection errors (`ModuleNotFoundError` or similar).

- [ ] **Step 4: Implement `difficulty_scoring.py`**

Create `fulltext_workflow/analysis/difficulty_scoring.py` with:

```python
"""Deterministic proposal implementation difficulty (target vs assessed)."""
from __future__ import annotations

import re
from typing import Any

import config

DIFFICULTY_LEVELS = ("easy", "moderate", "hard")
_PREPRINT = re.compile(r"biorxiv|medrxiv|arxiv|preprint|research square", re.I)


def difficulty_ordinal(level: str) -> int:
    key = (level or "").strip().lower()
    if key not in DIFFICULTY_LEVELS:
        raise ValueError(f"invalid difficulty level: {level!r}")
    return DIFFICULTY_LEVELS.index(key)


def difficulty_color(delta: int) -> str:
    if delta == 0:
        return "green"
    if abs(int(delta)) == 1:
        return "amber"
    return "red"


def _is_preprint(row: dict[str, Any]) -> bool:
    blob = " ".join(
        str(row.get(k) or "")
        for k in ("journal_abbr", "journal_name", "name", "abbr")
    )
    return bool(_PREPRINT.search(blob))


def _valid_quartile(q: Any) -> str | None:
    if q is None:
        return None
    s = str(q).strip().upper()
    if s in ("", "NAN", "NONE", "NULL"):
        return None
    if s.startswith("Q") and s[1:2].isdigit():
        return s[:2] if len(s) >= 2 else s
    return None


def research_bar_from_papers(papers: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(papers)
    if n == 0:
        return {
            "research_bar": "easy",
            "q1_ratio": 0.0,
            "avg_if": 0.0,
            "q_coverage": 0.0,
            "q_coverage_low": True,
            "support_paper_cnt": 0,
        }

    q_ok = 0
    q1 = 0
    ifs: list[float] = []
    for r in papers:
        if _is_preprint(r):
            continue
        q = _valid_quartile(r.get("quartile"))
        if q:
            q_ok += 1
            if q == "Q1":
                q1 += 1
        raw_if = r.get("impact_factor")
        if raw_if is not None and str(raw_if).strip() != "":
            try:
                v = float(raw_if)
                if v > 0:
                    ifs.append(v)
            except (TypeError, ValueError):
                pass

    # q1_ratio and q_coverage over full |S| (spec); preprints simply never increment q1/q_ok
    q1_ratio = q1 / n
    q_coverage = q_ok / n
    avg_if = sum(ifs) / len(ifs) if ifs else 0.0

    if q1_ratio >= config.DIFFICULTY_Q1_HARD or avg_if >= config.DIFFICULTY_IF_HARD:
        bar = "hard"
    elif q1_ratio >= config.DIFFICULTY_Q1_MODERATE or avg_if >= config.DIFFICULTY_IF_MODERATE:
        bar = "moderate"
    else:
        bar = "easy"

    return {
        "research_bar": bar,
        "q1_ratio": round(q1_ratio, 3),
        "avg_if": round(avg_if, 2),
        "q_coverage": round(q_coverage, 3),
        "q_coverage_low": q_coverage < config.DIFFICULTY_Q_COVERAGE_LOW,
        "support_paper_cnt": n,
    }


def fangxin_tier(feasibility_score: float | None, cohort: int | None) -> str:
    score = float(feasibility_score) if feasibility_score is not None else 0.0
    size = int(cohort) if cohort is not None else 0
    if score >= config.DIFFICULTY_FX_EASY_SCORE and size >= config.DIFFICULTY_FX_EASY_COHORT:
        return "easy"
    if score >= config.DIFFICULTY_FX_MOD_SCORE or size >= config.DIFFICULTY_FX_MOD_COHORT:
        return "moderate"
    return "hard"


def apply_public_relief(
    tier: str, public_datasets: list[str]
) -> tuple[str, list[str]]:
    names = [n for n in public_datasets if n and str(n).strip()]
    if not names or tier == "easy":
        return tier, []
    idx = difficulty_ordinal(tier)
    new_tier = DIFFICULTY_LEVELS[max(0, idx - 1)]
    return new_tier, names


def assess_implementation_difficulty(
    *,
    target_difficulty: str,
    papers: list[dict[str, Any]],
    feasibility_score: float | None,
    available_cohort_size: int | None,
    public_datasets: list[str],
) -> dict[str, Any]:
    target = (target_difficulty or "moderate").strip().lower()
    if target not in DIFFICULTY_LEVELS:
        target = "moderate"

    research = research_bar_from_papers(papers)
    fx = fangxin_tier(feasibility_score, available_cohort_size)
    engineering, relies_on_public = apply_public_relief(fx, public_datasets)

    assessed = DIFFICULTY_LEVELS[
        max(
            difficulty_ordinal(research["research_bar"]),
            difficulty_ordinal(engineering),
        )
    ]
    delta = difficulty_ordinal(assessed) - difficulty_ordinal(target)
    color = difficulty_color(delta)

    breakdown = {
        **research,
        "fangxin_tier": fx,
        "engineering_bar": engineering,
        "feasibility_score": feasibility_score,
        "available_cohort_size": available_cohort_size,
        "relies_on_public": relies_on_public,
    }
    summary = (
        f"research={research['research_bar']} (Q1 {research['q1_ratio']:.0%}) · "
        f"engineering={engineering} (Fangxin {feasibility_score if feasibility_score is not None else 'n/a'}"
        + (f" + public: {', '.join(relies_on_public)}" if relies_on_public else "")
        + ")"
    )
    return {
        "target_difficulty": target,
        "assessed_difficulty": assessed,
        "research_bar": research["research_bar"],
        "engineering_bar": engineering,
        "difficulty_delta": delta,
        "color": color,
        "q_coverage_low": research["q_coverage_low"],
        "breakdown": breakdown,
        "summary_line": summary,
    }


def format_difficulty_markdown_header(result: dict[str, Any]) -> str:
    """Plain-text header for proposal Markdown (colors live in UI)."""
    low = " | Q coverage low" if result.get("q_coverage_low") else ""
    return (
        f"> **Difficulty** · target=`{result['target_difficulty']}` · "
        f"assessed=`{result['assessed_difficulty']}` · "
        f"delta={result['difficulty_delta']:+d} ({result['color']}){low}\n"
        f"> {result['summary_line']}\n"
    )
```

- [ ] **Step 5: Run tests — expect PASS**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_difficulty_scoring.py -v
```

Expected: all PASSED.

---

### Task 2: Gather papers (Q/IF) + public datasets for a gap keyword

**Files:**
- Modify: `fulltext_workflow/analysis/difficulty_scoring.py` (add gather helpers) **or** prefer keep pure scoring and add gather in `idea_agent.py` — **this task adds gather functions to `difficulty_scoring.py`** for testability.
- Modify: `fulltext_workflow/tests/test_difficulty_scoring.py`

**Interfaces:**
- Consumes: `search_papers_for_topic`, `get_conn`, `tool_datasets_for_topic` pattern / SQL
- Produces:
  - `load_supporting_papers_for_keyword(keyword: str, limit: int | None = None) -> list[dict]`
  - `load_public_datasets_for_keyword(keyword: str) -> list[str]`

- [ ] **Step 1: Write failing tests with monkeypatched DB helpers**

Add tests that call gather functions with monkeypatch returning fake rows (no live DB required), e.g. patch `search_papers_for_topic` and a small SQL wrapper.

```python
def test_load_public_datasets_filters_public_only(monkeypatch):
    from analysis import difficulty_scoring as ds

    def fake_datasets(keyword: str) -> dict:
        return {
            "data": [
                {"dataset": "Camelyon17", "access_class": "public"},
                {"dataset": "HospitalX", "access_class": "private"},
                {"dataset": "Mystery", "access_class": "unknown"},
            ]
        }

    monkeypatch.setattr(ds, "_datasets_for_topic_rows", fake_datasets)
    assert ds.load_public_datasets_for_keyword("npc") == ["Camelyon17"]
```

- [ ] **Step 2: Implement gather helpers**

In `difficulty_scoring.py`:

```python
def _datasets_for_topic_rows(keyword: str) -> dict:
    # Late import to avoid cycles; mirrors idea_agent.tool_datasets_for_topic
    from idea_agent import tool_datasets_for_topic
    return tool_datasets_for_topic(keyword)


def load_public_datasets_for_keyword(keyword: str) -> list[str]:
    payload = _datasets_for_topic_rows(keyword)
    rows = payload.get("data") or []
    return [
        str(r["dataset"])
        for r in rows
        if str(r.get("access_class") or "unknown").lower() == "public"
        and r.get("dataset")
    ]


def load_supporting_papers_for_keyword(
    keyword: str, limit: int | None = None
) -> list[dict[str, Any]]:
    from analysis.focus_filter import search_papers_for_topic

    lim = limit if limit is not None else config.TOOL_TOP_N
    select = (
        "p.pmid, p.title, p.year, p.journal_name, p.journal_abbr, "
        "p.citation_count, j.quartile, j.impact_factor"
    )
    # search_papers_for_topic only selects from papers p — join journals via subquery workaround:
    rows, _strategy = search_papers_for_topic(
        keyword,
        limit=lim,
        select_columns=(
            "p.pmid, p.title, p.year, p.journal_name, p.journal_abbr, "
            "p.citation_count, p.journal_id"
        ),
    )
    if not rows:
        return []
    from db.schema import get_conn

    ids = [int(r["journal_id"]) for r in rows if r.get("journal_id") is not None]
    jmap: dict[int, dict] = {}
    if ids:
        placeholders = ",".join("?" * len(ids))
        with get_conn() as conn:
            jrows = conn.execute(
                f"SELECT id, quartile, impact_factor, abbr, name FROM journals "
                f"WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        jmap = {int(j["id"]): dict(j) for j in jrows}
    out = []
    for r in rows:
        d = dict(r)
        j = jmap.get(int(d["journal_id"])) if d.get("journal_id") is not None else None
        if j:
            d["quartile"] = j.get("quartile")
            d["impact_factor"] = j.get("impact_factor")
        else:
            d.setdefault("quartile", None)
            d.setdefault("impact_factor", None)
        out.append(d)
    return out
```

If `search_papers_for_topic` + second query is awkward, alternatively add a dedicated SQL in this module using `resolve_topic_pmids` + `JOIN journals j ON p.journal_id = j.id` (preferred if cleaner). **Prefer one SQL with JOIN** when implementing:

```sql
SELECT p.pmid, p.title, p.year, p.journal_name, p.journal_abbr,
       p.citation_count, j.quartile, j.impact_factor
FROM papers p
LEFT JOIN journals j ON p.journal_id = j.id
WHERE p.pmid IN (...)
ORDER BY p.year DESC
LIMIT ?
```

Use `resolve_topic_pmids` from `analysis.focus_filter` for the PMID list.

- [ ] **Step 3: Run tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_difficulty_scoring.py -v
```

Expected: PASS.

---

### Task 3: Wire `stream_idea_agent`

**Files:**
- Modify: `fulltext_workflow/idea_agent.py`
- Modify: `fulltext_workflow/tests/test_feasibility.py` **or** add `fulltext_workflow/tests/test_idea_difficulty_wiring.py` with mocked stream internals if full stream is heavy — prefer a small unit test for header injection helper if extracted; otherwise smoke-test the assessment call site with mocks.

**Interfaces:**
- Consumes: `assess_implementation_difficulty`, `load_supporting_papers_for_keyword`, `load_public_datasets_for_keyword`, `format_difficulty_markdown_header`
- Produces: `stream_idea_agent(..., target_difficulty: str = "moderate")`; events `difficulty_assessed`; `final` payload includes difficulty fields; proposal content may gain Markdown header

- [ ] **Step 1: Extend signature and Designer prompt**

In `stream_idea_agent`:

```python
def stream_idea_agent(
    gap_text: str,
    gap_data: dict | None = None,
    max_rounds: int = 3,
    accept_score: float = ACCEPT_SCORE,
    target_difficulty: str = "moderate",
) -> Generator[dict, None, None]:
```

At start, normalize target; append to `gap_context`:

```text
Target implementation difficulty: {target}.
Steer methods/evidence toward this tier (easy=landable/mid-tier venues; hard=may align with high-Q1 methods).
Fangxin remains primary when feasible; label any public datasets. Assessed difficulty is computed by the host (do not invent it).
```

Yield start event including `target_difficulty`.

- [ ] **Step 2: Capture cohort from feasibility tool results**

Extend `_capture_feasibility_from_event` to also store `available_cohort_size` (nonlocal), reading `result.get("available_cohort_size")`.

- [ ] **Step 3: After loop (before/with `final`), compute and yield difficulty**

```python
papers = load_supporting_papers_for_keyword(gap_text)
public_ds = load_public_datasets_for_keyword(gap_text)
diff = assess_implementation_difficulty(
    target_difficulty=target_difficulty,
    papers=papers,
    feasibility_score=feasibility_score,
    available_cohort_size=available_cohort_size,
    public_datasets=public_ds,
)
yield {"type": "difficulty_assessed", **diff}
```

Prepend `format_difficulty_markdown_header(diff)` to final proposal Markdown if not already present.

Include in `final` event: `target_difficulty`, `assessed_difficulty`, `difficulty_delta`, `difficulty_color` (= `color`), `difficulty_breakdown` (= `breakdown`), `difficulty_summary` (= `summary_line`), `q_coverage_low`.

**Do not** change Critic accept rules based on delta.

- [ ] **Step 4: Manual/unit check**

If adding `tests/test_idea_difficulty_wiring.py`, mock gather + assess and assert event keys. Otherwise run existing idea/feasibility tests:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_feasibility.py tests/test_difficulty_scoring.py -v
```

Expected: PASS.

---

### Task 4: Persist difficulty on `ops_proposals`

**Files:**
- Modify: `fulltext_workflow/db/schema.py` (`SCHEMA_SQL` create + `_migrate_db` + `insert_ops_proposal`)
- Modify: `fulltext_workflow/analysis/ops_memory.py` (`persist_proposal`)
- Modify: `fulltext_workflow/tests/test_ops_memory.py`

**Interfaces:**
- Produces: columns `target_difficulty TEXT`, `assessed_difficulty TEXT`, `difficulty_delta INTEGER`, `difficulty_breakdown_json TEXT` on `ops_proposals`; `insert_ops_proposal` / `persist_proposal` kwargs for the same.

- [ ] **Step 1: Failing test — persist round-trip**

Extend `test_ops_memory.py` to call `persist_proposal(..., target_difficulty="easy", assessed_difficulty="hard", difficulty_delta=2, difficulty_breakdown_json='{"research_bar":"hard"}')` and SELECT assert columns.

- [ ] **Step 2: Migration**

In `_migrate_db`, after ops_proposals column checks (near existing `critic_score` migrate):

```python
prop_cols = {r[1] for r in conn.execute("PRAGMA table_info(ops_proposals)").fetchall()}
for col, ddl in (
    ("target_difficulty", "ALTER TABLE ops_proposals ADD COLUMN target_difficulty TEXT"),
    ("assessed_difficulty", "ALTER TABLE ops_proposals ADD COLUMN assessed_difficulty TEXT"),
    ("difficulty_delta", "ALTER TABLE ops_proposals ADD COLUMN difficulty_delta INTEGER"),
    ("difficulty_breakdown_json", "ALTER TABLE ops_proposals ADD COLUMN difficulty_breakdown_json TEXT"),
):
    if col not in prop_cols:
        conn.execute(ddl)
```

Also add the four columns to `CREATE TABLE IF NOT EXISTS ops_proposals` in `SCHEMA_SQL` / duplicate create block in `_migrate_db` if present.

- [ ] **Step 3: Update `insert_ops_proposal` and `persist_proposal` signatures** to accept and INSERT the four fields (`breakdown` stored as JSON string).

- [ ] **Step 4: Run tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_ops_memory.py tests/test_difficulty_scoring.py -v
```

Expected: PASS.

---

### Task 5: Gap UI — selectbox + color pills + persist

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (proposal tab ~1935–2050)

**Interfaces:**
- Consumes: `stream_idea_agent(..., target_difficulty=...)`, final/`difficulty_assessed` events
- Produces: UI selectbox; colored HTML/markdown pills; `persist_proposal` difficulty kwargs

- [ ] **Step 1: Add selectbox before Generate**

```python
target_difficulty_input = st.selectbox(
    "Target difficulty",
    options=["easy", "moderate", "hard"],
    index=1,
    key="proposal_target_difficulty",
    help="Steers proposal ambition; assessed difficulty is computed separately and color-coded.",
    on_change=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
)
```

Pass into stream:

```python
for event in stream_idea_agent(
    gap_text=str(gap_input).strip(),
    max_rounds=proposal_rounds_input,
    target_difficulty=target_difficulty_input,
):
```

- [ ] **Step 2: Handle `difficulty_assessed` / final fields**

On `difficulty_assessed` or `final`, store in `st.session_state`:

- `proposal_target_difficulty`
- `proposal_assessed_difficulty`
- `proposal_difficulty_delta`
- `proposal_difficulty_color`
- `proposal_difficulty_summary`
- `proposal_q_coverage_low`
- `proposal_difficulty_breakdown`

- [ ] **Step 3: Render pills above metrics**

Use Streamlit markdown HTML (salient colors):

```python
_color_map = {"green": "#2e7d32", "amber": "#ed6c02", "red": "#c62828"}
c = _color_map.get(st.session_state.get("proposal_difficulty_color") or "green", "#2e7d32")
tgt = st.session_state.get("proposal_target_difficulty")
asd = st.session_state.get("proposal_assessed_difficulty")
if tgt and asd:
    st.markdown(
        f'<div style="display:flex;gap:8px;align-items:center;margin:8px 0;">'
        f'<span style="padding:4px 10px;border-radius:999px;background:#eee;">Target: <b>{tgt}</b></span>'
        f'<span style="padding:4px 10px;border-radius:999px;background:{c};color:#fff;">'
        f'Assessed: <b>{asd}</b></span>'
        + (
            '<span style="padding:4px 10px;border-radius:999px;background:#9e9e9e;color:#fff;">Q coverage low</span>'
            if st.session_state.get("proposal_q_coverage_low")
            else ""
        )
        + f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(st.session_state.get("proposal_difficulty_summary") or "")
```

- [ ] **Step 4: Pass fields into `persist_proposal`**

```python
import json
persist_proposal(
    rid,
    gap_title=gap_title,
    proposal_md=event.get("content", ""),
    feasibility_score=...,
    critic_score=...,
    status="generated",
    target_difficulty=event.get("target_difficulty"),
    assessed_difficulty=event.get("assessed_difficulty"),
    difficulty_delta=event.get("difficulty_delta"),
    difficulty_breakdown_json=json.dumps(
        event.get("difficulty_breakdown") or {}, ensure_ascii=False
    ),
)
```

- [ ] **Step 5: Sanity check**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_difficulty_scoring.py tests/test_ops_memory.py tests/test_feasibility.py -v
```

Expected: PASS. Optionally open Gap UI and confirm pills for delta 0/1/2 (manual).

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| User target select | Task 5 |
| Deterministic assessed three-level | Task 1 |
| Color annotate, no gate | Task 1 color + Task 3/5 (no accept change) |
| research_bar from Q/IF | Task 1–2 |
| engineering Fangxin + public relief | Task 1–2 |
| Designer steering text | Task 3 |
| `difficulty_assessed` event | Task 3 |
| Persist columns | Task 4–5 |
| No extractor changes / re-extract note | Global constraints (no task) |
| Unit tests | Task 1–2, 4 |

## Placeholder / consistency self-check

- Function names aligned: `assess_implementation_difficulty`, `load_supporting_papers_for_keyword`, `load_public_datasets_for_keyword`, `format_difficulty_markdown_header`.
- Event field `color` mapped to UI as `difficulty_color` / `proposal_difficulty_color`.
- Cohort field name: `available_cohort_size` (matches feasibility assessment).
- No TBD/TODO left in steps.
