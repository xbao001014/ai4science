# Gap UI Ops Tab (Weekly Job + Clear Memory) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Gap UI「运维」Tab that starts the weekly pipeline as a background job with stage progress + log tail, plus a safe clear-ops-memory action, without blocking other tabs.

**Architecture:** `analysis/ops_jobs.py` owns job directories under `output/ops_jobs/`, `status.json` / `log.txt` / `current.json`, and a detached runner that sequentially calls `python main.py <step>`. Clear-memory core moves into `analysis/ops_memory.py` for UI + CLI reuse. Streamlit renders via a focused `ops_panel.py` imported by `gap_ui.py`, with ~2s fragment polling.

**Tech Stack:** Python 3, subprocess, SQLite via existing `db.schema`, Streamlit (`st.fragment` if available), pytest.

**Spec:** `docs/superpowers/specs/2026-08-04-gap-ui-ops-weekly-job-design.md`

## Global Constraints

- Scope A only: weekly one-click + clear ops memory (+ corpus stats refresh via existing `db_stats`).
- Weekly stages must match `run_pipeline.ps1 -Stage weekly` (10 steps; `enrich-s2` skippable).
- At most one `running` weekly job; refuse a second start.
- Background job survives Streamlit reruns via filesystem status; do not run weekly steps inside the Streamlit process.
- Clear memory never touches papers / KG / hotspot tables.
- Destructive UI actions require explicit confirmation checkboxes.
- Do not expose `clear_database` / `reset_extraction` / landscape / import-if in this UI.
- Run pytest from `fulltext_workflow/` (tests insert that root on `sys.path`).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the tree dirty and note the suggested commit message.
- Do not commit `fulltext_workflow/output/` or secrets.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/analysis/__init__.py` | **New** (empty) — enable `python -m analysis.ops_jobs` |
| `fulltext_workflow/analysis/ops_jobs.py` | **New** — weekly job create/start/cancel/read/reclaim; runner `__main__` |
| `fulltext_workflow/analysis/ops_memory.py` | **Modify** — add `preview_ops_memory` / `clear_ops_memory` (moved from script) |
| `fulltext_workflow/scripts/clear_ops_memory.py` | **Modify** — thin CLI wrapping `analysis.ops_memory` |
| `fulltext_workflow/ops_panel.py` | **New** — Streamlit render helpers for ops tab + sidebar chip + pure display helpers |
| `fulltext_workflow/gap_ui.py` | **Modify** — add「运维」to `MAIN_TAB_ENTRIES`; call `render_ops_tab` / sidebar status |
| `fulltext_workflow/tests/test_ops_jobs.py` | **New** — job state machine, skip, fail, cancel, concurrency, zombie |
| `fulltext_workflow/tests/test_ops_memory_clear.py` | **New** — preview/clear focus filter (temp SQLite) |
| `fulltext_workflow/tests/test_ops_panel_helpers.py` | **New** — step icon mapping, log tail, progress fraction |
| `fulltext_workflow/SCRIPTS.md` | **Modify** — Ops Tab ↔ CLI equivalence |
| `fulltext_workflow/gap_ui_guide.md` | **Modify** — short Ops Tab section |

---

### Task 1: Clear ops memory API in `ops_memory.py`

**Files:**
- Modify: `fulltext_workflow/analysis/ops_memory.py`
- Modify: `fulltext_workflow/scripts/clear_ops_memory.py`
- Test: `fulltext_workflow/tests/test_ops_memory_clear.py`

**Interfaces:**
- Consumes: `normalize_focus_key`, `db.schema.get_conn`, `init_db`
- Produces:
  - `preview_ops_memory(focus: str | None = None) -> dict` with keys `focus_key` (`str | None`, `None` = all), `counts: dict[str,int]` (`ops_runs`, `ops_gap_items`, `ops_proposals`), `file_paths: list[str]`
  - `clear_ops_memory(*, focus: str | None = None, execute: bool = False, delete_files: bool = False) -> dict` — same behavior as current script (`execute=False` dry-run; when `focus` is not `None` and blank → `__all__` lane)

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_ops_memory_clear.py`:

