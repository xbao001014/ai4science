# Design: Weekly Ops Memory (Soft Dedup + Persist)

**Date:** 2026-07-15  
**Status:** Approved (awaiting implementation plan)  
**Scope:** Persist weekly operating artifacts (gap debate, research proposals, hotspot linkage) and soft-steer subsequent gap debates away from near-duplicate directions. Primary usage is **focused** runs; full-corpus runs use a separate `__all__` memory lane.

## Problem

Operating cadence is about **once every 1–2 weeks**: DB incremental update → weekly hotspot → gap debate → optional research-proposal generation. Gap debate is largely **stateless** across sessions:

- Streamlit keeps results only in `st.session_state`.
- CLI overwrites `output/gap_debate_report.md` (and similar) without structured history.
- `feasibility_assessments` stores feasibility scores, not debate gap inventories.
- Weekly hotspots already persist (`weekly_hotspot_runs` / `weekly_hotspot_snapshots`) with WoW comparison, but debate does not read that history as “what we already recommended.”

Result: biweekly gap reports tend to **repeat similar blanks** for the same focus.

## Goals

- Form a **weekly ops memory**: store generated gap reports, gap items, proposals, and link to hotspot week when available.
- On later runs under the same focus, **soft-avoid** recently covered directions (prompt guidance + optional `revisited` labeling), not hard-drop.
- Default lookback: **last 4 runs** per `focus_key` (≈ 1–2 months at current cadence).
- UI sidebar toggles: **use memory** (inject) and **persist this run** (write).
- Single SQLite home: `fulltext_workflow/data/kg_fulltext.db`, aligned with existing hotspot tables.

## Non-goals

- Embedding / vector semantic search for dedup (v1 uses token fingerprints + Jaccard).
- Hard filtering that silently removes overlapping gaps.
- Mandatory backfill of historical Markdown into `ops_*` tables.
- Changes to PubMed fetch / extract / build pipeline beyond optional `init` schema migration.
- Replacing or duplicating `weekly_hotspot_snapshots` content.

## Approach (chosen)

**SQLite ops memory + prompt soft-steer** (Approach 2 from brainstorming).

Rejected:

1. Filesystem-only archive — weak query/focus isolation; dual-track vs hotspot DB.  
2. Embedding layer — overkill for 1–2 week cadence and small history windows.

## Decisions (from brainstorming)

| Topic | Choice |
|-------|--------|
| Focus scoping | Mix of focused + full-corpus; **focused more common** → memory primarily keyed by `focus_key`; `__all__` lane for no-focus runs |
| Dedup policy | **A Soft avoid** — inject prior titles; allow revisit with explicit distinction / `revisited` |
| What to store | **C Full weekly kit** — gap debate + proposals + hotspot week link |
| Lookback | **A Last 4 runs** per focus_key |
| Implementation | SQLite tables + `analysis/ops_memory.py` API |
| UI | Dual toggles: use memory / persist run |

## Data model

New tables in `kg_fulltext.db` (created via `init_db` / schema migrate).

### `ops_runs`

One weekly-ops session (or one successful artifact-producing run).

| Column | Type | Notes |
|--------|------|--------|
| `run_id` | INTEGER PK | Auto |
| `week_id` | TEXT | ISO week, e.g. `2026-W29`, same helper as hotspot |
| `focus_raw` | TEXT | User input as typed |
| `focus_key` | TEXT NOT NULL | Normalized; empty focus → `__all__` |
| `source` | TEXT | `gap_ui` \| `gap-debate` \| `idea-pipeline` \| `hotspot` |
| `started_at` | TIMESTAMP | |
| `finished_at` | TIMESTAMP | Set on successful complete persist |
| `hotspot_week_id` | TEXT | Optional FK-like to `weekly_hotspot_runs.week_id` |
| `gap_report_path` | TEXT | Markdown under `output/` |
| `proposal_report_path` | TEXT | Optional combined proposal path |
| `notes` | TEXT | Optional |

