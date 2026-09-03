# Ops Upgrade Re-extract Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Gap UI 运维 weekly form opt in to abstract→fulltext upgrade re-extract (default off) via extract CLI flags, so weekly runs stay fast unless the user explicitly enables upgrades.

**Architecture:** Add `upgrade_abstract_fulltext` to weekly job params (default false). `build_weekly_argv("extract")` appends `--no-upgrade-reextract` or `--upgrade-reextract`. `cmd_extract` sets `config.FULLTEXT_UPGRADE_REEXTRACT` before `run_extraction`. Ops checkbox wires the param.

**Tech Stack:** Python 3, argparse, Streamlit ops panel, existing `ops_jobs` runner, pytest.

**Spec:** `docs/superpowers/specs/2026-08-05-ops-upgrade-reextract-toggle-design.md`

## Global Constraints

- Ops checkbox **default False** (off).
- Missing param in old `status.json` → treat as False when building argv.
- CLI extract with **neither** flag → leave config/env unchanged (default true).
- `--upgrade-reextract` and `--no-upgrade-reextract` are mutually exclusive.
- No upgrade count UI; no new weekly step; no global env default change.
- Run pytest from `fulltext_workflow/`.
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the tree dirty and note the suggested commit message.
- Do not commit `data/`, `raw/`, `output/`, or secrets.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/analysis/ops_jobs.py` | Param on create/start; extract argv flags |
| `fulltext_workflow/main.py` | extract CLI flags → config |
| `fulltext_workflow/ops_panel.py` | Checkbox default off |
| `fulltext_workflow/tests/test_ops_jobs.py` | argv + param persistence tests |
| `fulltext_workflow/SCRIPTS.md` | CLI flag note |
| `fulltext_workflow/gap_ui_guide.md` | Ops checkbox note |

---

### Task 1: Job params, argv, extract CLI

**Files:**
- Modify: `fulltext_workflow/analysis/ops_jobs.py`
- Modify: `fulltext_workflow/main.py`
- Modify: `fulltext_workflow/tests/test_ops_jobs.py`

**Interfaces:**
- Consumes: existing `create_weekly_job` / `start_weekly_job` / `build_weekly_argv` / `cmd_extract`
- Produces:
  - `create_weekly_job(..., upgrade_abstract_fulltext: bool = False)` stores param
  - `start_weekly_job(..., upgrade_abstract_fulltext: bool = False)` forwards it
  - `build_weekly_argv("extract", params)` ends with `--no-upgrade-reextract` if not `params.get("upgrade_abstract_fulltext")`, else `--upgrade-reextract`
  - `extract` argparse: `--upgrade-reextract`, `--no-upgrade-reextract`; `cmd_extract` sets config accordingly

- [ ] **Step 1: Write the failing tests**

Append to `fulltext_workflow/tests/test_ops_jobs.py`:

```python
def test_build_weekly_argv_upgrade_flags():
    base = {"since_days": 14, "extract_limit": 0, "skip_enrich": False}
    off = oj.build_weekly_argv("extract", {**base, "upgrade_abstract_fulltext": False})
    assert off == [
        "extract",
        "--limit",
        "0",
        "--core-only",
        "--no-upgrade-reextract",
    ]
    on = oj.build_weekly_argv("extract", {**base, "upgrade_abstract_fulltext": True})
    assert on == [
        "extract",
        "--limit",
        "0",
        "--core-only",
        "--upgrade-reextract",
    ]
    # Missing key → off (fast weekly default)
    missing = oj.build_weekly_argv("extract", base)
    assert missing[-1] == "--no-upgrade-reextract"