```python
"""Tests for ops memory preview/clear API."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.ops_memory import clear_ops_memory, preview_ops_memory  # noqa: E402
from db.schema import get_conn, init_db, insert_ops_run  # noqa: E402


def _tmp_db(monkeypatch):
    td = tempfile.mkdtemp()
    db = str(Path(td) / "t.db")
    monkeypatch.setattr(config, "DB_PATH", db)
    init_db()
    return db


def test_preview_and_clear_all(monkeypatch):
    _tmp_db(monkeypatch)
    insert_ops_run(week_id="2026-W31", focus_key="breast carcinoma")
    insert_ops_run(week_id="2026-W31", focus_key="__all__")
    prev = preview_ops_memory(None)
    assert prev["focus_key"] is None
    assert prev["counts"]["ops_runs"] == 2
    dry = clear_ops_memory(execute=False)
    assert dry["dry_run"] is True
    assert dry["before"]["ops_runs"] == 2
    done = clear_ops_memory(execute=True)
    assert done["after"]["ops_runs"] == 0


def test_clear_focus_lane_only(monkeypatch):
    _tmp_db(monkeypatch)
    insert_ops_run(week_id="2026-W31", focus_key="breast carcinoma")
    insert_ops_run(week_id="2026-W31", focus_key="__all__")
    clear_ops_memory(focus="breast cancer", execute=True)
    prev = preview_ops_memory(None)
    assert prev["counts"]["ops_runs"] == 1
```

Adjust `insert_ops_run` call kwargs to match the real signature in `db/schema.py` (read it before writing the test; keep the same assertions).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_ops_memory_clear.py -v`  
Expected: FAIL (import error or missing `preview_ops_memory`)

- [ ] **Step 3: Implement API + thin CLI**

Move `_counts`, `_collect_file_paths`, and `clear_ops_memory` from `scripts/clear_ops_memory.py` into `analysis/ops_memory.py`. Add:

```python
def preview_ops_memory(focus: str | None = None) -> dict:
    init_db()
    focus_key = None
    if focus is not None:
        focus_key = normalize_focus_key(focus) if str(focus).strip() else "__all__"
    with get_conn() as conn:
        counts = _counts(conn, focus_key)
        files = _collect_file_paths(conn, focus_key)
    return {"focus_key": focus_key, "counts": counts, "file_paths": files}
```

Keep `clear_ops_memory` semantics identical to the script (including print statements optional — prefer returning dicts; CLI can print).

Rewrite `scripts/clear_ops_memory.py` to:

```python
from analysis.ops_memory import clear_ops_memory

def main() -> None:
    # same argparse as today
    clear_ops_memory(focus=args.focus, execute=args.yes, delete_files=args.delete_files)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_ops_memory_clear.py tests/test_ops_memory.py -v`  
Expected: PASS (existing ops memory tests still green)

- [ ] **Step 5: Commit** (only if user requested commits)

Suggested message: `refactor: expose clear ops memory API for Gap UI`

---

### Task 2: Job status IO + weekly step plan

**Files:**
- Create: `fulltext_workflow/analysis/__init__.py` (empty)
- Create: `fulltext_workflow/analysis/ops_jobs.py` (status helpers + step plan first)
- Test: `fulltext_workflow/tests/test_ops_jobs.py`

**Interfaces:**
- Consumes: `config.OUTPUT_DIR`
- Produces:
  - `OPS_JOBS_DIR: Path` = `Path(config.OUTPUT_DIR) / "ops_jobs"`
  - `WEEKLY_STEPS: list[dict]` with `id` / `label` for the 10 steps
  - `build_weekly_argv(step_id: str, params: dict) -> list[str] | None` — returns `main.py` argv **without** python executable; returns `None` when step should be skipped
  - `new_job_id(kind: str = "weekly") -> str`
  - `job_dir(job_id: str) -> Path`
  - `write_status(job: dict) -> None` / `read_status(job_id: str) -> dict | None`
  - `write_current(job_id: str, state: str) -> None` / `read_current() -> dict | None`
  - `create_weekly_job(*, since_days: int = 14, extract_limit: int = 0, skip_enrich: bool = False) -> dict` — writes initial `status.json` with all steps `pending`, updates `current.json`, does **not** spawn
  - `append_log(job_id: str, text: str) -> None`
  - `tail_log(job_id: str, max_lines: int = 200) -> str`
  - `progress_counts(job: dict) -> tuple[int, int]` — completed (`succeeded`+`skipped`) / total

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_ops_jobs.py` (first batch):