Indexes: `(focus_key, finished_at DESC)`, `(week_id)`.

### `ops_gap_items`

Parsed gaps from a run’s debate report.

| Column | Type | Notes |
|--------|------|--------|
| `id` | INTEGER PK | |
| `run_id` | INTEGER FK → ops_runs | |
| `rank_pos` | INTEGER | Order in report |
| `title` | TEXT | |
| `research_question` | TEXT | Optional extract |
| `fingerprint` | TEXT | Stable short hash / normalized token key |
| `section_md` | TEXT | Section body; truncate at configurable cap (default **8192** chars) |
| `status` | TEXT | `reported` \| `revisited` (post-run overlap tag optional) |

Index: `(run_id)`, `(fingerprint)`.

### `ops_proposals`

| Column | Type | Notes |
|--------|------|--------|
| `id` | INTEGER PK | |
| `run_id` | INTEGER FK | |
| `gap_item_id` | INTEGER FK nullable | Link when title match known |
| `proposal_path` | TEXT | Prefer path over huge blobs when file exists |
| `proposal_md` | TEXT | Inline if no file / short |
| `feasibility_score` | REAL | If assessed |
| `status` | TEXT | Feasibility / pipeline status if any |

## Fingerprint & soft overlap

1. Normalize title: lowercase, strip punctuation, collapse whitespace.  
2. Optional: expand known disease tokens via shared synonym helpers when available (same spirit as disease-synonyms work; if module not ready, skip without blocking).  
3. Sort unique tokens → join → SHA1 (or blake2) truncated hex as `fingerprint`.  
4. Soft match: token-set **Jaccard** between candidate title and stored title/fingerprint tokens; default threshold **0.55** (`OPS_MEMORY_JACCARD_THRESHOLD`).  
5. Soft avoid **only** surfaces high-overlap items in the memory block and may set `status=revisited` after persist — **never** auto-delete gaps from the final report.

## Module API (`analysis/ops_memory.py`)

Suggested surface (names may adjust slightly in implementation):

- `normalize_focus_key(focus: str | None) -> str`
- `fingerprint_gap_title(title: str) -> str`
- `jaccard_overlap(a: str, b: str) -> float`
- `create_run(...) -> run_id`
- `finalize_run(run_id, *, gap_report_path=..., hotspot_week_id=...)`
- `persist_gaps_from_report(run_id, report_text) -> list[item]` — uses `parse_gap_titles` / `parse_gap_sections`
- `persist_proposal(run_id, ..., gap_item_id=None)`
- `link_hotspot(run_id | week_id+focus, hotspot_week_id)`
- `load_recent_gaps(focus_key, limit_runs=4) -> MemoryBundle` (runs + titles + week_ids)
- `format_memory_prompt_block(bundle) -> str`
- `tag_revisited_against_memory(items, bundle, threshold) -> updated statuses`

Agents and UI call this module; they do not embed raw SQL.

## Write hooks

| Entry | Persist behavior |
|-------|------------------|
| Gap debate complete (`gap_ui`, `main.py gap-debate`, `pipeline.run_idea_pipeline`) | If persist on: create run → parse gaps → write items → set `gap_report_path` / `finished_at` |
| Proposal complete (Proposal tab / idea-pipeline) | Same or sibling run keyed by `week_id` + `focus_key`; write `ops_proposals` |
| Hotspot “Save snapshot” | Set/link `hotspot_week_id` on matching week run, or create `source=hotspot` run with no gap items |
| Persist off | No `ops_*` writes for that invocation |
| Failed / interrupted debate | v1: do not write gap items; optional incomplete run omitted (prefer write only on success) |

Same week + same focus + multiple debates → **new `run_id` each time** (history preserved). Lookback counts the last 4 finished runs for that `focus_key`.

Migration: add tables in schema init; **no** required Markdown backfill.

## Soft avoid injection (gap debate)

