"""SQLite schema and CRUD for the full-text workflow sandbox."""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Callable, Generator

import config

# Prefer config.DB_PATH at call time so tests can re-point the database after import.
DB_PATH = config.DB_PATH


def _db_path() -> str:
    return config.DB_PATH or DB_PATH


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    _ensure_dir()
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS journals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    abbr            TEXT,
    issn            TEXT UNIQUE,
    impact_factor   REAL,
    if_year         INTEGER,
    quartile        TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS papers (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    pmid                    TEXT UNIQUE,
    doi                     TEXT,
    pmc_id                  TEXT,
    s2id                    TEXT,
    title                   TEXT NOT NULL,
    abstract                TEXT,
    pub_date                TEXT,
    year                    INTEGER,
    date_precision          TEXT,
    journal_id              INTEGER REFERENCES journals(id),
    journal_name            TEXT,
    journal_abbr            TEXT,
    issn                    TEXT,
    study_type              TEXT,
    pub_types               TEXT,
    mesh_terms              TEXT,
    keywords                TEXT,
    source_queries          TEXT,
    citation_count          INTEGER DEFAULT 0,
    open_access             INTEGER DEFAULT 0,
    citation_source         TEXT,
    full_text_status        TEXT DEFAULT 'pending',
    full_text_fetched_at    TIMESTAMP,
    fulltext_pdf_attempts   INTEGER DEFAULT 0,
    extraction_done         INTEGER DEFAULT 0,
    reconcile_status        TEXT DEFAULT 'pending',
    reconcile_at            TIMESTAMP,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_papers_pmid ON papers(pmid);
CREATE INDEX IF NOT EXISTS idx_papers_pmc ON papers(pmc_id);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_papers_ft ON papers(full_text_status);

CREATE TABLE IF NOT EXISTS authors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    affiliation TEXT,
    orcid       TEXT,
    UNIQUE(name, affiliation)
);

CREATE TABLE IF NOT EXISTS paper_authors (
    paper_id     INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    author_id    INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    author_order INTEGER,
    PRIMARY KEY (paper_id, author_id)
);

CREATE TABLE IF NOT EXISTS document_sections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id        INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    section_type    TEXT NOT NULL,
    title           TEXT,
    content         TEXT NOT NULL,
    order_idx       INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sections_paper ON document_sections(paper_id);
CREATE INDEX IF NOT EXISTS idx_sections_type ON document_sections(section_type);

CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    cui         TEXT,
    aliases     TEXT,
    access_class TEXT,
    method_role TEXT,
    UNIQUE(name, type)
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