```python
"""Tests for weekly ops job status + runner."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis import ops_jobs as oj  # noqa: E402


def _tmp_jobs(monkeypatch):
    td = Path(tempfile.mkdtemp())
    monkeypatch.setattr(oj, "OPS_JOBS_DIR", td / "ops_jobs")
    return td


def test_create_weekly_job_writes_status(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job(since_days=7, extract_limit=3, skip_enrich=True)
    assert job["kind"] == "weekly"
    assert job["state"] == "pending"
    assert len(job["steps"]) == 10
    assert job["params"]["skip_enrich"] is True
    loaded = oj.read_status(job["job_id"])
    assert loaded["job_id"] == job["job_id"]
    cur = oj.read_current()
    assert cur["job_id"] == job["job_id"]


def test_build_weekly_argv_skip_enrich(monkeypatch):
    _tmp_jobs(monkeypatch)
    params = {"since_days": 14, "extract_limit": 0, "skip_enrich": True}
    assert oj.build_weekly_argv("enrich-s2", params) is None
    fetch = oj.build_weekly_argv("fetch", params)
    assert fetch[:2] == ["fetch", "--since-days"]
    assert "14" in fetch
    ext = oj.build_weekly_argv("extract", {"since_days": 14, "extract_limit": 5, "skip_enrich": False})
    assert ext == ["extract", "--limit", "5", "--core-only"]


def test_tail_log_and_progress(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    oj.append_log(job["job_id"], "a\nb\nc\n")
    assert oj.tail_log(job["job_id"], max_lines=2) == "b\nc"
    job["steps"][0]["status"] = "succeeded"
    job["steps"][1]["status"] = "skipped"
    done, total = oj.progress_counts(job)
    assert (done, total) == (2, 10)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_ops_jobs.py -v`  
Expected: FAIL (module missing)

- [ ] **Step 3: Implement status IO + step plan**

In `ops_jobs.py`, implement the helpers above. Weekly step ids in order:

`fetch`, `enrich-s2`, `fetch-fulltext`, `extract`, `compute-gap-lifecycle`, `hotspot-report`, `hotspot-brief`, `build`, `analyze`, `stats`

`create_weekly_job` sets `state` to `pending` initially (runner / `start_weekly_job` flips to `running`).