When “use memory” is on and `load_recent_gaps` returns data:

| Role | Behavior |
|------|----------|
| Optimist | User prompt appends recent covered titles; prefer novel angles; if revisiting, different framing + declare previously covered |
| Skeptic | High overlap without stated distinction → `weak_evidence` / `duplicate_risk`-style note; **not** automatic `false_gaps` solely for overlap |
| Moderator | Prefer new directions; revisited items keep **Distinction from prior ops memory**; priority table may mark `new` / `revisited` |

Config:

- `OPS_MEMORY_ENABLED` default true (UI can override per run)  
- `OPS_MEMORY_LOOKBACK_RUNS` default 4  
- `OPS_MEMORY_JACCARD_THRESHOLD` default 0.55  
- `OPS_MEMORY_SECTION_MAX_CHARS` default 8192  

CLI flags (align with UI):

- `--no-ops-memory` — skip inject  
- `--no-ops-persist` — skip write  

## UI (`gap_ui` sidebar)

1. **使用周常记忆** (use ops memory) — default on → inject lookback.  
2. **本轮写入记忆** (persist this run) — default on → write on success.  
3. Optional read-only expander: memory summary for current focus (week_id + gap titles from last ≤4 runs).

Pass flags into `stream_gap_debate_agent(...)` / persist helpers.

## Testing

- Unit: `normalize_focus_key`, fingerprint stability, Jaccard above/below threshold, lookback returns at most 4 runs per focus and does not mix `__all__` with a disease focus.  
- Persist: round-trip report markdown → `ops_gap_items` titles.  
- Soft block: `format_memory_prompt_block` non-empty when seeded.  
- No LLM required for core tests (in-memory / temp SQLite).

## Files to touch (expected)

| File | Change |
|------|--------|
| `db/schema.py` | `ops_runs` / `ops_gap_items` / `ops_proposals` + migrate helpers |
| `analysis/ops_memory.py` | **New** — API above |
| `config.py` | Env knobs for enable / lookback / threshold / section cap |
| `gap_agent.py` | Load memory → inject prompts; optional post-tag |
| `gap_ui.py` | Sidebar toggles + summary; wire flags + persist on final |
| `pipeline.py` / `main.py` | Persist + CLI flags |
| `analysis/weekly_hotspot.py` or hotspot UI save path | Link `hotspot_week_id` |
| `tests/test_ops_memory.py` | **New** |
| `PIPELINE.md` or `gap_ui_guide.md` | Short note on weekly memory (light) |

## Acceptance criteria

1. Same focus, second debate with memory on: prompt/context includes prior titles; report trends toward new angles or explicit revisited distinction.  
2. Memory toggle off: no memory inject; behavior matches pre-feature debate prompting aside from unrelated changes.  
3. Persist toggle off: successful debate does **not** insert `ops_runs` / gap items.  
4. Hotspot save links `hotspot_week_id` for the week when a run exists or creates a hotspot-only run.  
5. Proposal persist links to gap item when title resolves.  
6. Unit tests green for fingerprint, lookback=4, focus isolation.

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Soft avoid ignored by LLM | Clear structured memory block; Skeptic/Moderator reminders; post-run `revisited` tags for UI honesty |
| Jaccard false positives/negatives | Tunable threshold; titles only in v1; document limit |
| DB growth from `section_md` | Cap chars; prefer report paths for full text |
| Focus key drift (`NPC` vs `nasopharyngeal carcinoma`) | Normalize + optional synonym expand when disease_synonyms lands; document that unmatched aliases split lanes |

## Open follow-ups (deferred)

- Embedding-based semantic dedup.  
- Hard-exclude mode.  
- Markdown backfill CLI.  
- Cross-focus “global novelty” board.

## Implementation notes

- Prefer TDD for `ops_memory` pure functions and SQLite helpers.  
- Do not commit secrets or `*.db` artifacts.  
- Spec approval does not imply git commit of this file unless the user requests it.