CREATE TABLE IF NOT EXISTS relations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type            TEXT NOT NULL,
    subject_id              INTEGER NOT NULL,
    relation                TEXT NOT NULL,
    object_type             TEXT NOT NULL,
    object_id               INTEGER NOT NULL,
    metric_value            TEXT,
    source_pmid               TEXT,
    confidence              REAL DEFAULT 1.0,
    evidence_section        TEXT,
    evidence_quote          TEXT,
    extraction_granularity  TEXT DEFAULT 'abstract',
    polarity                TEXT DEFAULT 'asserted',
    status                  TEXT DEFAULT 'active',
    superseded_by           INTEGER,
    extraction_pass         TEXT DEFAULT 'section',
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_relations_subj ON relations(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_obj ON relations(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_relations_rel ON relations(relation);
CREATE INDEX IF NOT EXISTS idx_relations_gran ON relations(extraction_granularity);

-- One relation can have multiple independent evidence spans.  Keep these rows
-- separate instead of relying on the legacy semicolon-joined evidence_quote.
CREATE TABLE IF NOT EXISTS relation_evidence (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    relation_id             INTEGER NOT NULL REFERENCES relations(id) ON DELETE CASCADE,
    source_pmid             TEXT,
    evidence_section        TEXT,
    evidence_quote          TEXT NOT NULL,
    evidence_start          INTEGER,
    evidence_end            INTEGER,
    evidence_status         TEXT DEFAULT 'unverified',
    support_status          TEXT DEFAULT 'unchecked',
    support_reason          TEXT,
    extraction_granularity  TEXT DEFAULT 'abstract',
    extraction_pass         TEXT DEFAULT 'section',
    evidence_sha256         TEXT NOT NULL,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(relation_id, evidence_sha256, evidence_start, evidence_end)
);
CREATE INDEX IF NOT EXISTS idx_relation_evidence_relation ON relation_evidence(relation_id);
CREATE INDEX IF NOT EXISTS idx_relation_evidence_pmid ON relation_evidence(source_pmid);
CREATE INDEX IF NOT EXISTS idx_relation_evidence_support ON relation_evidence(support_status);

-- Section-level observability for the complete extraction path. This records
-- silent truncation, model empties and policy/grounding losses without storing
-- the source text or any API credential.
CREATE TABLE IF NOT EXISTS extraction_audits (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id                INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    source_pmid             TEXT,
    section_type            TEXT NOT NULL,
    section_title           TEXT,
    extraction_granularity  TEXT DEFAULT 'abstract',
    source_chars            INTEGER DEFAULT 0,
    sent_chars              INTEGER DEFAULT 0,
    truncated               INTEGER DEFAULT 0,
    parsed                  INTEGER DEFAULT 0,
    postprocessed           INTEGER DEFAULT 0,
    retained                INTEGER DEFAULT 0,
    outcome                 TEXT NOT NULL,
    empty_reason            TEXT,
    recall_check_reason     TEXT,
    rejected_json           TEXT DEFAULT '[]',
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_extraction_audits_pmid ON extraction_audits(source_pmid);
CREATE INDEX IF NOT EXISTS idx_extraction_audits_outcome ON extraction_audits(outcome);

CREATE TABLE IF NOT EXISTS pathology_landscape (
    disease_id      TEXT PRIMARY KEY,
    payload_json    TEXT NOT NULL,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feasibility_assessments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    gap_title       TEXT,
    hypothesis_id   TEXT,
    hypothesis_json TEXT,
    feasibility_score REAL,
    status          TEXT,
    assessment_json TEXT,
    assessed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_feas_gap ON feasibility_assessments(gap_title);

CREATE TABLE IF NOT EXISTS public_dataset_assessments (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    gap_title               TEXT,
    keyword                 TEXT,
    public_coverage_score   REAL,
    status                  TEXT,
    assessment_json         TEXT,
    assessed_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pda_gap ON public_dataset_assessments(gap_title);

CREATE TABLE IF NOT EXISTS limitation_temporal (
    limitation_id       INTEGER PRIMARY KEY REFERENCES entities(id),
    limitation_name     TEXT NOT NULL,
    first_year          INTEGER,
    last_year           INTEGER,
    paper_cnt           INTEGER,
    asserted_cnt        INTEGER,
    hypothesized_cnt    INTEGER,
    early_cnt           INTEGER,
    recent_cnt          INTEGER,
    recent_ratio        REAL,
    temporal_status     TEXT,
    avg_cite            REAL,
    avg_cite_per_year   REAL,
    impact_tier         TEXT,
    computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lt_status ON limitation_temporal(temporal_status);
CREATE INDEX IF NOT EXISTS idx_lt_last_year ON limitation_temporal(last_year);

CREATE TABLE IF NOT EXISTS limitation_resolution_signals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    limitation_id       INTEGER NOT NULL REFERENCES entities(id),
    signal_type         TEXT NOT NULL,
    anchor_pmid         TEXT,
    followup_pmid       TEXT,
    anchor_year         INTEGER,
    followup_year       INTEGER,
    shared_entities     TEXT,
    confidence          REAL DEFAULT 0.5,
    computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lrs_limitation ON limitation_resolution_signals(limitation_id);
CREATE INDEX IF NOT EXISTS idx_lrs_signal ON limitation_resolution_signals(signal_type);

CREATE TABLE IF NOT EXISTS weekly_hotspot_runs (
    week_id             TEXT PRIMARY KEY,
    snapshot_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    window_days         INTEGER NOT NULL,
    prior_window_days   INTEGER NOT NULL,
    papers_ingested     INTEGER DEFAULT 0,
    report_path         TEXT
);

CREATE TABLE IF NOT EXISTS weekly_hotspot_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id             TEXT NOT NULL,
    board               TEXT NOT NULL,
    item_key            TEXT NOT NULL,
    entity_type         TEXT,
    rank_pos            INTEGER,
    recent_cnt          INTEGER,
    prior_cnt           INTEGER,
    velocity            REAL,
    emerging_score      REAL,
    avg_cite            REAL,
    avg_if              REAL,
    gap_phase           TEXT,
    top_pmids           TEXT,
    UNIQUE(week_id, board, item_key)
);
CREATE INDEX IF NOT EXISTS idx_whs_week_board ON weekly_hotspot_snapshots(week_id, board);
CREATE INDEX IF NOT EXISTS idx_whs_board_score ON weekly_hotspot_snapshots(board, emerging_score);

CREATE TABLE IF NOT EXISTS ops_runs (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id             TEXT,
    focus_raw           TEXT,
    focus_key           TEXT NOT NULL,
    source              TEXT,
    started_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at         TIMESTAMP,
    hotspot_week_id     TEXT,
    gap_report_path     TEXT,
    proposal_report_path TEXT,
    validation_status   TEXT,
    debate_session_id   TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_ops_runs_focus_finished
    ON ops_runs(focus_key, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_runs_week ON ops_runs(week_id);

CREATE TABLE IF NOT EXISTS ops_gap_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES ops_runs(run_id),
    rank_pos            INTEGER,
    title               TEXT NOT NULL,
    research_question   TEXT,
    fingerprint         TEXT,
    section_md          TEXT,
    status              TEXT DEFAULT 'reported'
);
CREATE INDEX IF NOT EXISTS idx_ops_gap_run ON ops_gap_items(run_id);
CREATE INDEX IF NOT EXISTS idx_ops_gap_fp ON ops_gap_items(fingerprint);

CREATE TABLE IF NOT EXISTS ops_proposals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES ops_runs(run_id),
    gap_item_id         INTEGER REFERENCES ops_gap_items(id),
    proposal_path       TEXT,
    proposal_md         TEXT,
    feasibility_score   REAL,
    critic_score        REAL,
    status              TEXT,
    target_difficulty   TEXT,
    assessed_difficulty TEXT,
    difficulty_delta    INTEGER,
    difficulty_breakdown_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_ops_prop_run ON ops_proposals(run_id);

CREATE TABLE IF NOT EXISTS debate_sessions (
    session_id          TEXT PRIMARY KEY,
    focus_raw           TEXT,
    focus_key           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'running',
    current_round       INTEGER DEFAULT 0,
    next_role           TEXT,
    max_rounds          INTEGER NOT NULL,
    top_n               INTEGER NOT NULL,
    validation_status   TEXT,
    final_report        TEXT,
    state_json          TEXT NOT NULL DEFAULT '{}',
    model               TEXT,
    prompt_version      TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_debate_sessions_focus_updated
    ON debate_sessions(focus_key, updated_at DESC);

CREATE TABLE IF NOT EXISTS debate_turns (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL REFERENCES debate_sessions(session_id) ON DELETE CASCADE,
    round_no            INTEGER NOT NULL,
    role                TEXT NOT NULL,
    input_text          TEXT,
    output_text         TEXT,
    handoff_json        TEXT,
    status              TEXT NOT NULL DEFAULT 'completed',
    started_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP,
    UNIQUE(session_id, round_no, role)
);
CREATE INDEX IF NOT EXISTS idx_debate_turns_session_round
    ON debate_turns(session_id, round_no, role);

CREATE TABLE IF NOT EXISTS debate_tool_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL REFERENCES debate_sessions(session_id) ON DELETE CASCADE,
    round_no            INTEGER NOT NULL,
    role                TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    tool_name           TEXT,
    call_id             TEXT,
    args_json           TEXT,
    result_json         TEXT,
    error_text          TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_debate_tool_events_session_round
    ON debate_tool_events(session_id, round_no, role, id);

CREATE TABLE IF NOT EXISTS debate_candidates (
    session_id          TEXT NOT NULL REFERENCES debate_sessions(session_id) ON DELETE CASCADE,
    candidate_id        TEXT NOT NULL,
    title               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'proposed',
    first_round         INTEGER NOT NULL,
    last_round          INTEGER NOT NULL,
    metadata_json       TEXT,
    PRIMARY KEY(session_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_debate_candidates_session_status
    ON debate_candidates(session_id, status);

CREATE TABLE IF NOT EXISTS idea_sessions (
    session_id          TEXT PRIMARY KEY,
    debate_session_id   TEXT REFERENCES debate_sessions(session_id),
    gap_text            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'running',
    current_round       INTEGER DEFAULT 0,
    next_role           TEXT DEFAULT 'generator',
    max_rounds          INTEGER NOT NULL,
    state_json          TEXT NOT NULL DEFAULT '{}',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_idea_sessions_debate_updated
    ON idea_sessions(debate_session_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS idea_turns (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL REFERENCES idea_sessions(session_id) ON DELETE CASCADE,
    round_no            INTEGER NOT NULL,
    role                TEXT NOT NULL,
    output_text         TEXT,
    state_json          TEXT NOT NULL DEFAULT '{}',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, round_no, role)
);
CREATE INDEX IF NOT EXISTS idx_idea_turns_session_round
    ON idea_turns(session_id, round_no, role);

CREATE TABLE IF NOT EXISTS paper_entity_bindings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pmid         TEXT NOT NULL,
    method_entity_id    INTEGER,
    disease_entity_id   INTEGER,
    dataset_entity_id   INTEGER,
    confidence          REAL DEFAULT 1.0,
    evidence_quote      TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_peb_pmid ON paper_entity_bindings(source_pmid);

CREATE TABLE IF NOT EXISTS paper_improvement_suggestions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pmid           TEXT NOT NULL,
    limitation_entity_id  INTEGER,
    action_type           TEXT NOT NULL,
    suggestion            TEXT NOT NULL,
    evidence_quote        TEXT,
    evidence_section      TEXT,
    grounding             TEXT NOT NULL,
    confidence            REAL DEFAULT 0.5,
    status                TEXT DEFAULT 'active',
    extraction_pass       TEXT DEFAULT 'fulltext_reconcile',
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pis_pmid ON paper_improvement_suggestions(source_pmid);
CREATE INDEX IF NOT EXISTS idx_pis_action ON paper_improvement_suggestions(action_type);
CREATE INDEX IF NOT EXISTS idx_pis_lim ON paper_improvement_suggestions(limitation_entity_id);
CREATE INDEX IF NOT EXISTS idx_pis_status ON paper_improvement_suggestions(status);

-- Phase A external embedding foundation. Raw input text and credentials are
-- deliberately not persisted in these tables.
CREATE TABLE IF NOT EXISTS embedding_cache (
    input_sha256       TEXT NOT NULL,
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    dimensions         INTEGER NOT NULL,
    vector_blob        BLOB NOT NULL,
    vector_norm        REAL NOT NULL,
    input_chars        INTEGER NOT NULL,
    prompt_tokens      INTEGER,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (input_sha256, provider, model, dimensions),
    CHECK (dimensions > 0),
    CHECK (length(vector_blob) = dimensions * 4)
);
CREATE INDEX IF NOT EXISTS idx_embedding_cache_model
    ON embedding_cache(provider, model, dimensions);

CREATE TABLE IF NOT EXISTS embedding_jobs (
    job_id              TEXT PRIMARY KEY,
    job_type            TEXT NOT NULL,
    status              TEXT NOT NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    dimensions          INTEGER NOT NULL,
    scope_json          TEXT NOT NULL DEFAULT '{}',
    planned_items       INTEGER DEFAULT 0,
    cache_hits          INTEGER DEFAULT 0,
    requested_items     INTEGER DEFAULT 0,
    succeeded_items     INTEGER DEFAULT 0,
    failed_items        INTEGER DEFAULT 0,
    estimated_tokens    INTEGER DEFAULT 0,
    actual_tokens       INTEGER DEFAULT 0,
    estimated_cost_cny  REAL DEFAULT 0,
    error_summary       TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_embedding_jobs_status
    ON embedding_jobs(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS embedding_job_items (
    job_id              TEXT NOT NULL REFERENCES embedding_jobs(job_id) ON DELETE CASCADE,
    item_type           TEXT NOT NULL,
    item_id             TEXT NOT NULL,
    input_sha256        TEXT NOT NULL,
    context_quality     TEXT NOT NULL,
    input_chars         INTEGER NOT NULL,
    estimated_tokens    INTEGER NOT NULL,
    status              TEXT NOT NULL,
    cache_hit           INTEGER DEFAULT 0,
    attempts            INTEGER DEFAULT 0,
    error_code          TEXT,
    error_summary       TEXT,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (job_id, item_type, item_id)
);
CREATE INDEX IF NOT EXISTS idx_embedding_job_items_status
    ON embedding_job_items(job_id, status);
CREATE INDEX IF NOT EXISTS idx_embedding_job_items_hash
    ON embedding_job_items(input_sha256);

CREATE TABLE IF NOT EXISTS embedding_batch_jobs (
    job_id              TEXT PRIMARY KEY REFERENCES embedding_jobs(job_id) ON DELETE CASCADE,
    remote_batch_id     TEXT UNIQUE,
    input_file_id       TEXT,
    output_file_id      TEXT,
    error_file_id       TEXT,
    remote_status       TEXT,
    submitted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_polled_at      TIMESTAMP,
    ingested_at         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS method_taxonomy_families (
    family_id           TEXT NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    display_name_zh     TEXT NOT NULL,
    display_name_en     TEXT NOT NULL,
    description         TEXT NOT NULL,
    seed_methods_json   TEXT NOT NULL DEFAULT '[]',
    negative_examples_json TEXT NOT NULL DEFAULT '[]',
    parent_family_id    TEXT,
    active              INTEGER NOT NULL DEFAULT 1,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (family_id, taxonomy_version)
);
CREATE INDEX IF NOT EXISTS idx_method_taxonomy_active
    ON method_taxonomy_families(taxonomy_version, active);

CREATE TABLE IF NOT EXISTS method_family_assignments (
    method_entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    family_id           TEXT NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    candidate_rank      INTEGER NOT NULL DEFAULT 1,
    is_primary          INTEGER NOT NULL DEFAULT 0,
    confidence          REAL,
    similarity          REAL NOT NULL,
    margin              REAL,
    source              TEXT NOT NULL,
    status              TEXT NOT NULL,
    input_sha256        TEXT NOT NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    dimensions          INTEGER NOT NULL,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (method_entity_id, family_id, taxonomy_version)
);
CREATE INDEX IF NOT EXISTS idx_method_family_status
    ON method_family_assignments(taxonomy_version, status, family_id);
CREATE INDEX IF NOT EXISTS idx_method_family_method
    ON method_family_assignments(method_entity_id, taxonomy_version, candidate_rank);

-- Phase C0 immutable expert Gold inputs. The source CSV is never rewritten;
-- normalized labels and the deterministic split are persisted as snapshots.
CREATE TABLE IF NOT EXISTS method_family_gold_sets (
    gold_set_id             TEXT PRIMARY KEY,
    taxonomy_version       TEXT NOT NULL,
    file_sha256            TEXT NOT NULL UNIQUE,
    source_filename        TEXT NOT NULL,
    byte_count             INTEGER NOT NULL,
    row_count              INTEGER NOT NULL,
    known_count            INTEGER NOT NULL,
    unknown_count          INTEGER NOT NULL,
    secondary_count        INTEGER NOT NULL,
    normalization_policy   TEXT NOT NULL,
    reviewer               TEXT NOT NULL,
    split_manifest_sha256  TEXT NOT NULL,
    calibration_count      INTEGER NOT NULL,
    holdout_count          INTEGER NOT NULL,
    created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (row_count = known_count + unknown_count),
    CHECK (row_count = calibration_count + holdout_count)
);

CREATE TABLE IF NOT EXISTS method_family_gold_labels (
    gold_set_id             TEXT NOT NULL REFERENCES method_family_gold_sets(gold_set_id),
    method_entity_id        INTEGER NOT NULL,
    source_row              INTEGER NOT NULL,
    method_name_snapshot    TEXT NOT NULL,
    method_role_snapshot    TEXT NOT NULL,
    paper_count_snapshot    INTEGER NOT NULL,
    first_year_snapshot     INTEGER,
    last_year_snapshot      INTEGER,
    raw_primary             TEXT NOT NULL,
    normalized_primary      TEXT NOT NULL,
    secondary_json          TEXT NOT NULL DEFAULT '[]',
    review_notes            TEXT NOT NULL DEFAULT '',
    suggested_primary       TEXT NOT NULL,
    top1_similarity         REAL NOT NULL,
    ranking_score           REAL NOT NULL,
    margin                  REAL NOT NULL,
    suggested_top3_json     TEXT NOT NULL,
    split                   TEXT NOT NULL,
    split_group             TEXT NOT NULL,
    PRIMARY KEY (gold_set_id, method_entity_id),
    CHECK (split IN ('calibration', 'holdout'))
);
CREATE INDEX IF NOT EXISTS idx_method_family_gold_split
    ON method_family_gold_labels(gold_set_id, split, normalized_primary);

CREATE TABLE IF NOT EXISTS method_family_calibrations (
    calibration_id                 TEXT PRIMARY KEY,
    gold_set_id                    TEXT NOT NULL REFERENCES method_family_gold_sets(gold_set_id),
    taxonomy_version               TEXT NOT NULL,
    split_manifest_sha256          TEXT NOT NULL,
    ruleset_version                TEXT NOT NULL,
    thresholds_json                TEXT NOT NULL,
    embedding_family_allowlist_json TEXT NOT NULL,
    blocked_families_json          TEXT NOT NULL,
    metrics_json                   TEXT NOT NULL,
    status                         TEXT NOT NULL,
    created_at                     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_method_family_calibration_gold
    ON method_family_calibrations(gold_set_id, created_at DESC);

CREATE TABLE IF NOT EXISTS method_family_rulesets (
    ruleset_id               TEXT PRIMARY KEY,
    gold_set_id              TEXT NOT NULL REFERENCES method_family_gold_sets(gold_set_id),
    taxonomy_version         TEXT NOT NULL,
    ruleset_version          TEXT NOT NULL,
    rules_sha256             TEXT NOT NULL,
    rules_json               TEXT NOT NULL,
    eligible_rule_ids_json   TEXT NOT NULL,
    metrics_json             TEXT NOT NULL,
    status                   TEXT NOT NULL,
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(gold_set_id, rules_sha256)
);

CREATE TABLE IF NOT EXISTS method_family_policy_previews (
    preview_id               TEXT PRIMARY KEY,
    gold_set_id              TEXT NOT NULL REFERENCES method_family_gold_sets(gold_set_id),
    calibration_id           TEXT NOT NULL REFERENCES method_family_calibrations(calibration_id),
    ruleset_id               TEXT NOT NULL REFERENCES method_family_rulesets(ruleset_id),
    graph_snapshot_sha256    TEXT NOT NULL,
    metrics_json             TEXT NOT NULL,
    status                   TEXT NOT NULL,
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(gold_set_id, calibration_id, ruleset_id, graph_snapshot_sha256)
);

CREATE TABLE IF NOT EXISTS method_family_review_queues (
    queue_id                 TEXT PRIMARY KEY,
    gold_set_id              TEXT NOT NULL REFERENCES method_family_gold_sets(gold_set_id),
    calibration_id           TEXT NOT NULL REFERENCES method_family_calibrations(calibration_id),
    ruleset_id               TEXT NOT NULL REFERENCES method_family_rulesets(ruleset_id),
    graph_snapshot_sha256    TEXT NOT NULL,
    target_paper_coverage    REAL NOT NULL,
    queue_sha256             TEXT NOT NULL,
    selection_json           TEXT NOT NULL,
    metrics_json             TEXT NOT NULL,
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(gold_set_id, calibration_id, ruleset_id, graph_snapshot_sha256,
           target_paper_coverage, queue_sha256)
);

CREATE TABLE IF NOT EXISTS method_family_gold_extensions (
    extension_id             TEXT PRIMARY KEY,
    queue_id                 TEXT NOT NULL REFERENCES method_family_review_queues(queue_id),
    parent_gold_set_id       TEXT NOT NULL REFERENCES method_family_gold_sets(gold_set_id),
    file_sha256              TEXT NOT NULL,
    source_filename          TEXT NOT NULL,
    label_snapshot_sha256    TEXT NOT NULL,
    rank_start               INTEGER NOT NULL,
    rank_end                 INTEGER NOT NULL,
    row_count                INTEGER NOT NULL,
    known_count              INTEGER NOT NULL,
    unknown_count            INTEGER NOT NULL,
    secondary_count          INTEGER NOT NULL,
    reviewer                 TEXT NOT NULL,
    normalization_policy     TEXT NOT NULL,
    metrics_json             TEXT NOT NULL,
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (rank_start >= 1 AND rank_end >= rank_start),
    CHECK (row_count = rank_end - rank_start + 1),
    CHECK (row_count = known_count + unknown_count),
    UNIQUE(queue_id, rank_start, rank_end, label_snapshot_sha256)
);

CREATE TABLE IF NOT EXISTS method_family_gold_extension_labels (
    extension_id             TEXT NOT NULL REFERENCES method_family_gold_extensions(extension_id),
    queue_id                 TEXT NOT NULL REFERENCES method_family_review_queues(queue_id),
    method_entity_id         INTEGER NOT NULL,
    queue_rank               INTEGER NOT NULL,
    method_name_snapshot     TEXT NOT NULL,
    raw_primary              TEXT NOT NULL,
    normalized_primary       TEXT NOT NULL,
    secondary_json           TEXT NOT NULL DEFAULT '[]',
    review_notes             TEXT NOT NULL DEFAULT '',
    paper_count_snapshot     INTEGER NOT NULL,
    uncovered_gain_snapshot  INTEGER NOT NULL,
    PRIMARY KEY (extension_id, method_entity_id),
    UNIQUE(queue_id, method_entity_id),
    UNIQUE(queue_id, queue_rank)
);

-- Independent blind evaluation sets. Model suggestions are frozen internally
-- but never exported to the reviewer-facing file.
CREATE TABLE IF NOT EXISTS method_family_blind_sets (
    blind_set_id              TEXT PRIMARY KEY,
    parent_gold_set_id        TEXT NOT NULL REFERENCES method_family_gold_sets(gold_set_id),
    taxonomy_version          TEXT NOT NULL,
    graph_snapshot_sha256     TEXT NOT NULL,
    training_snapshot_sha256  TEXT NOT NULL,
    sampling_version          TEXT NOT NULL,
    seed_sha256               TEXT NOT NULL,
    sample_snapshot_sha256    TEXT NOT NULL,
    export_sha256             TEXT NOT NULL,
    source_filename           TEXT NOT NULL,
    row_count                 INTEGER NOT NULL,
    created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_gold_set_id, graph_snapshot_sha256,
           training_snapshot_sha256, sampling_version, row_count)
);

CREATE TABLE IF NOT EXISTS method_family_blind_items (
    blind_set_id              TEXT NOT NULL REFERENCES method_family_blind_sets(blind_set_id),
    blind_rank                INTEGER NOT NULL,
    blind_item_id             TEXT NOT NULL,
    method_entity_id          INTEGER NOT NULL,
    method_name_snapshot      TEXT NOT NULL,
    method_role_snapshot      TEXT NOT NULL,
    paper_count_snapshot      INTEGER NOT NULL,
    first_year_snapshot       INTEGER,
    last_year_snapshot        INTEGER,
    context_quality_snapshot  TEXT NOT NULL,
    context_excerpt_snapshot  TEXT NOT NULL,
    stratum_snapshot          TEXT NOT NULL,
    hidden_suggested_primary  TEXT NOT NULL,
    hidden_top1_similarity    REAL NOT NULL,
    hidden_ranking_score      REAL NOT NULL,
    hidden_margin             REAL NOT NULL,
    hidden_top3_json          TEXT NOT NULL,
    PRIMARY KEY (blind_set_id, blind_rank),
    UNIQUE(blind_set_id, blind_item_id),
    UNIQUE(blind_set_id, method_entity_id)
);

CREATE TABLE IF NOT EXISTS method_family_blind_submissions (
    submission_id             TEXT PRIMARY KEY,
    blind_set_id              TEXT NOT NULL UNIQUE REFERENCES method_family_blind_sets(blind_set_id),
    file_sha256               TEXT NOT NULL,
    source_filename           TEXT NOT NULL,
    label_snapshot_sha256     TEXT NOT NULL,
    reviewer                  TEXT NOT NULL,
    row_count                 INTEGER NOT NULL,
    known_count               INTEGER NOT NULL,
    unknown_count             INTEGER NOT NULL,
    secondary_count           INTEGER NOT NULL,
    metrics_json              TEXT NOT NULL,
    created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (row_count = known_count + unknown_count)
);

CREATE TABLE IF NOT EXISTS method_family_blind_submission_labels (
    submission_id             TEXT NOT NULL REFERENCES method_family_blind_submissions(submission_id),
    blind_set_id              TEXT NOT NULL REFERENCES method_family_blind_sets(blind_set_id),
    blind_rank                INTEGER NOT NULL,
    blind_item_id             TEXT NOT NULL,
    method_entity_id          INTEGER NOT NULL,
    normalized_primary        TEXT NOT NULL,
    secondary_json            TEXT NOT NULL DEFAULT '[]',
    review_notes              TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (submission_id, blind_rank),
    UNIQUE(blind_set_id, method_entity_id)
);

CREATE TABLE IF NOT EXISTS method_family_models (
    model_id                  TEXT PRIMARY KEY,
    parent_gold_set_id        TEXT NOT NULL REFERENCES method_family_gold_sets(gold_set_id),
    ruleset_id                TEXT NOT NULL REFERENCES method_family_rulesets(ruleset_id),
    taxonomy_version          TEXT NOT NULL,
    training_snapshot_sha256  TEXT NOT NULL,
    algorithm_version         TEXT NOT NULL,
    provider                  TEXT NOT NULL,
    embedding_model           TEXT NOT NULL,
    dimensions                INTEGER NOT NULL,
    alpha                     REAL NOT NULL,
    score_threshold           REAL NOT NULL,
    margin_threshold          REAL NOT NULL,
    label_ids_json            TEXT NOT NULL,
    model_json                TEXT NOT NULL,
    metrics_json              TEXT NOT NULL,
    status                    TEXT NOT NULL,
    created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_gold_set_id, ruleset_id, training_snapshot_sha256,
           algorithm_version, provider, embedding_model, dimensions)
);

CREATE TABLE IF NOT EXISTS method_family_blind_evaluations (
    evaluation_id             TEXT PRIMARY KEY,
    model_id                  TEXT NOT NULL REFERENCES method_family_models(model_id),
    submission_id             TEXT NOT NULL REFERENCES method_family_blind_submissions(submission_id),
    metrics_json              TEXT NOT NULL,
    status                    TEXT NOT NULL,
    created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(model_id, submission_id)
);

-- A completed blind set may be retired and promoted into future training only.
-- Its methods remain excluded from later blind generations.
CREATE TABLE IF NOT EXISTS method_family_blind_promotions (
    promotion_id             TEXT PRIMARY KEY,
    evaluation_id            TEXT NOT NULL UNIQUE REFERENCES method_family_blind_evaluations(evaluation_id),
    submission_id            TEXT NOT NULL UNIQUE REFERENCES method_family_blind_submissions(submission_id),
    parent_gold_set_id        TEXT NOT NULL REFERENCES method_family_gold_sets(gold_set_id),
    label_snapshot_sha256     TEXT NOT NULL,
    promoted_by              TEXT NOT NULL,
    metrics_json             TEXT NOT NULL,
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS method_family_releases (
    release_id                TEXT PRIMARY KEY,
    model_id                  TEXT NOT NULL REFERENCES method_family_models(model_id),
    evaluation_id             TEXT NOT NULL REFERENCES method_family_blind_evaluations(evaluation_id),
    taxonomy_version          TEXT NOT NULL,
    graph_snapshot_sha256     TEXT NOT NULL,
    assignment_snapshot_sha256 TEXT NOT NULL,
    metrics_json              TEXT NOT NULL,
    status                    TEXT NOT NULL,
    created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(model_id, evaluation_id, graph_snapshot_sha256)
);

CREATE TABLE IF NOT EXISTS method_family_release_assignments (
    release_id                TEXT NOT NULL REFERENCES method_family_releases(release_id),
    method_entity_id          INTEGER NOT NULL,
    family_id                 TEXT NOT NULL,
    source                    TEXT NOT NULL,
    score                     REAL NOT NULL,
    margin                    REAL NOT NULL,
    PRIMARY KEY (release_id, method_entity_id)
);

-- Activation is append-only. The current release is the latest row.
CREATE TABLE IF NOT EXISTS method_family_release_activations (
    activation_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id                TEXT NOT NULL UNIQUE REFERENCES method_family_releases(release_id),
    activated_by              TEXT NOT NULL,
    activated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS trg_method_family_gold_sets_no_update
BEFORE UPDATE ON method_family_gold_sets
BEGIN
    SELECT RAISE(ABORT, 'method_family_gold_sets is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_gold_sets_no_delete
BEFORE DELETE ON method_family_gold_sets
BEGIN
    SELECT RAISE(ABORT, 'method_family_gold_sets is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_gold_labels_no_update
BEFORE UPDATE ON method_family_gold_labels
BEGIN
    SELECT RAISE(ABORT, 'method_family_gold_labels is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_gold_labels_no_delete
BEFORE DELETE ON method_family_gold_labels
BEGIN
    SELECT RAISE(ABORT, 'method_family_gold_labels is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_calibrations_no_update
BEFORE UPDATE ON method_family_calibrations
BEGIN
    SELECT RAISE(ABORT, 'method_family_calibrations is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_calibrations_no_delete
BEFORE DELETE ON method_family_calibrations
BEGIN
    SELECT RAISE(ABORT, 'method_family_calibrations is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_rulesets_no_update
BEFORE UPDATE ON method_family_rulesets
BEGIN
    SELECT RAISE(ABORT, 'method_family_rulesets is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_rulesets_no_delete
BEFORE DELETE ON method_family_rulesets
BEGIN
    SELECT RAISE(ABORT, 'method_family_rulesets is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_policy_previews_no_update
BEFORE UPDATE ON method_family_policy_previews
BEGIN
    SELECT RAISE(ABORT, 'method_family_policy_previews is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_policy_previews_no_delete
BEFORE DELETE ON method_family_policy_previews
BEGIN
    SELECT RAISE(ABORT, 'method_family_policy_previews is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_review_queues_no_update
BEFORE UPDATE ON method_family_review_queues
BEGIN
    SELECT RAISE(ABORT, 'method_family_review_queues is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_review_queues_no_delete
BEFORE DELETE ON method_family_review_queues
BEGIN
    SELECT RAISE(ABORT, 'method_family_review_queues is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_gold_extensions_no_update
BEFORE UPDATE ON method_family_gold_extensions
BEGIN
    SELECT RAISE(ABORT, 'method_family_gold_extensions is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_gold_extensions_no_delete
BEFORE DELETE ON method_family_gold_extensions
BEGIN
    SELECT RAISE(ABORT, 'method_family_gold_extensions is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_gold_extension_labels_no_update
BEFORE UPDATE ON method_family_gold_extension_labels
BEGIN
    SELECT RAISE(ABORT, 'method_family_gold_extension_labels is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_gold_extension_labels_no_delete
BEFORE DELETE ON method_family_gold_extension_labels
BEGIN
    SELECT RAISE(ABORT, 'method_family_gold_extension_labels is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_sets_no_update
BEFORE UPDATE ON method_family_blind_sets
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_sets is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_sets_no_delete
BEFORE DELETE ON method_family_blind_sets
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_sets is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_items_no_update
BEFORE UPDATE ON method_family_blind_items
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_items is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_items_no_delete
BEFORE DELETE ON method_family_blind_items
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_items is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_submissions_no_update
BEFORE UPDATE ON method_family_blind_submissions
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_submissions is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_submissions_no_delete
BEFORE DELETE ON method_family_blind_submissions
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_submissions is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_submission_labels_no_update
BEFORE UPDATE ON method_family_blind_submission_labels
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_submission_labels is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_submission_labels_no_delete
BEFORE DELETE ON method_family_blind_submission_labels
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_submission_labels is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_models_no_update
BEFORE UPDATE ON method_family_models
BEGIN
    SELECT RAISE(ABORT, 'method_family_models is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_models_no_delete
BEFORE DELETE ON method_family_models
BEGIN
    SELECT RAISE(ABORT, 'method_family_models is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_evaluations_no_update
BEFORE UPDATE ON method_family_blind_evaluations
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_evaluations is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_evaluations_no_delete
BEFORE DELETE ON method_family_blind_evaluations
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_evaluations is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_promotions_no_update
BEFORE UPDATE ON method_family_blind_promotions
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_promotions is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_blind_promotions_no_delete
BEFORE DELETE ON method_family_blind_promotions
BEGIN
    SELECT RAISE(ABORT, 'method_family_blind_promotions is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_releases_no_update
BEFORE UPDATE ON method_family_releases
BEGIN
    SELECT RAISE(ABORT, 'method_family_releases is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_releases_no_delete
BEFORE DELETE ON method_family_releases
BEGIN
    SELECT RAISE(ABORT, 'method_family_releases is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_release_assignments_no_update
BEFORE UPDATE ON method_family_release_assignments
BEGIN
    SELECT RAISE(ABORT, 'method_family_release_assignments is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_release_assignments_no_delete
BEFORE DELETE ON method_family_release_assignments
BEGIN
    SELECT RAISE(ABORT, 'method_family_release_assignments is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_release_activations_no_update
BEFORE UPDATE ON method_family_release_activations
BEGIN
    SELECT RAISE(ABORT, 'method_family_release_activations is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_method_family_release_activations_no_delete
BEFORE DELETE ON method_family_release_activations
BEGIN
    SELECT RAISE(ABORT, 'method_family_release_activations is immutable');
END;
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_db(conn)
    print(f"[DB] Initialized database at {_db_path()}")


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Add columns for citation/IF weighting on existing databases."""
    paper_cols = {r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()}
    journal_cols = {r[1] for r in conn.execute("PRAGMA table_info(journals)").fetchall()}
    entity_cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
    relation_cols = {r[1] for r in conn.execute("PRAGMA table_info(relations)").fetchall()}

    if "access_class" not in entity_cols:
        conn.execute("ALTER TABLE entities ADD COLUMN access_class TEXT")
    if "method_role" not in entity_cols:
        conn.execute("ALTER TABLE entities ADD COLUMN method_role TEXT")

    for col, ddl in (
        ("status", "ALTER TABLE relations ADD COLUMN status TEXT DEFAULT 'active'"),
        ("superseded_by", "ALTER TABLE relations ADD COLUMN superseded_by INTEGER"),
        (
            "extraction_pass",
            "ALTER TABLE relations ADD COLUMN extraction_pass TEXT DEFAULT 'section'",
        ),
    ):
        if col not in relation_cols:
            conn.execute(ddl)

    for col, ddl in (
        ("s2id", "ALTER TABLE papers ADD COLUMN s2id TEXT"),
        ("citation_count", "ALTER TABLE papers ADD COLUMN citation_count INTEGER DEFAULT 0"),
        ("open_access", "ALTER TABLE papers ADD COLUMN open_access INTEGER DEFAULT 0"),
        ("citation_source", "ALTER TABLE papers ADD COLUMN citation_source TEXT"),
        ("date_precision", "ALTER TABLE papers ADD COLUMN date_precision TEXT"),
        ("reconcile_status", "ALTER TABLE papers ADD COLUMN reconcile_status TEXT DEFAULT 'pending'"),
        ("reconcile_at", "ALTER TABLE papers ADD COLUMN reconcile_at TIMESTAMP"),
        ("fulltext_pdf_attempts", "ALTER TABLE papers ADD COLUMN fulltext_pdf_attempts INTEGER DEFAULT 0"),
    ):
        if col not in paper_cols:
            conn.execute(ddl)

    for col, ddl in (
        ("impact_factor", "ALTER TABLE journals ADD COLUMN impact_factor REAL"),
        ("if_year", "ALTER TABLE journals ADD COLUMN if_year INTEGER"),
        ("quartile", "ALTER TABLE journals ADD COLUMN quartile TEXT"),
    ):
        if col not in journal_cols:
            conn.execute(ddl)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS limitation_temporal (
            limitation_id       INTEGER PRIMARY KEY REFERENCES entities(id),
            limitation_name     TEXT NOT NULL,
            first_year          INTEGER,
            last_year           INTEGER,
            paper_cnt           INTEGER,
            asserted_cnt        INTEGER,
            hypothesized_cnt    INTEGER,
            early_cnt           INTEGER,
            recent_cnt          INTEGER,
            recent_ratio        REAL,
            temporal_status     TEXT,
            avg_cite            REAL,
            avg_cite_per_year   REAL,
            impact_tier         TEXT,
            computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_lt_status ON limitation_temporal(temporal_status);
        CREATE INDEX IF NOT EXISTS idx_lt_last_year ON limitation_temporal(last_year);

        CREATE TABLE IF NOT EXISTS limitation_resolution_signals (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            limitation_id       INTEGER NOT NULL REFERENCES entities(id),
            signal_type         TEXT NOT NULL,
            anchor_pmid         TEXT,
            followup_pmid       TEXT,
            anchor_year         INTEGER,
            followup_year       INTEGER,
            shared_entities     TEXT,
            confidence          REAL DEFAULT 0.5,
            computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_lrs_limitation ON limitation_resolution_signals(limitation_id);
        CREATE INDEX IF NOT EXISTS idx_lrs_signal ON limitation_resolution_signals(signal_type);
        CREATE INDEX IF NOT EXISTS idx_rel_limitation ON relations(relation, object_id);
        CREATE INDEX IF NOT EXISTS idx_relations_pmid ON relations(source_pmid);
        CREATE INDEX IF NOT EXISTS idx_relations_rel_pmid ON relations(relation, source_pmid);
CREATE INDEX IF NOT EXISTS idx_relations_object_id ON relations(object_id);
        CREATE INDEX IF NOT EXISTS idx_relations_object_id ON relations(object_id);

        CREATE TABLE IF NOT EXISTS weekly_hotspot_runs (
            week_id             TEXT PRIMARY KEY,
            snapshot_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            window_days         INTEGER NOT NULL,
            prior_window_days   INTEGER NOT NULL,
            papers_ingested     INTEGER DEFAULT 0,
            report_path         TEXT
        );
        CREATE TABLE IF NOT EXISTS weekly_hotspot_snapshots (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            week_id             TEXT NOT NULL,
            board               TEXT NOT NULL,
            item_key            TEXT NOT NULL,
            entity_type         TEXT,
            rank_pos            INTEGER,
            recent_cnt          INTEGER,
            prior_cnt           INTEGER,
            velocity            REAL,
            emerging_score      REAL,
            avg_cite            REAL,
            avg_if              REAL,
            gap_phase           TEXT,
            top_pmids           TEXT,
            UNIQUE(week_id, board, item_key)
        );
        CREATE INDEX IF NOT EXISTS idx_whs_week_board ON weekly_hotspot_snapshots(week_id, board);
        CREATE INDEX IF NOT EXISTS idx_whs_board_score ON weekly_hotspot_snapshots(board, emerging_score);

        CREATE TABLE IF NOT EXISTS ops_runs (
            run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            week_id             TEXT,
            focus_raw           TEXT,
            focus_key           TEXT NOT NULL,
            source              TEXT,
            started_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at         TIMESTAMP,
            hotspot_week_id     TEXT,
            gap_report_path     TEXT,
            proposal_report_path TEXT,
            validation_status   TEXT,
            debate_session_id   TEXT,
            notes               TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ops_runs_focus_finished
            ON ops_runs(focus_key, finished_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ops_runs_week ON ops_runs(week_id);

        CREATE TABLE IF NOT EXISTS ops_gap_items (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id              INTEGER NOT NULL REFERENCES ops_runs(run_id),
            rank_pos            INTEGER,
            title               TEXT NOT NULL,
            research_question   TEXT,
            fingerprint         TEXT,
            section_md          TEXT,
            status              TEXT DEFAULT 'reported'
        );
        CREATE INDEX IF NOT EXISTS idx_ops_gap_run ON ops_gap_items(run_id);
        CREATE INDEX IF NOT EXISTS idx_ops_gap_fp ON ops_gap_items(fingerprint);

        CREATE TABLE IF NOT EXISTS ops_proposals (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id              INTEGER NOT NULL REFERENCES ops_runs(run_id),
            gap_item_id         INTEGER REFERENCES ops_gap_items(id),
            proposal_path       TEXT,
            proposal_md         TEXT,
            feasibility_score   REAL,
            critic_score        REAL,
            status              TEXT,
            target_difficulty   TEXT,
            assessed_difficulty TEXT,
            difficulty_delta    INTEGER,
            difficulty_breakdown_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ops_prop_run ON ops_proposals(run_id);

        CREATE TABLE IF NOT EXISTS debate_sessions (
            session_id          TEXT PRIMARY KEY,
            focus_raw           TEXT,
            focus_key           TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'running',
            current_round       INTEGER DEFAULT 0,
            next_role           TEXT,
            max_rounds          INTEGER NOT NULL,
            top_n               INTEGER NOT NULL,
            validation_status   TEXT,
            final_report        TEXT,
            state_json          TEXT NOT NULL DEFAULT '{}',
            model               TEXT,
            prompt_version      TEXT,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at        TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_debate_sessions_focus_updated
            ON debate_sessions(focus_key, updated_at DESC);

        CREATE TABLE IF NOT EXISTS debate_turns (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          TEXT NOT NULL REFERENCES debate_sessions(session_id) ON DELETE CASCADE,
            round_no            INTEGER NOT NULL,
            role                TEXT NOT NULL,
            input_text          TEXT,
            output_text         TEXT,
            handoff_json        TEXT,
            status              TEXT NOT NULL DEFAULT 'completed',
            started_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at        TIMESTAMP,
            UNIQUE(session_id, round_no, role)
        );
        CREATE INDEX IF NOT EXISTS idx_debate_turns_session_round
            ON debate_turns(session_id, round_no, role);

        CREATE TABLE IF NOT EXISTS debate_tool_events (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          TEXT NOT NULL REFERENCES debate_sessions(session_id) ON DELETE CASCADE,
            round_no            INTEGER NOT NULL,
            role                TEXT NOT NULL,
            event_type          TEXT NOT NULL,
            tool_name           TEXT,
            call_id             TEXT,
            args_json           TEXT,
            result_json         TEXT,
            error_text          TEXT,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_debate_tool_events_session_round
            ON debate_tool_events(session_id, round_no, role, id);

        CREATE TABLE IF NOT EXISTS debate_candidates (
            session_id          TEXT NOT NULL REFERENCES debate_sessions(session_id) ON DELETE CASCADE,
            candidate_id        TEXT NOT NULL,
            title               TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'proposed',
            first_round         INTEGER NOT NULL,
            last_round          INTEGER NOT NULL,
            metadata_json       TEXT,
            PRIMARY KEY(session_id, candidate_id)
        );
        CREATE INDEX IF NOT EXISTS idx_debate_candidates_session_status
            ON debate_candidates(session_id, status);

        CREATE TABLE IF NOT EXISTS idea_sessions (
            session_id          TEXT PRIMARY KEY,
            debate_session_id   TEXT REFERENCES debate_sessions(session_id),
            gap_text            TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'running',
            current_round       INTEGER DEFAULT 0,
            next_role           TEXT DEFAULT 'generator',
            max_rounds          INTEGER NOT NULL,
            state_json          TEXT NOT NULL DEFAULT '{}',
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at        TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_idea_sessions_debate_updated
            ON idea_sessions(debate_session_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS idea_turns (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          TEXT NOT NULL REFERENCES idea_sessions(session_id) ON DELETE CASCADE,
            round_no            INTEGER NOT NULL,
            role                TEXT NOT NULL,
            output_text         TEXT,
            state_json          TEXT NOT NULL DEFAULT '{}',
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, round_no, role)
        );
        CREATE INDEX IF NOT EXISTS idx_idea_turns_session_round
            ON idea_turns(session_id, round_no, role);

        CREATE TABLE IF NOT EXISTS paper_entity_bindings (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            source_pmid         TEXT NOT NULL,
            method_entity_id    INTEGER,
            disease_entity_id   INTEGER,
            dataset_entity_id   INTEGER,
            confidence          REAL DEFAULT 1.0,
            evidence_quote      TEXT,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_peb_pmid ON paper_entity_bindings(source_pmid);

        CREATE TABLE IF NOT EXISTS paper_improvement_suggestions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            source_pmid           TEXT NOT NULL,
            limitation_entity_id  INTEGER,
            action_type           TEXT NOT NULL,
            suggestion            TEXT NOT NULL,
            evidence_quote        TEXT,
            evidence_section      TEXT,
            grounding             TEXT NOT NULL,
            confidence            REAL DEFAULT 0.5,
            status                TEXT DEFAULT 'active',
            extraction_pass       TEXT DEFAULT 'fulltext_reconcile',
            created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_pis_pmid ON paper_improvement_suggestions(source_pmid);
        CREATE INDEX IF NOT EXISTS idx_pis_action ON paper_improvement_suggestions(action_type);
        CREATE INDEX IF NOT EXISTS idx_pis_lim ON paper_improvement_suggestions(limitation_entity_id);
        CREATE INDEX IF NOT EXISTS idx_pis_status ON paper_improvement_suggestions(status);
    """)

    prop_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(ops_proposals)").fetchall()
    }
    if "critic_score" not in prop_cols:
        conn.execute("ALTER TABLE ops_proposals ADD COLUMN critic_score REAL")

    for col, ddl in (
        ("target_difficulty", "ALTER TABLE ops_proposals ADD COLUMN target_difficulty TEXT"),
        ("assessed_difficulty", "ALTER TABLE ops_proposals ADD COLUMN assessed_difficulty TEXT"),
        ("difficulty_delta", "ALTER TABLE ops_proposals ADD COLUMN difficulty_delta INTEGER"),
        (
            "difficulty_breakdown_json",
            "ALTER TABLE ops_proposals ADD COLUMN difficulty_breakdown_json TEXT",
        ),
    ):
        if col not in prop_cols:
            conn.execute(ddl)

    ops_run_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(ops_runs)").fetchall()
    }
    for col, ddl in (
        ("validation_status", "ALTER TABLE ops_runs ADD COLUMN validation_status TEXT"),
        ("debate_session_id", "ALTER TABLE ops_runs ADD COLUMN debate_session_id TEXT"),
    ):
        if col not in ops_run_cols:
            conn.execute(ddl)

    # Ops memory: collapse synonym spellings onto disease canonical focus_key
    try:
        from analysis.ops_memory import migrate_ops_focus_keys
    except ImportError:
        migrate_ops_focus_keys = None  # type: ignore
    if migrate_ops_focus_keys is not None:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "ops_runs" in tables:
            migrate_ops_focus_keys(conn)


def upsert_paper(data: dict[str, Any]) -> int:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, source_queries FROM papers WHERE pmid=? OR (doi IS NOT NULL AND doi=? AND doi != '')",
            (data.get("pmid"), data.get("doi")),
        ).fetchone()

        new_queries: list[str] = data.get("source_queries", [])
        if existing:
            old_queries = json.loads(existing["source_queries"] or "[]")
            merged = list(set(old_queries) | set(new_queries))
            # Backfill date fields only when date_precision is still unset.
            row_full = conn.execute(
                "SELECT date_precision FROM papers WHERE id=?", (existing["id"],)
            ).fetchone()
            existing_prec = (row_full["date_precision"] if row_full else None) or ""
            new_prec = (data.get("date_precision") or "").strip()
            if not existing_prec and new_prec:
                conn.execute(
                    """UPDATE papers SET
                       source_queries=?,
                       abstract=COALESCE(NULLIF(?, ''), abstract),
                       title=COALESCE(NULLIF(?, ''), title),
                       pmc_id=COALESCE(?, pmc_id),
                       pub_date=COALESCE(NULLIF(?, ''), pub_date),
                       year=COALESCE(?, year),
                       date_precision=?
                       WHERE id=?""",
                    (
                        json.dumps(merged),
                        data.get("abstract", ""),
                        data.get("title", ""),
                        data.get("pmc_id"),
                        data.get("pub_date") or "",
                        data.get("year"),
                        new_prec,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """UPDATE papers SET
                       source_queries=?,
                       abstract=COALESCE(NULLIF(?, ''), abstract),
                       title=COALESCE(NULLIF(?, ''), title),
                       pmc_id=COALESCE(?, pmc_id)
                       WHERE id=?""",
                    (
                        json.dumps(merged),
                        data.get("abstract", ""),
                        data.get("title", ""),
                        data.get("pmc_id"),
                        existing["id"],
                    ),
                )
            return existing["id"]

        conn.execute(
            """INSERT INTO papers
               (pmid, doi, pmc_id, title, abstract, pub_date, year, date_precision,
                journal_name, journal_abbr, issn, pub_types, mesh_terms,
                keywords, source_queries, full_text_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data.get("pmid"),
                data.get("doi"),
                data.get("pmc_id"),
                data.get("title", ""),
                data.get("abstract", ""),
                data.get("pub_date"),
                data.get("year"),
                data.get("date_precision"),
                data.get("journal_name"),
                data.get("journal_abbr"),
                data.get("issn"),
                json.dumps(data.get("pub_types", [])),
                json.dumps(data.get("mesh_terms", [])),
                json.dumps(data.get("keywords", [])),
                json.dumps(new_queries),
                data.get("full_text_status", "pending"),
            ),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def upsert_journal(name: str, abbr: str = "", issn: str = "") -> int:
    with get_conn() as conn:
        existing = None
        if issn:
            existing = conn.execute(
                "SELECT id FROM journals WHERE issn=?", (issn,)
            ).fetchone()
        if existing is None:
            existing = conn.execute(
                "SELECT id FROM journals WHERE name=?", (name,)
            ).fetchone()
        if existing:
            return existing["id"]
        conn.execute(
            "INSERT OR IGNORE INTO journals (name, abbr, issn) VALUES (?,?,?)",
            (name, abbr or None, issn or None),
        )
        row = conn.execute("SELECT id FROM journals WHERE name=?", (name,)).fetchone()
        return row["id"] if row else conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_all_journals() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM journals").fetchall()


def update_journal_if(
    journal_id: int,
    impact_factor: float,
    if_year: int,
    quartile: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE journals SET impact_factor=?, if_year=?, quartile=? WHERE id=?",
            (impact_factor, if_year, quartile, journal_id),
        )


def link_paper_journal(paper_id: int, journal_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE papers SET journal_id=? WHERE id=?", (journal_id, paper_id))


def upsert_author(name: str, affiliation: str = "", orcid: str = "") -> int:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM authors WHERE name=? AND affiliation=?", (name, affiliation)
        ).fetchone()
        if existing:
            return existing["id"]
        conn.execute(
            "INSERT INTO authors (name, affiliation, orcid) VALUES (?,?,?)",
            (name, affiliation, orcid),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def link_paper_author(paper_id: int, author_id: int, order: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO paper_authors (paper_id, author_id, author_order) VALUES (?,?,?)",
            (paper_id, author_id, order),
        )


def mark_fulltext_status(
    paper_id: int,
    status: str,
    pmc_id: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE papers SET
               full_text_status=?,
               pmc_id=COALESCE(?, pmc_id),
               full_text_fetched_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (status, pmc_id, paper_id),
        )


def cooldown_days_for_pdf_attempts(
    attempts: int, *, base_days: int = 7, cap_days: int = 56
) -> int:
    a = max(int(attempts or 0), 1)
    return min(int(cap_days), int(base_days) * (2 ** (a - 1)))


def increment_fulltext_pdf_attempts(paper_id: int) -> int:
    with get_conn() as conn:
        conn.execute(
            """UPDATE papers SET
                   fulltext_pdf_attempts = COALESCE(fulltext_pdf_attempts, 0) + 1
               WHERE id=?""",
            (paper_id,),
        )
        row = conn.execute(
            "SELECT fulltext_pdf_attempts FROM papers WHERE id=?",
            (paper_id,),
        ).fetchone()
        return int(row[0])


def repair_misclassified_unavailable_without_pdf_attempt() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE papers SET full_text_status='jats_unavailable'
               WHERE full_text_status='unavailable'
                 AND COALESCE(fulltext_pdf_attempts, 0)=0
                 AND pmid IS NOT NULL"""
        )
        return int(cur.rowcount)


def requeue_cooled_fulltext_failures(
    *,
    cooldown_days: int,
    force: bool = False,
) -> int:
    """Reset cooled-down unavailable papers to pending.

    Escalating cooldown by fulltext_pdf_attempts when force=False (7/14/28/56
    days when base cooldown_days=7). Does not touch jats_unavailable, available,
    or extraction/reconcile flags.
    """
    if cooldown_days < 0:
        raise ValueError("cooldown_days must be >= 0")
    with get_conn() as conn:
        if force:
            cur = conn.execute(
                """UPDATE papers SET
                       full_text_status='pending',
                       full_text_fetched_at=CURRENT_TIMESTAMP
                   WHERE full_text_status='unavailable'
                     AND pmid IS NOT NULL"""
            )
        else:
            cur = conn.execute(
                """UPDATE papers SET
                       full_text_status='pending',
                       full_text_fetched_at=CURRENT_TIMESTAMP
                   WHERE full_text_status='unavailable'
                     AND pmid IS NOT NULL
                     AND (
                       full_text_fetched_at IS NULL
                       OR julianday('now') - julianday(full_text_fetched_at)
                          >= CASE
                               WHEN COALESCE(fulltext_pdf_attempts, 0) <= 1
                                 THEN ?
                               WHEN fulltext_pdf_attempts = 2
                                 THEN ?
                               WHEN fulltext_pdf_attempts = 3
                                 THEN ?
                               ELSE ?
                             END
                     )""",
                (
                    float(cooldown_days_for_pdf_attempts(1, base_days=cooldown_days)),
                    float(cooldown_days_for_pdf_attempts(2, base_days=cooldown_days)),
                    float(cooldown_days_for_pdf_attempts(3, base_days=cooldown_days)),
                    float(cooldown_days_for_pdf_attempts(4, base_days=cooldown_days)),
                ),
            )
        return int(cur.rowcount)


def delete_paper_sections(paper_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM document_sections WHERE paper_id=?", (paper_id,))


def insert_sections(paper_id: int, sections: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        for sec in sections:
            conn.execute(
                """INSERT INTO document_sections
                   (paper_id, section_type, title, content, order_idx)
                   VALUES (?,?,?,?,?)""",
                (
                    paper_id,
                    sec["section_type"],
                    sec.get("title", ""),
                    sec["content"],
                    sec.get("order_idx", 0),
                ),
            )


def get_papers_pending_fulltext() -> list[sqlite3.Row]:
    return get_papers_needing_fulltext()


def get_papers_needing_fulltext() -> list[sqlite3.Row]:
    """Papers awaiting tier-1 JATS fetch (status=pending)."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT id, pmid, doi, pmc_id FROM papers
               WHERE pmid IS NOT NULL AND full_text_status = 'pending'"""
        ).fetchall()


def get_papers_for_extraction(limit: int = 0) -> list[sqlite3.Row]:
    with get_conn() as conn:
        sql = """
            SELECT * FROM papers
            WHERE extraction_done=0
              AND abstract IS NOT NULL AND abstract != ''
            ORDER BY
              CASE
                WHEN LOWER(title) LIKE 'correction:%'
                  OR LOWER(title) LIKE 'corrigendum:%'
                  OR LOWER(title) LIKE 'erratum:%'
                  OR LOWER(title) LIKE 'comment on:%'
                  OR (LENGTH(abstract) < 80 AND LOWER(abstract) LIKE '%corrects the article%')
                THEN 2
                ELSE 0
              END,
              CASE full_text_status
                WHEN 'available' THEN 0
                WHEN 'pdf_available' THEN 1
                ELSE 2
              END,
              year DESC
        """
        if limit:
            sql += f" LIMIT {limit}"
        return conn.execute(sql).fetchall()


def get_unprocessed_papers(limit: int = 0) -> list[sqlite3.Row]:
    return get_papers_for_extraction(limit=limit)


def get_paper_sections(paper_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM document_sections
               WHERE paper_id=? ORDER BY order_idx""",
            (paper_id,),
        ).fetchall()


def mark_extraction_done(paper_id: int, study_type: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET extraction_done=1, study_type=? WHERE id=?",
            (study_type, paper_id),
        )


def upsert_entity(
    name: str,
    entity_type: str,
    cui: str = "",
    access_class: str | None = None,
    method_role: str | None = None,
) -> int:
    from extractor.dataset_access import stronger_access
    from extractor.entity_normalize import normalize_entity_name

    raw_name = name.strip().lower()
    normalized = normalize_entity_name(name, entity_type)
    alias = raw_name if raw_name and raw_name != normalized else None
    ac = None
    if entity_type == "Dataset" and access_class:
        ac = access_class.strip().lower()
        if ac not in ("public", "private", "unknown"):
            ac = "unknown"

    resolved_role = None
    if entity_type == "Method":
        from analysis.method_role import resolve_method_role

        resolved_role = resolve_method_role(name, method_role)

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, access_class, method_role, aliases FROM entities WHERE name=? AND type=?",
            (normalized, entity_type),
        ).fetchone()
        if existing:
            if alias:
                try:
                    aliases = set(json.loads(existing["aliases"] or "[]"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    aliases = {
                        value.strip() for value in str(existing["aliases"] or "").split(",")
                        if value.strip()
                    }
                if alias not in aliases:
                    aliases.add(alias)
                    conn.execute(
                        "UPDATE entities SET aliases=? WHERE id=?",
                        (json.dumps(sorted(aliases), ensure_ascii=False), existing["id"]),
                    )
            if entity_type == "Dataset" and ac:
                merged = stronger_access(existing["access_class"], ac)
                if merged != (existing["access_class"] or "unknown"):
                    conn.execute(
                        "UPDATE entities SET access_class=? WHERE id=?",
                        (merged, existing["id"]),
                    )
            if (
                entity_type == "Method"
                and resolved_role is not None
                and resolved_role != "unknown"
                and resolved_role != existing["method_role"]
            ):
                conn.execute(
                    "UPDATE entities SET method_role=? WHERE id=?",
                    (resolved_role, existing["id"]),
                )
            return existing["id"]
        conn.execute(
            """INSERT INTO entities
               (name, type, cui, aliases, access_class, method_role) VALUES (?,?,?,?,?,?)""",
            (
                normalized,
                entity_type,
                cui or None,
                json.dumps([alias], ensure_ascii=False) if alias else None,
                ac if entity_type == "Dataset" else None,
                resolved_role if entity_type == "Method" else None,
            ),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def insert_relation(
    subject_type: str,
    subject_id: int,
    relation: str,
    object_type: str,
    object_id: int,
    source_pmid: str = "",
    metric_value: str = "",
    confidence: float = 1.0,
    evidence_section: str = "",
    evidence_quote: str = "",
    extraction_granularity: str = "abstract",
    polarity: str = "asserted",
    status: str = "active",
    superseded_by: int | None = None,
    extraction_pass: str = "section",
) -> int:
    with get_conn() as conn:
        existing = conn.execute(
            """SELECT id, extraction_granularity, evidence_quote, status, superseded_by
               FROM relations
               WHERE subject_type=? AND subject_id=? AND relation=?
                 AND object_type=? AND object_id=? AND source_pmid=?""",
            (subject_type, subject_id, relation, object_type, object_id, source_pmid),
        ).fetchone()
        if existing:
            # Pass 2 may supersede a Pass 1 edge then re-assert the canonical.
            if (
                existing["status"] == "superseded"
                and status == "active"
                and extraction_pass != "fulltext_reconcile"
            ):
                return existing["id"]
            gran = existing["extraction_granularity"]
            _rank = {"fulltext": 3, "mineru_pdf": 2, "abstract": 1}
            if _rank.get(gran, 0) > _rank.get(extraction_granularity, 0):
                return existing["id"]
            quote = existing["evidence_quote"] or ""
            if evidence_quote and evidence_quote not in quote:
                quote = f"{quote}; {evidence_quote}".strip("; ")
            if status == "active" and extraction_pass == "fulltext_reconcile":
                next_superseded_by = None
            elif superseded_by is not None:
                next_superseded_by = superseded_by
            else:
                next_superseded_by = existing["superseded_by"]
            conn.execute(
                """UPDATE relations SET
                   metric_value=COALESCE(NULLIF(?, ''), metric_value),
                   confidence=MAX(confidence, ?),
                   evidence_section=COALESCE(NULLIF(?, ''), evidence_section),
                   evidence_quote=?,
                   extraction_granularity=?,
                   polarity=?,
                   status=?,
                   superseded_by=?,
                   extraction_pass=?
                   WHERE id=?""",
                (
                    metric_value,
                    confidence,
                    evidence_section,
                    quote,
                    extraction_granularity,
                    polarity,
                    status,
                    next_superseded_by,
                    extraction_pass,
                    existing["id"],
                ),
            )
            return existing["id"]

        conn.execute(
            """INSERT INTO relations
               (subject_type, subject_id, relation, object_type, object_id,
                metric_value, source_pmid, confidence, evidence_section,
                evidence_quote, extraction_granularity, polarity,
                status, superseded_by, extraction_pass)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                subject_type,
                subject_id,
                relation,
                object_type,
                object_id,
                metric_value or None,
                source_pmid or None,
                confidence,
                evidence_section or None,
                evidence_quote or None,
                extraction_granularity,
                polarity,
                status,
                superseded_by,
                extraction_pass,
            ),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def insert_relation_evidence(
    relation_id: int,
    *,
    source_pmid: str = "",
    evidence_section: str = "",
    evidence_quote: str,
    evidence_start: int | None = None,
    evidence_end: int | None = None,
    evidence_status: str = "unverified",
    support_status: str = "unchecked",
    support_reason: str = "",
    extraction_granularity: str = "abstract",
    extraction_pass: str = "section",
) -> int | None:
    """Persist one independently addressable evidence span for a relation."""
    if not evidence_quote.strip():
        return None
    digest = hashlib.sha256(evidence_quote.encode("utf-8")).hexdigest()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO relation_evidence
               (relation_id, source_pmid, evidence_section, evidence_quote,
                evidence_start, evidence_end, evidence_status, support_status,
                support_reason, extraction_granularity, extraction_pass,
                evidence_sha256)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                relation_id,
                source_pmid or None,
                evidence_section or None,
                evidence_quote,
                evidence_start,
                evidence_end,
                evidence_status,
                support_status,
                support_reason or None,
                extraction_granularity,
                extraction_pass,
                digest,
            ),
        )
        row = conn.execute(
            """SELECT id FROM relation_evidence
               WHERE relation_id=? AND evidence_sha256=?
                 AND evidence_start IS ? AND evidence_end IS ?""",
            (relation_id, digest, evidence_start, evidence_end),
        ).fetchone()
        return row["id"] if row else None


def insert_extraction_audit(
    paper_id: int | None,
    *,
    source_pmid: str = "",
    section_type: str,
    section_title: str = "",
    extraction_granularity: str = "abstract",
    audit: dict[str, Any],
) -> int:
    """Persist one section extraction outcome for replay and quality analysis."""
    rejected = audit.get("rejected")
    if not isinstance(rejected, list):
        rejected = []
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO extraction_audits
               (paper_id, source_pmid, section_type, section_title,
                extraction_granularity, source_chars, sent_chars, truncated,
                parsed, postprocessed, retained, outcome, empty_reason,
                recall_check_reason, rejected_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                paper_id,
                source_pmid or None,
                section_type,
                section_title or None,
                extraction_granularity,
                int(audit.get("source_chars") or 0),
                int(audit.get("sent_chars") or 0),
                1 if audit.get("truncated") else 0,
                int(audit.get("parsed") or 0),
                int(audit.get("postprocessed") or 0),
                int(audit.get("retained") or 0),
                str(audit.get("outcome") or "unknown"),
                audit.get("empty_reason"),
                audit.get("recall_check_reason"),
                json.dumps(rejected, ensure_ascii=False, default=str),
            ),
        )
        return int(cur.lastrowid)


def supersede_relation(relation_id: int, superseded_by: int | None) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE relations SET status='superseded', superseded_by=?
               WHERE id=?""",
            (superseded_by, relation_id),
        )


def list_relations_for_pmid(
    pmid: str,
    relation: str | None = None,
) -> list[sqlite3.Row]:
    """Relations for a PMID with object entity name joined."""
    clauses = ["r.source_pmid=?"]
    params: list[Any] = [pmid]
    if relation:
        clauses.append("r.relation=?")
        params.append(relation)
    where = " AND ".join(clauses)
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT r.*, e.name AS object_name
                FROM relations r
                JOIN entities e ON e.id = r.object_id
                WHERE {where}""",
            tuple(params),
        ).fetchall()


def set_paper_reconcile_status(paper_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE papers SET reconcile_status=?, reconcile_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (status, paper_id),
        )


def clear_paper_kg_extractions(pmid: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM relations WHERE source_pmid=?", (pmid,))
        conn.execute("DELETE FROM paper_entity_bindings WHERE source_pmid=?", (pmid,))
        conn.execute(
            "DELETE FROM paper_improvement_suggestions WHERE source_pmid=?",
            (pmid,),
        )
        conn.execute(
            """UPDATE papers
               SET extraction_done=0,
                   study_type=NULL,
                   reconcile_status='pending',
                   reconcile_at=NULL
               WHERE pmid=?""",
            (pmid,),
        )


def list_papers_for_fulltext_upgrade() -> list[sqlite3.Row]:
    """Abstract-extracted papers that now have fulltext sections available."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT id, pmid, year, full_text_status, reconcile_status
               FROM papers
               WHERE extraction_done=1
                 AND reconcile_status='skipped_no_ft'
                 AND full_text_status IN ('available', 'pdf_available')
                 AND pmid IS NOT NULL
               ORDER BY year DESC, id DESC"""
        ).fetchall()


def clear_abstract_extractions_for_fulltext_upgrade() -> int:
    """Clear KG extractions for upgrade candidates; return number cleared."""
    rows = list_papers_for_fulltext_upgrade()
    for row in rows:
        clear_paper_kg_extractions(row["pmid"])
    return len(rows)


def upsert_paper_entity_binding(
    source_pmid: str,
    method_entity_id: int | None,
    disease_entity_id: int | None,
    dataset_entity_id: int | None,
    confidence: float = 1.0,
    evidence_quote: str = "",
) -> int:
    with get_conn() as conn:
        existing = conn.execute(
            """SELECT id FROM paper_entity_bindings
               WHERE source_pmid=?
                 AND COALESCE(method_entity_id, -1)=COALESCE(?, -1)
                 AND COALESCE(disease_entity_id, -1)=COALESCE(?, -1)
                 AND COALESCE(dataset_entity_id, -1)=COALESCE(?, -1)""",
            (source_pmid, method_entity_id, disease_entity_id, dataset_entity_id),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE paper_entity_bindings SET
                   confidence=?, evidence_quote=?
                   WHERE id=?""",
                (confidence, evidence_quote or None, existing["id"]),
            )
            return existing["id"]
        conn.execute(
            """INSERT INTO paper_entity_bindings
               (source_pmid, method_entity_id, disease_entity_id, dataset_entity_id,
                confidence, evidence_quote)
               VALUES (?,?,?,?,?,?)""",
            (
                source_pmid,
                method_entity_id,
                disease_entity_id,
                dataset_entity_id,
                confidence,
                evidence_quote or None,
            ),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_papers_by_pmids(pmids: list[str]) -> list[sqlite3.Row]:
    if not pmids:
        return []
    placeholders = ",".join("?" * len(pmids))
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM papers WHERE pmid IN ({placeholders})",
            tuple(pmids),
        ).fetchall()


def db_stats() -> dict[str, Any]:
    with get_conn() as conn:
        stats = {
            "papers": conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
            "sections": conn.execute("SELECT COUNT(*) FROM document_sections").fetchone()[0],
            "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "relations": conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
            "fulltext_jats": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE full_text_status='available'"
            ).fetchone()[0],
            "fulltext_mineru_pdf": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE full_text_status='pdf_available'"
            ).fetchone()[0],
            "fulltext_unavailable": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE full_text_status='unavailable'"
            ).fetchone()[0],
            "extracted": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE extraction_done=1"
            ).fetchone()[0],
            "relations_fulltext": conn.execute(
                "SELECT COUNT(*) FROM relations WHERE extraction_granularity='fulltext'"
            ).fetchone()[0],
            "relations_mineru_pdf": conn.execute(
                "SELECT COUNT(*) FROM relations WHERE extraction_granularity='mineru_pdf'"
            ).fetchone()[0],
            "relations_abstract": conn.execute(
                "SELECT COUNT(*) FROM relations WHERE extraction_granularity='abstract'"
            ).fetchone()[0],
            "s2_enriched": conn.execute(
                """SELECT COUNT(*) FROM papers
                   WHERE citation_source IS NOT NULL
                     AND citation_source NOT IN ('', 'unavailable')"""
            ).fetchone()[0],
            "citations_openalex": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE citation_source='openalex'"
            ).fetchone()[0],
            "citations_semantic_scholar": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE citation_source='semantic_scholar'"
            ).fetchone()[0],
            "journals_with_if": conn.execute(
                "SELECT COUNT(*) FROM journals WHERE impact_factor IS NOT NULL"
            ).fetchone()[0],
            "date_precision_day": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE date_precision='day'"
            ).fetchone()[0],
            "date_precision_month": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE date_precision='month'"
            ).fetchone()[0],
            "date_precision_year": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE date_precision='year'"
            ).fetchone()[0],
            "date_precision_unknown": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE date_precision='unknown'"
            ).fetchone()[0],
            "date_precision_missing": conn.execute(
                """SELECT COUNT(*) FROM papers
                   WHERE date_precision IS NULL OR date_precision=''"""
            ).fetchone()[0],
        }
        stats["fulltext_available"] = stats["fulltext_jats"] + stats["fulltext_mineru_pdf"]
    return stats


def landscape_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM pathology_landscape").fetchone()[0]


def clear_landscape() -> int:
    """Delete all cached pathology landscape rows. Returns rows removed."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM pathology_landscape")
        return cur.rowcount


def upsert_landscape(disease_id: str, payload: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO pathology_landscape (disease_id, payload_json, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(disease_id) DO UPDATE SET
                 payload_json=excluded.payload_json,
                 updated_at=CURRENT_TIMESTAMP""",
            (disease_id, json.dumps(payload, ensure_ascii=False)),
        )


def get_all_landscape() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT disease_id, payload_json, updated_at FROM pathology_landscape"
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "disease_id": r["disease_id"],
            "payload": json.loads(r["payload_json"]),
            "updated_at": r["updated_at"],
        })
    return out


def save_feasibility_assessment(
    gap_title: str,
    hypothesis_id: str,
    hypothesis: dict[str, Any],
    score: float,
    status: str,
    assessment: dict[str, Any],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO feasibility_assessments
               (gap_title, hypothesis_id, hypothesis_json, feasibility_score,
                status, assessment_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                gap_title,
                hypothesis_id,
                json.dumps(hypothesis, ensure_ascii=False),
                score,
                status,
                json.dumps(assessment, ensure_ascii=False),
            ),
        )


def get_feasibility_assessments(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT gap_title, hypothesis_id, feasibility_score, status,
                      assessment_json, assessed_at
               FROM feasibility_assessments
               ORDER BY assessed_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_public_dataset_assessment(
    gap_title: str,
    keyword: str,
    score: float,
    status: str,
    assessment: dict[str, Any],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO public_dataset_assessments
               (gap_title, keyword, public_coverage_score, status, assessment_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                gap_title,
                keyword,
                score,
                status,
                json.dumps(assessment, ensure_ascii=False),
            ),
        )


def get_public_dataset_assessments(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT gap_title, keyword, public_coverage_score, status,
                      assessment_json, assessed_at
               FROM public_dataset_assessments
               ORDER BY assessed_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def clear_limitation_lifecycle() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM limitation_resolution_signals")
        conn.execute("DELETE FROM limitation_temporal")


def upsert_limitation_temporal(
    rows: list[dict[str, Any]],
    *,
    chunk_size: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    if not rows:
        return 0
    chunk = chunk_size or config.GAP_LIFECYCLE_UPSERT_CHUNK
    sql = """INSERT INTO limitation_temporal
               (limitation_id, limitation_name, first_year, last_year, paper_cnt,
                asserted_cnt, hypothesized_cnt, early_cnt, recent_cnt, recent_ratio,
                temporal_status, avg_cite, avg_cite_per_year, impact_tier, computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(limitation_id) DO UPDATE SET
                 limitation_name=excluded.limitation_name,
                 first_year=excluded.first_year,
                 last_year=excluded.last_year,
                 paper_cnt=excluded.paper_cnt,
                 asserted_cnt=excluded.asserted_cnt,
                 hypothesized_cnt=excluded.hypothesized_cnt,
                 early_cnt=excluded.early_cnt,
                 recent_cnt=excluded.recent_cnt,
                 recent_ratio=excluded.recent_ratio,
                 temporal_status=excluded.temporal_status,
                 avg_cite=excluded.avg_cite,
                 avg_cite_per_year=excluded.avg_cite_per_year,
                 impact_tier=excluded.impact_tier,
                 computed_at=CURRENT_TIMESTAMP"""

    def _tuple(r: dict[str, Any]) -> tuple:
        return (
            r["limitation_id"],
            r["limitation_name"],
            r.get("first_year"),
            r.get("last_year"),
            r.get("paper_cnt"),
            r.get("asserted_cnt"),
            r.get("hypothesized_cnt"),
            r.get("early_cnt"),
            r.get("recent_cnt"),
            r.get("recent_ratio"),
            r.get("temporal_status"),
            r.get("avg_cite"),
            r.get("avg_cite_per_year"),
            r.get("impact_tier"),
        )

    total = len(rows)
    with get_conn() as conn:
        for start in range(0, total, chunk):
            batch = rows[start : start + chunk]
            conn.executemany(sql, [_tuple(r) for r in batch])
            if on_progress:
                on_progress(min(start + len(batch), total), total)
    return total


def insert_limitation_resolution_signals(
    rows: list[dict[str, Any]],
    *,
    chunk_size: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    if not rows:
        return 0
    chunk = chunk_size or config.GAP_LIFECYCLE_UPSERT_CHUNK
    sql = """INSERT INTO limitation_resolution_signals
               (limitation_id, signal_type, anchor_pmid, followup_pmid,
                anchor_year, followup_year, shared_entities, confidence)
               VALUES (?,?,?,?,?,?,?,?)"""

    def _tuple(r: dict[str, Any]) -> tuple:
        return (
            r["limitation_id"],
            r["signal_type"],
            r.get("anchor_pmid"),
            r.get("followup_pmid"),
            r.get("anchor_year"),
            r.get("followup_year"),
            r.get("shared_entities"),
            r.get("confidence", 0.5),
        )

    total = len(rows)
    with get_conn() as conn:
        for start in range(0, total, chunk):
            batch = rows[start : start + chunk]
            conn.executemany(sql, [_tuple(r) for r in batch])
            if on_progress:
                on_progress(min(start + len(batch), total), total)
    return total


def get_limitation_temporal_rows(
    focus: str | None = None,
    temporal_status: str | None = None,
    temporal_statuses: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if focus:
        clauses.append("LOWER(limitation_name) LIKE LOWER(?)")
        params.append(f"%{focus}%")
    if temporal_statuses:
        placeholders = ",".join("?" * len(temporal_statuses))
        clauses.append(f"temporal_status IN ({placeholders})")
        params.extend(temporal_statuses)
    elif temporal_status:
        clauses.append("temporal_status = ?")
        params.append(temporal_status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    lim = f" LIMIT {int(limit)}" if limit else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT limitation_id, limitation_name, first_year, last_year,
                       paper_cnt, asserted_cnt, hypothesized_cnt, early_cnt,
                       recent_cnt, recent_ratio, temporal_status,
                       avg_cite, avg_cite_per_year, impact_tier, computed_at
                FROM limitation_temporal {where}
                ORDER BY paper_cnt DESC, recent_ratio DESC{lim}""",
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def get_limitation_resolution_rows(
    limitation_id: int | None = None,
    signal_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if limitation_id is not None:
        clauses.append("limitation_id = ?")
        params.append(limitation_id)
    if signal_type:
        clauses.append("signal_type = ?")
        params.append(signal_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    lim = f" LIMIT {int(limit)}" if limit else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT id, limitation_id, signal_type, anchor_pmid, followup_pmid,
                       anchor_year, followup_year, shared_entities, confidence
                FROM limitation_resolution_signals {where}
                ORDER BY confidence DESC, followup_year DESC{lim}""",
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def limitation_lifecycle_stats() -> dict[str, int]:
    with get_conn() as conn:
        return {
            "limitation_temporal": conn.execute(
                "SELECT COUNT(*) FROM limitation_temporal"
            ).fetchone()[0],
            "persistent": conn.execute(
                "SELECT COUNT(*) FROM limitation_temporal WHERE temporal_status='persistent'"
            ).fetchone()[0],
            "declining": conn.execute(
                "SELECT COUNT(*) FROM limitation_temporal WHERE temporal_status='declining'"
            ).fetchone()[0],
            "emerging": conn.execute(
                "SELECT COUNT(*) FROM limitation_temporal WHERE temporal_status='emerging'"
            ).fetchone()[0],
            "resolution_signals": conn.execute(
                "SELECT COUNT(*) FROM limitation_resolution_signals"
            ).fetchone()[0],
            "topic_followup_moderate": conn.execute(
                """SELECT COUNT(DISTINCT limitation_id)
                   FROM limitation_resolution_signals
                   WHERE signal_type='topic_followup' AND confidence >= 0.7"""
            ).fetchone()[0],
        }


def upsert_weekly_hotspot_run(
    week_id: str,
    *,
    window_days: int,
    prior_window_days: int,
    papers_ingested: int,
    report_path: str = "",
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO weekly_hotspot_runs
               (week_id, window_days, prior_window_days, papers_ingested, report_path, snapshot_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(week_id) DO UPDATE SET
                 window_days=excluded.window_days,
                 prior_window_days=excluded.prior_window_days,
                 papers_ingested=excluded.papers_ingested,
                 report_path=excluded.report_path,
                 snapshot_at=CURRENT_TIMESTAMP""",
            (week_id, window_days, prior_window_days, papers_ingested, report_path),
        )


def replace_weekly_hotspot_snapshots(week_id: str, rows: list[dict[str, Any]]) -> int:
    """Replace all snapshot rows for a week. Returns rows written."""
    with get_conn() as conn:
        conn.execute("DELETE FROM weekly_hotspot_snapshots WHERE week_id=?", (week_id,))
        if not rows:
            return 0
        conn.executemany(
            """INSERT INTO weekly_hotspot_snapshots
               (week_id, board, item_key, entity_type, rank_pos,
                recent_cnt, prior_cnt, velocity, emerging_score,
                avg_cite, avg_if, gap_phase, top_pmids)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    week_id,
                    r["board"],
                    r["item_key"],
                    r.get("entity_type"),
                    r.get("rank_pos"),
                    r.get("recent_cnt"),
                    r.get("prior_cnt"),
                    r.get("velocity"),
                    r.get("emerging_score"),
                    r.get("avg_cite"),
                    r.get("avg_if"),
                    r.get("gap_phase"),
                    r.get("top_pmids"),
                )
                for r in rows
            ],
        )
        return len(rows)


def get_weekly_hotspot_snapshots(
    week_id: str,
    board: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["week_id = ?"]
    params: list[Any] = [week_id]
    if board:
        clauses.append("board = ?")
        params.append(board)
    where = " AND ".join(clauses)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT week_id, board, item_key, entity_type, rank_pos,
                       recent_cnt, prior_cnt, velocity, emerging_score,
                       avg_cite, avg_if, gap_phase, top_pmids
                FROM weekly_hotspot_snapshots
                WHERE {where}
                ORDER BY board, rank_pos ASC, emerging_score DESC""",
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def replace_paper_improvement_suggestions(pmid: str, rows: list[dict[str, Any]]) -> int:
    """Supersede prior active rows for pmid, then insert new active rows. Returns insert count."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE paper_improvement_suggestions
               SET status='superseded'
               WHERE source_pmid=? AND COALESCE(status, 'active')='active'""",
            (pmid,),
        )
        n = 0
        for row in rows:
            conn.execute(
                """INSERT INTO paper_improvement_suggestions
                   (source_pmid, limitation_entity_id, action_type, suggestion,
                    evidence_quote, evidence_section, grounding, confidence,
                    status, extraction_pass)
                   VALUES (?,?,?,?,?,?,?,?, 'active', 'fulltext_reconcile')""",
                (
                    pmid,
                    row.get("limitation_entity_id"),
                    row["action_type"],
                    row["suggestion"],
                    row.get("evidence_quote") or "",
                    row.get("evidence_section") or "",
                    row["grounding"],
                    float(row.get("confidence") if row.get("confidence") is not None else 0.5),
                ),
            )
            n += 1
        return n


def list_active_improvement_suggestions(
    pmid: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if pmid:
            rows = conn.execute(
                """SELECT s.*, e.name AS limitation_name
                   FROM paper_improvement_suggestions s
                   LEFT JOIN entities e ON s.limitation_entity_id = e.id
                   WHERE s.source_pmid=? AND COALESCE(s.status, 'active')='active'
                   ORDER BY s.confidence DESC, s.id DESC
                   LIMIT ?""",
                (pmid, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT s.*, e.name AS limitation_name
                   FROM paper_improvement_suggestions s
                   LEFT JOIN entities e ON s.limitation_entity_id = e.id
                   WHERE COALESCE(s.status, 'active')='active'
                   ORDER BY s.confidence DESC, s.id DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def list_active_improvement_suggestions_for_limitations(
    names: list[str],
    limit: int = 50,
) -> list[dict[str, Any]]:
    cleaned = [str(n).strip() for n in names if n and str(n).strip()]
    if not cleaned:
        return []
    placeholders = ",".join("?" * len(cleaned))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT s.source_pmid, e.name AS limitation_name,
                       s.action_type, s.suggestion, s.grounding, s.evidence_quote
                FROM paper_improvement_suggestions s
                LEFT JOIN entities e ON s.limitation_entity_id = e.id
                WHERE COALESCE(s.status, 'active')='active'
                  AND e.name IN ({placeholders})
                ORDER BY s.confidence DESC, s.id DESC
                LIMIT ?""",
            (*cleaned, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_weekly_hotspot_weeks(limit: int = 12) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT week_id FROM weekly_hotspot_runs
               ORDER BY snapshot_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [r["week_id"] for r in rows]


def weekly_hotspot_stats() -> dict[str, int]:
    with get_conn() as conn:
        return {
            "hotspot_runs": conn.execute(
                "SELECT COUNT(*) FROM weekly_hotspot_runs"
            ).fetchone()[0],
            "hotspot_snapshot_rows": conn.execute(
                "SELECT COUNT(*) FROM weekly_hotspot_snapshots"
            ).fetchone()[0],
        }


def insert_ops_run(
    *,
    week_id: str,
    focus_raw: str | None,
    focus_key: str,
    source: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO ops_runs
               (week_id, focus_raw, focus_key, source, started_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (week_id, focus_raw, focus_key, source),
        )
        return int(cur.lastrowid)


def update_ops_run_finalize(
    run_id: int,
    *,
    gap_report_path: str = "",
    hotspot_week_id: str = "",
    proposal_report_path: str = "",
    validation_status: str = "",
    debate_session_id: str = "",
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE ops_runs SET
               finished_at=CURRENT_TIMESTAMP,
               gap_report_path=COALESCE(NULLIF(?, ''), gap_report_path),
               hotspot_week_id=COALESCE(NULLIF(?, ''), hotspot_week_id),
               proposal_report_path=COALESCE(NULLIF(?, ''), proposal_report_path),
               validation_status=COALESCE(NULLIF(?, ''), validation_status),
               debate_session_id=COALESCE(NULLIF(?, ''), debate_session_id)
               WHERE run_id=?""",
            (
                gap_report_path,
                hotspot_week_id,
                proposal_report_path,
                validation_status,
                debate_session_id,
                run_id,
            ),
        )


def insert_ops_gap_items(run_id: int, items: list[dict[str, Any]]) -> int:
    with get_conn() as conn:
        for it in items:
            conn.execute(
                """INSERT INTO ops_gap_items
                   (run_id, rank_pos, title, research_question, fingerprint,
                    section_md, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    it.get("rank_pos"),
                    it["title"],
                    it.get("research_question"),
                    it.get("fingerprint"),
                    it.get("section_md"),
                    it.get("status") or "reported",
                ),
            )
        return len(items)


def insert_ops_proposal(
    run_id: int,
    *,
    gap_item_id: int | None = None,
    proposal_path: str = "",
    proposal_md: str = "",
    feasibility_score: float | None = None,
    critic_score: float | None = None,
    status: str = "",
    target_difficulty: str | None = None,
    assessed_difficulty: str | None = None,
    difficulty_delta: int | None = None,
    difficulty_breakdown_json: str | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO ops_proposals
               (run_id, gap_item_id, proposal_path, proposal_md,
                feasibility_score, critic_score, status,
                target_difficulty, assessed_difficulty, difficulty_delta,
                difficulty_breakdown_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                gap_item_id,
                proposal_path or None,
                proposal_md or None,
                feasibility_score,
                critic_score,
                status or None,
                target_difficulty,
                assessed_difficulty,
                difficulty_delta,
                difficulty_breakdown_json,
            ),
        )
        return int(cur.lastrowid)


def fetch_recent_ops_runs(focus_key: str, limit: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT run_id, week_id, focus_raw, focus_key, source,
                      started_at, finished_at, hotspot_week_id,
                      gap_report_path, proposal_report_path,
                      validation_status, debate_session_id
               FROM ops_runs
               WHERE focus_key=? AND finished_at IS NOT NULL
                 AND (validation_status IS NULL OR validation_status='evidence_checked')
                 AND EXISTS (
                     SELECT 1 FROM ops_gap_items g WHERE g.run_id=ops_runs.run_id
                 )
               ORDER BY finished_at DESC, run_id DESC
               LIMIT ?""",
            (focus_key, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_ops_gap_items_for_runs(run_ids: list[int]) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    placeholders = ",".join("?" * len(run_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT id, run_id, rank_pos, title, research_question,
                       fingerprint, section_md, status
                FROM ops_gap_items
                WHERE run_id IN ({placeholders})
                ORDER BY run_id DESC, rank_pos ASC""",
            tuple(run_ids),
        ).fetchall()
    return [dict(r) for r in rows]


def update_ops_run_hotspot(run_id: int, hotspot_week_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE ops_runs SET hotspot_week_id=? WHERE run_id=?",
            (hotspot_week_id, run_id),
        )


def find_ops_run_by_week_focus(week_id: str, focus_key: str) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT run_id FROM ops_runs
               WHERE week_id=? AND focus_key=?
               ORDER BY COALESCE(finished_at, started_at) DESC, run_id DESC
               LIMIT 1""",
            (week_id, focus_key),
        ).fetchone()
    return int(row["run_id"]) if row else None


def find_ops_gap_items_by_run(run_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, run_id, rank_pos, title, research_question,
                      fingerprint, status
               FROM ops_gap_items
               WHERE run_id=?
               ORDER BY rank_pos ASC""",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_ops_run_proposal_path(run_id: int, proposal_report_path: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE ops_runs SET
               proposal_report_path=COALESCE(NULLIF(?, ''), proposal_report_path)
               WHERE run_id=?""",
            (proposal_report_path, run_id),
        )


def insert_debate_session(
    *,
    session_id: str,
    focus_raw: str | None,
    focus_key: str,
    max_rounds: int,
    top_n: int,
    state_json: str,
    model: str = "",
    prompt_version: str = "",
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO debate_sessions
               (session_id, focus_raw, focus_key, status, current_round,
                next_role, max_rounds, top_n, state_json, model, prompt_version)
               VALUES (?, ?, ?, 'running', 0, 'optimist', ?, ?, ?, ?, ?)""",
            (
                session_id,
                focus_raw,
                focus_key,
                max_rounds,
                top_n,
                state_json,
                model or None,
                prompt_version or None,
            ),
        )


def update_debate_session_checkpoint(
    session_id: str,
    *,
    state_json: str,
    current_round: int,
    next_role: str,
    status: str = "running",
    validation_status: str = "",
    final_report: str = "",
) -> None:
    completed = status in {"completed", "failed", "aborted"}
    with get_conn() as conn:
        conn.execute(
            """UPDATE debate_sessions SET
               state_json=?, current_round=?, next_role=?, status=?,
               validation_status=COALESCE(NULLIF(?, ''), validation_status),
               final_report=COALESCE(NULLIF(?, ''), final_report),
               updated_at=CURRENT_TIMESTAMP,
               completed_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE completed_at END
               WHERE session_id=?""",
            (
                state_json,
                current_round,
                next_role or None,
                status,
                validation_status,
                final_report,
                1 if completed else 0,
                session_id,
            ),
        )


def upsert_debate_turn(
    session_id: str,
    *,
    round_no: int,
    role: str,
    input_text: str,
    output_text: str,
    handoff_json: str,
    status: str = "completed",
) -> int:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO debate_turns
               (session_id, round_no, role, input_text, output_text,
                handoff_json, status, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(session_id, round_no, role) DO UPDATE SET
                 input_text=excluded.input_text,
                 output_text=excluded.output_text,
                 handoff_json=excluded.handoff_json,
                 status=excluded.status,
                 completed_at=CURRENT_TIMESTAMP""",
            (
                session_id,
                round_no,
                role,
                input_text,
                output_text,
                handoff_json,
                status,
            ),
        )
        row = conn.execute(
            """SELECT id FROM debate_turns
               WHERE session_id=? AND round_no=? AND role=?""",
            (session_id, round_no, role),
        ).fetchone()
        return int(row["id"])


def insert_debate_tool_event(
    session_id: str,
    *,
    round_no: int,
    role: str,
    event_type: str,
    tool_name: str = "",
    call_id: str = "",
    args_json: str = "",
    result_json: str = "",
    error_text: str = "",
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO debate_tool_events
               (session_id, round_no, role, event_type, tool_name, call_id,
                args_json, result_json, error_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                round_no,
                role,
                event_type,
                tool_name or None,
                call_id or None,
                args_json or None,
                result_json or None,
                error_text or None,
            ),
        )
        return int(cur.lastrowid)


def upsert_debate_candidate(
    session_id: str,
    *,
    candidate_id: str,
    title: str,
    status: str,
    first_round: int,
    last_round: int,
    metadata_json: str = "",
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO debate_candidates
               (session_id, candidate_id, title, status, first_round,
                last_round, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id, candidate_id) DO UPDATE SET
                 title=excluded.title,
                 status=excluded.status,
                 last_round=excluded.last_round,
                 metadata_json=excluded.metadata_json""",
            (
                session_id,
                candidate_id,
                title,
                status,
                first_round,
                last_round,
                metadata_json or None,
            ),
        )


def fetch_debate_session(session_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM debate_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def list_debate_sessions(
    *,
    focus_key: str | None = None,
    limit: int = 20,
    resumable_only: bool = False,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if focus_key is not None:
        where.append("focus_key=?")
        params.append(focus_key)
    if resumable_only:
        where.append("status IN ('running', 'failed', 'aborted')")
    clause = " WHERE " + " AND ".join(where) if where else ""
    params.append(max(1, int(limit)))
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT session_id, focus_raw, focus_key, status, current_round,
                      next_role, max_rounds, top_n, validation_status,
                      prompt_version, created_at, updated_at, completed_at
               FROM debate_sessions"""
            + clause
            + " ORDER BY updated_at DESC, created_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def reopen_debate_session(session_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE debate_sessions SET status='running',
               completed_at=NULL, updated_at=CURRENT_TIMESTAMP
               WHERE session_id=?""",
            (session_id,),
        )


def fetch_debate_turns(session_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM debate_turns WHERE session_id=?
               ORDER BY round_no, id""",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def fetch_debate_tool_events(session_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM debate_tool_events WHERE session_id=?
               ORDER BY id""",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def insert_idea_session(
    *,
    session_id: str,
    debate_session_id: str | None,
    gap_text: str,
    max_rounds: int,
    state_json: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO idea_sessions
               (session_id, debate_session_id, gap_text, max_rounds, state_json)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, debate_session_id, gap_text, max_rounds, state_json),
        )


def checkpoint_idea_session(
    session_id: str,
    *,
    round_no: int,
    role: str,
    next_role: str,
    output_text: str,
    state_json: str,
    status: str = "running",
) -> None:
    completed = status in {"completed", "failed", "aborted"}
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO idea_turns
               (session_id, round_no, role, output_text, state_json)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_id, round_no, role) DO UPDATE SET
                 output_text=excluded.output_text,
                 state_json=excluded.state_json,
                 created_at=CURRENT_TIMESTAMP""",
            (session_id, round_no, role, output_text, state_json),
        )
        conn.execute(
            """UPDATE idea_sessions SET current_round=?, next_role=?,
               state_json=?, status=?, updated_at=CURRENT_TIMESTAMP,
               completed_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE completed_at END
               WHERE session_id=?""",
            (
                round_no,
                next_role or None,
                state_json,
                status,
                1 if completed else 0,
                session_id,
            ),
        )


def fetch_idea_session(session_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM idea_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    return dict(row) if row else None