Atomic-ish writes: write `status.json.tmp` then replace.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_ops_jobs.py -v`  
Expected: PASS

- [ ] **Step 5: Commit** (if requested)

Suggested: `feat: add weekly ops job status helpers`

---

### Task 3: Runner execute loop (injectable subprocess)

**Files:**
- Modify: `fulltext_workflow/analysis/ops_jobs.py`
- Modify: `fulltext_workflow/tests/test_ops_jobs.py`

**Interfaces:**
- Consumes: Task 2 helpers
- Produces:
  - `run_weekly_job(job_id: str, *, popen_factory=None) -> dict` — executes steps; default `popen_factory` runs `sys.executable` + `main.py` + argv with `cwd=fulltext_workflow` root; injectable factory `(argv: list[str], log_path: Path) -> CompletedProcess-like` with `.returncode`, `.stdout`, `.stderr` for tests
  - Prefer `subprocess.run` inside the **runner process** (already detached). Use a callable `run_step(argv, log_fh) -> int` injectable as `run_step_fn`.
  - `__main__`: `argparse` with `--run-job JOB_ID` calling `run_weekly_job`

- [ ] **Step 1: Write the failing tests**

Append to `test_ops_jobs.py`:

```python
def test_run_weekly_job_skips_enrich_and_succeeds(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job(skip_enrich=True)
    calls: list[list[str]] = []

    def fake_run(argv, log_fh):
        calls.append(list(argv))
        log_fh.write(f"ok {' '.join(argv)}\n")
        return 0

    result = oj.run_weekly_job(job["job_id"], run_step_fn=fake_run)
    assert result["state"] == "succeeded"
    assert all(c[0] != "enrich-s2" for c in calls)
    enrich = next(s for s in result["steps"] if s["id"] == "enrich-s2")
    assert enrich["status"] == "skipped"
    assert calls[0][0] == "fetch"


def test_run_weekly_job_stops_on_failure(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job(skip_enrich=True)

    def fake_run(argv, log_fh):
        if argv[0] == "fetch-fulltext":
            log_fh.write("boom\n")
            return 2
        return 0

    result = oj.run_weekly_job(job["job_id"], run_step_fn=fake_run)
    assert result["state"] == "failed"
    ft = next(s for s in result["steps"] if s["id"] == "fetch-fulltext")
    assert ft["status"] == "failed"
    later = next(s for s in result["steps"] if s["id"] == "build")
    assert later["status"] == "pending"
```

- [ ] **Step 2: Run tests — expect FAIL** (`run_weekly_job` missing)

- [ ] **Step 3: Implement `run_weekly_job`**

Logic:
1. Load status; set `state=running`, record `pid=os.getpid()`, `started_at`.
2. For each step: if `build_weekly_argv` is `None` → mark `skipped` and continue.
3. Else mark `running`, call `run_step_fn(argv, log_fh)`; on 0 → `succeeded`; else → `failed`, set job `error`, `state=failed`, break.
4. If all done → `state=succeeded`, `finished_at`.
5. Always `write_current` with latest state.

Default `run_step_fn`:

```python
def _default_run_step(argv: list[str], log_fh) -> int:
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(root / "main.py"), *argv]
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log_fh.write(proc.stdout or "")
    log_fh.flush()
    return int(proc.returncode)
```

`__main__` block:

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-job", required=True)
    args = parser.parse_args()
    run_weekly_job(args.run_job)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_ops_jobs.py -v`

- [ ] **Step 5: Commit** (if requested)

Suggested: `feat: run weekly ops jobs step-by-step with injectable runner`

---

### Task 4: Start / cancel / concurrency / zombie

**Files:**
- Modify: `fulltext_workflow/analysis/ops_jobs.py`
- Modify: `fulltext_workflow/tests/test_ops_jobs.py`

**Interfaces:**
- Produces:
  - `get_active_weekly_job() -> dict | None` — read current; if `running`, reclaim zombie first; return status or `None`
  - `reclaim_zombie(job: dict) -> dict` — if `state==running` and pid dead → `failed` with error `process exited unexpectedly`
  - `pid_is_alive(pid: int) -> bool`
  - `start_weekly_job(*, since_days=14, extract_limit=0, skip_enrich=False, spawn_fn=None) -> dict` — raises `OpsJobError` if another running; creates job; spawns detached process; returns status
  - `cancel_weekly_job(job_id: str | None = None) -> dict` — terminate process tree; mark current step `cancelled`, job `cancelled`
  - `OpsJobError(Exception)`

Default spawn (Windows-friendly):

```python
def _default_spawn(job_id: str) -> int:
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-m", "analysis.ops_jobs", "--run-job", job_id]
    # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS on Windows
    kwargs = {"cwd": str(root), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    return int(proc.pid)
```

Note: runner overwrites `status.pid` with its own pid on start of `run_weekly_job` — that is the pid to kill on cancel. `start_weekly_job` may briefly store spawn pid then runner updates it; cancel should prefer status.pid after a short read, and kill that tree.

Cancel on Windows: `subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"])` when `win32`, else `os.killpg` / `SIGTERM`.

- [ ] **Step 1: Write failing tests**

```python
class OpsJobError(Exception):
    pass  # only in test import from module after impl


def test_start_rejects_second_running(monkeypatch):
    _tmp_jobs(monkeypatch)
    spawned = []

    def spawn(job_id):
        spawned.append(job_id)
        return 4242

    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: True)
    j1 = oj.start_weekly_job(spawn_fn=spawn, skip_enrich=True)
    # Simulate runner marked running with alive pid
    j1["state"] = "running"
    j1["pid"] = 4242
    oj.write_status(j1)
    oj.write_current(j1["job_id"], "running")
    try:
        oj.start_weekly_job(spawn_fn=spawn)
        assert False, "expected OpsJobError"
    except oj.OpsJobError:
        pass
    assert len(spawned) == 1


def test_reclaim_zombie(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["state"] = "running"
    job["pid"] = 999001
    oj.write_status(job)
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: False)
    out = oj.reclaim_zombie(oj.read_status(job["job_id"]))
    assert out["state"] == "failed"
    assert "exited" in (out.get("error") or "").lower()


def test_cancel_marks_cancelled(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["state"] = "running"
    job["pid"] = 777
    job["steps"][0]["status"] = "running"
    oj.write_status(job)
    oj.write_current(job["job_id"], "running")
    killed = []

    def fake_kill(pid):
        killed.append(pid)

    monkeypatch.setattr(oj, "_kill_process_tree", fake_kill)
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: True)
    out = oj.cancel_weekly_job(job["job_id"])
    assert out["state"] == "cancelled"
    assert out["steps"][0]["status"] == "cancelled"
    assert killed == [777]
```

- [ ] **Step 2–4:** Implement, run `pytest tests/test_ops_jobs.py -v`, expect PASS

- [ ] **Step 5: Commit** (if requested)

Suggested: `feat: start/cancel weekly ops jobs with zombie reclaim`

---

### Task 5: Ops panel helpers + Streamlit UI

**Files:**
- Create: `fulltext_workflow/ops_panel.py`
- Modify: `fulltext_workflow/gap_ui.py` (`MAIN_TAB_ENTRIES`, tab unpack, sidebar chip)
- Test: `fulltext_workflow/tests/test_ops_panel_helpers.py`

**Interfaces:**
- Consumes: `analysis.ops_jobs`, `analysis.ops_memory.preview_ops_memory` / `clear_ops_memory`
- Produces (pure, tested):
  - `step_status_icon(status: str) -> str` — `○`/`●`/`✓`/`–`/`✗`/`■` for pending/running/succeeded/skipped/failed/cancelled
  - `format_sidebar_job_chip(job: dict | None) -> str` — `周更：空闲` or `周更：进行中 · fetch`
  - `render_ops_tab(focus_hint: str = "") -> None`
  - `render_ops_sidebar_chip() -> None`

- [ ] **Step 1: Write failing helper tests**

```python
from ops_panel import format_sidebar_job_chip, step_status_icon

def test_step_status_icon():
    assert step_status_icon("pending") == "○"
    assert step_status_icon("running") == "●"
    assert step_status_icon("succeeded") == "✓"
    assert step_status_icon("skipped") == "–"
    assert step_status_icon("failed") == "✗"

def test_sidebar_chip():
    assert format_sidebar_job_chip(None) == "周更：空闲"
    job = {
        "state": "running",
        "steps": [
            {"id": "fetch", "status": "succeeded"},
            {"id": "enrich-s2", "status": "running"},
        ],
    }
    assert "enrich-s2" in format_sidebar_job_chip(job)
```

- [ ] **Step 2: Implement `ops_panel.py` UI**

`render_ops_tab`:
1. Section **周常一键更新** — number inputs / checkbox; Start disabled if active running; on click `start_weekly_job(...)` with try/except `OpsJobError`.
2. Progress: `st.progress(done/total)`; list steps with icons.
3. Expander log via `tail_log`.
4. Cancel: checkbox「确认取消」+ button → `cancel_weekly_job`.
5. Polling: wrap status block in `@st.fragment(run_every=2)` if available; always include「刷新状态」button (`st.rerun()`).
6. Section **清空 ops 记忆** — preview counts; radio 全部/仅当前焦点 (disable focus option when `normalize_focus(focus_hint)` empty); checkbox delete files; checkbox「我确认清空」; execute button.

`gap_ui.py` changes:
- Append `("ops-maintenance", "运维")` to `MAIN_TAB_ENTRIES`.
- Unpack extra `tab_ops` from `st.tabs(...)`.
- In both empty-events and filled-events branches, `with tab_ops: render_ops_tab(focus_hint=focus_input)`.
- Near end of sidebar (after debate button / before session stats is fine): `render_ops_sidebar_chip()`.

If `st.fragment` is unavailable in the installed Streamlit, degrade to manual refresh only (feature-detect with `hasattr(st, "fragment")`).

- [ ] **Step 3: Run helper tests**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_ops_panel_helpers.py tests/test_ops_jobs.py tests/test_ops_memory_clear.py -v`  
Expected: PASS

- [ ] **Step 4: Manual smoke** (engineer)

1. `..\.venv\Scripts\streamlit.exe run gap_ui.py`
2. Open「运维」— confirm controls render.
3. Optional: start weekly with `ExtractLimit=0` only if DB/network OK; otherwise start is enough to see `running` then cancel.
4. Clear memory dry path: uncheck confirm → button disabled; with confirm on empty DB → succeeds.

- [ ] **Step 5: Commit** (if requested)

Suggested: `feat: add Gap UI ops tab for weekly job and clear memory`

---

### Task 6: Docs

**Files:**
- Modify: `fulltext_workflow/SCRIPTS.md`
- Modify: `fulltext_workflow/gap_ui_guide.md`

- [ ] **Step 1: Update SCRIPTS.md**

Under section 1 (一键脚本), add:

```markdown
### Gap UI「运维」Tab

等价于后台执行 `-Stage weekly`（阶段进度 + 日志），并支持清空 ops 记忆：

- 周更参数：`SinceDays` / `ExtractLimit` / `SkipEnrich`
- 清空记忆：对应 `scripts/clear_ops_memory.py`（预览 + `--yes` + 可选 `--focus` / `--delete-files`）
```

- [ ] **Step 2: Update gap_ui_guide.md**

Add a short「运维」section: start weekly, read progress, cancel, clear memory confirmations; note other tabs usable while job runs.

- [ ] **Step 3: Commit** (if requested)

Suggested: `docs: document Gap UI ops tab weekly job`

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Ops Tab + sidebar chip | 5 |
| Weekly 10 steps aligned with ps1 | 2–3 |
| Background job + status/log files | 2–4 |
| Stage progress + log tail + polling | 5 |
| SkipEnrich → skipped | 3 |
| Single running job | 4 |
| Cancel + zombie | 4 |
| Clear memory preview/confirm/focus/files | 1 + 5 |
| Tests for jobs / clear / helpers | 1–5 |
| SCRIPTS + gap_ui_guide | 6 |
| No clear_database / landscape in UI | 5 (non-goal) |

## Self-review notes

- No TBD placeholders; runner entry is `python -m analysis.ops_jobs --run-job` with new empty `analysis/__init__.py`.
- `insert_ops_run` kwargs in Task 1 must be checked against `db/schema.py` at implementation time.
- `gap_ui.py` has two tab-content branches (empty vs filled events) — both must host `tab_ops`.
- Commit steps are optional unless the user asks to commit while executing.