def test_create_weekly_job_stores_upgrade_flag(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job(upgrade_abstract_fulltext=True)
    assert job["params"]["upgrade_abstract_fulltext"] is True
    job2 = oj.create_weekly_job()
    assert job2["params"]["upgrade_abstract_fulltext"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_ops_jobs.py::test_build_weekly_argv_upgrade_flags tests/test_ops_jobs.py::test_create_weekly_job_stores_upgrade_flag -v
```

Expected: FAIL (wrong argv / missing param).

- [ ] **Step 3: Implement ops_jobs changes**

Update signatures and body:

```python
def create_weekly_job(
    *,
    since_days: int = 14,
    extract_limit: int = 0,
    skip_enrich: bool = False,
    upgrade_abstract_fulltext: bool = False,
) -> dict:
    ...
        "params": {
            "since_days": since_days,
            "extract_limit": extract_limit,
            "skip_enrich": skip_enrich,
            "upgrade_abstract_fulltext": upgrade_abstract_fulltext,
        },
```

```python
    if step_id == "extract":
        argv = [
            "extract",
            "--limit",
            str(params["extract_limit"]),
            "--core-only",
        ]
        if params.get("upgrade_abstract_fulltext"):
            argv.append("--upgrade-reextract")
        else:
            argv.append("--no-upgrade-reextract")
        return argv
```

```python
def start_weekly_job(
    *,
    since_days: int = 14,
    extract_limit: int = 0,
    skip_enrich: bool = False,
    upgrade_abstract_fulltext: bool = False,
    spawn_fn: Callable[[str], int] | None = None,
) -> dict:
    ...
    job = create_weekly_job(
        since_days=since_days,
        extract_limit=extract_limit,
        skip_enrich=skip_enrich,
        upgrade_abstract_fulltext=upgrade_abstract_fulltext,
    )
```

If `__main__` runner CLI creates jobs, leave it unless it already exposes weekly params (do not invent new runner flags unless already present for skip_enrich).

- [ ] **Step 4: Implement extract CLI flags in `main.py`**

In `cmd_extract`, after core-only / workers config tweaks and before `run_extraction`:

```python
    upgrade = getattr(args, "upgrade_reextract", False)
    no_upgrade = getattr(args, "no_upgrade_reextract", False)
    if upgrade and no_upgrade:
        raise SystemExit("Use only one of --upgrade-reextract / --no-upgrade-reextract")
    if upgrade:
        config.FULLTEXT_UPGRADE_REEXTRACT = True
    elif no_upgrade:
        config.FULLTEXT_UPGRADE_REEXTRACT = False
```

On `p_ext`:

```python
    p_ext.add_argument(
        "--upgrade-reextract",
        action="store_true",
        help="Force enable abstract→fulltext upgrade clear+reextract",
    )
    p_ext.add_argument(
        "--no-upgrade-reextract",
        action="store_true",
        help="Disable abstract→fulltext upgrade clear+reextract for this run",
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_ops_jobs.py::test_build_weekly_argv_upgrade_flags tests/test_ops_jobs.py::test_create_weekly_job_stores_upgrade_flag tests/test_ops_jobs.py::test_build_weekly_argv_fetch_fulltext_unchanged -v
```

Expected: PASS.

- [ ] **Step 6: Commit (only if user asked / plan-exec includes commits)**

```bash
git add fulltext_workflow/analysis/ops_jobs.py fulltext_workflow/main.py fulltext_workflow/tests/test_ops_jobs.py
git commit -m "feat: pass upgrade-reextract flags from weekly ops job params"
```

---

### Task 2: Ops UI checkbox + docs

**Files:**
- Modify: `fulltext_workflow/ops_panel.py`
- Modify: `fulltext_workflow/SCRIPTS.md`
- Modify: `fulltext_workflow/gap_ui_guide.md`

**Interfaces:**
- Consumes: `start_weekly_job(..., upgrade_abstract_fulltext=...)`
- Produces: checkbox default False; docs mention default off

- [ ] **Step 1: Add checkbox in `ops_panel.py`**

Beside SkipEnrich (new row or same columns — prefer a second checkbox under the three-column row or a fourth control):

```python
    upgrade_abstract = st.checkbox(
        "升级先前仅摘要文献（补全文后完整重抽）",
        value=False,
        key="ops_upgrade_abstract_fulltext",
        help="开启后 extract 会对曾摘要抽取且现已有全文的论文 clear 并重抽，可能很慢。默认关闭以加快周常。",
    )
```

Pass into start:

```python
            job = start_weekly_job(
                since_days=int(since_days),
                extract_limit=int(extract_limit),
                skip_enrich=bool(skip_enrich),
                upgrade_abstract_fulltext=bool(upgrade_abstract),
            )
```

- [ ] **Step 2: Update docs**

`gap_ui_guide.md` table row for weekly params — add the checkbox (default off).

`SCRIPTS.md` near extract:

```powershell
& $py main.py extract --limit 0 --core-only --no-upgrade-reextract
& $py main.py extract --limit 0 --core-only --upgrade-reextract
```

- [ ] **Step 3: Run ops_jobs tests once more**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_ops_jobs.py -v --tb=line -q
```

Expected: PASS (no UI test required).

- [ ] **Step 4: Commit (only if user asked / plan-exec includes commits)**

```bash
git add fulltext_workflow/ops_panel.py fulltext_workflow/SCRIPTS.md fulltext_workflow/gap_ui_guide.md
git commit -m "feat: ops weekly checkbox for abstract fulltext upgrade re-extract"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Checkbox default off | Task 2 |
| Job param `upgrade_abstract_fulltext` | Task 1 |
| extract argv flags | Task 1 |
| Mutual exclusion / config set in cmd_extract | Task 1 |
| Missing param → no-upgrade | Task 1 |
| CLI neither flag → env default | Task 1 |
| Docs | Task 2 |

## Out of scope

- Upgrade caps, env default flip, new weekly steps, Streamlit widget unit tests
