"""Unit tests for fulltext reconcile assemble/parse helpers."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    get_conn,
    init_db,
    insert_relation,
    upsert_entity,
    upsert_paper,
)


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_assemble_prefers_core_sections_and_truncates():
    from extractor.fulltext_reconcile import assemble_reconcile_text

    sections = [
        {"section_type": "introduction", "content": "INTRO " * 5000},
        {"section_type": "methods", "content": "METHODS " * 100},
        {"section_type": "discussion", "content": "DISC " * 100},
        {"section_type": "limitations", "content": "LIM " * 50},
    ]
    text = assemble_reconcile_text(sections, max_chars=2000)
    assert "METHODS" in text
    assert "LIM" in text
    assert len(text) <= 2000


def test_parse_reconcile_payload_normalizes():
    from extractor.fulltext_reconcile import parse_reconcile_payload

    raw = {
        "datasets": [
            {
                "name": "PubMed",
                "access": "public",
                "action": "drop",
                "reason": "platform",
            }
        ],
        "bindings": [
            {"method": "CNN", "disease": "breast cancer", "dataset": "", "quote": "q"}
        ],
        "limitations": [
            {"canonical": "small sample size", "merges": ["small n"], "quote": "q2"}
        ],
    }
    p = parse_reconcile_payload(raw)
    assert p["datasets"][0]["action"] == "drop"
    assert p["bindings"][0]["dataset"] == ""
    assert p["limitations"][0]["canonical"] == "small sample size"


def test_apply_reconcile_payload(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "12345678"
    paper_id = upsert_paper({"pmid": pmid, "title": "Reconcile test paper"})

    pubmed_id = upsert_entity("pubmed", "Dataset")
    camelyon_id = upsert_entity("camelyon16", "Dataset", access_class="unknown")
    small_n_id = upsert_entity("small n", "Limitation")
    cohort_id = upsert_entity("limited cohort", "Limitation")

    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        pubmed_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        camelyon_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    insert_relation(
        "Paper",
        paper_id,
        "REPORTS_LIMITATION",
        "Limitation",
        small_n_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    insert_relation(
        "Paper",
        paper_id,
        "REPORTS_LIMITATION",
        "Limitation",
        cohort_id,
        source_pmid=pmid,
        extraction_pass="section",
    )

    payload = {
        "datasets": [
            {"name": "PubMed", "access": "public", "action": "drop", "reason": "platform"},
            {"name": "camelyon16", "access": "public", "action": "keep", "reason": "benchmark"},
        ],
        "limitations": [
            {
                "canonical": "small sample size",
                "merges": ["small n", "limited cohort"],
                "quote": "small cohort limits generalizability",
            }
        ],
        "bindings": [
            {
                "method": "CNN",
                "disease": "breast cancer",
                "dataset": "camelyon16",
                "quote": "CNN on Camelyon16 for breast cancer",
            }
        ],
    }
    apply_reconcile_payload(paper_id, pmid, payload)

    with get_conn() as conn:
        active_datasets = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET' AND r.status='active'""",
            (pmid,),
        ).fetchall()
        pubmed_row = conn.execute(
            """SELECT r.status, r.superseded_by FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND e.name='pubmed'""",
            (pmid,),
        ).fetchone()
        active_lims = conn.execute(
            """SELECT e.name, r.extraction_pass, r.evidence_section
               FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='REPORTS_LIMITATION'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
        superseded_lims = conn.execute(
            """SELECT e.name, r.superseded_by FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='REPORTS_LIMITATION'
                 AND r.status='superseded'""",
            (pmid,),
        ).fetchall()
        bind_cnt = conn.execute(
            "SELECT COUNT(*) FROM paper_entity_bindings WHERE source_pmid=?",
            (pmid,),
        ).fetchone()[0]
        camelyon_access = conn.execute(
            "SELECT access_class FROM entities WHERE id=?", (camelyon_id,)
        ).fetchone()["access_class"]

    assert {r["name"] for r in active_datasets} == {"camelyon16"}
    assert pubmed_row["status"] == "superseded"
    assert pubmed_row["superseded_by"] is None
    assert len(active_lims) == 1
    assert active_lims[0]["name"] == "small sample size"
    assert active_lims[0]["extraction_pass"] == "fulltext_reconcile"
    assert active_lims[0]["evidence_section"] == "fulltext_reconcile"
    assert len(superseded_lims) == 2
    canonical_id = upsert_entity("small sample size", "Limitation")
    assert all(r["superseded_by"] == canonical_id for r in superseded_lims)
    assert bind_cnt == 1
    assert camelyon_access == "public"


def test_apply_platform_keep_and_binding_do_not_pollute(monkeypatch):
    """Pass 2 apply must treat platform keep/binding as drop — no active edges."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "87654321"
    paper_id = upsert_paper({"pmid": pmid, "title": "Platform pollution test"})

    pubmed_id = upsert_entity("pubmed", "Dataset")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        pubmed_id,
        source_pmid=pmid,
        extraction_pass="section",
    )

    payload = {
        "datasets": [
            {"name": "PubMed", "access": "public", "action": "keep", "reason": "mistake"},
        ],
        "bindings": [
            {
                "method": "CNN",
                "disease": "breast cancer",
                "dataset": "PubMed",
                "quote": "CNN trained on PubMed",
            }
        ],
        "limitations": [],
    }
    apply_reconcile_payload(paper_id, pmid, payload)

    with get_conn() as conn:
        active_datasets = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
        pubmed_status = conn.execute(
            """SELECT r.status FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND e.name='pubmed'""",
            (pmid,),
        ).fetchone()["status"]
        bind_rows = conn.execute(
            """SELECT b.dataset_entity_id, e.name
               FROM paper_entity_bindings b
               LEFT JOIN entities e ON e.id = b.dataset_entity_id
               WHERE b.source_pmid=?""",
            (pmid,),
        ).fetchall()

    assert active_datasets == []
    assert pubmed_status == "superseded"
    assert len(bind_rows) == 1
    assert bind_rows[0]["dataset_entity_id"] is None


def test_apply_dataset_merge_supersedes_aliases(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "11223344"
    paper_id = upsert_paper({"pmid": pmid, "title": "Dataset merge test"})

    alias_a_id = upsert_entity("camelyon 16", "Dataset")
    alias_b_id = upsert_entity("camelyon16 dataset", "Dataset")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        alias_a_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        alias_b_id,
        source_pmid=pmid,
        extraction_pass="section",
    )

    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "camelyon16",
                    "access": "public",
                    "action": "merge",
                    "reason": "alias collapse",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
    )

    with get_conn() as conn:
        active = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
        superseded = conn.execute(
            """SELECT e.name, r.superseded_by FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                 AND r.status='superseded'""",
            (pmid,),
        ).fetchall()

    assert {r["name"] for r in active} == {"camelyon16"}
    assert len(active) == 1
    assert {r["name"] for r in superseded} == {"camelyon 16", "camelyon16 dataset"}
    canon_id = upsert_entity("camelyon16", "Dataset")
    assert all(r["superseded_by"] == canon_id for r in superseded)


def test_review_study_type_clears_all_datasets(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "66778899"
    paper_id = upsert_paper({"pmid": pmid, "title": "A systematic review"})
    tcga_id = upsert_entity("tcga", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        tcga_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {"name": "tcga", "access": "public", "action": "keep", "reason": "survey"}
            ],
            "bindings": [],
            "limitations": [],
        },
        study_type="review",
    )
    with get_conn() as conn:
        active = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='USES_DATASET' AND status='active'""",
            (pmid,),
        ).fetchone()[0]
        superseded = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='USES_DATASET' AND status='superseded'""",
            (pmid,),
        ).fetchone()[0]
    assert active == 0
    assert superseded == 1


def test_parse_dataset_role_and_survey_fields():
    from extractor.fulltext_reconcile import parse_reconcile_payload

    raw = {
        "datasets": [
            {
                "name": "camelyon16",
                "access": "public",
                "action": "keep",
                "role": "release",
                "reason": "we release",
            }
        ],
        "surveyed_methods": [{"name": "clam", "quote": "CLAM is widely used"}],
        "covered_diseases": [{"name": "breast cancer", "quote": "we cover breast cancer"}],
        "bindings": [],
        "limitations": [],
    }
    p = parse_reconcile_payload(raw)
    assert p["datasets"][0]["role"] == "release"
    assert p["surveyed_methods"][0]["name"] == "clam"


def test_review_apply_clears_datasets_and_writes_survey(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "66778900"
    paper_id = upsert_paper({"pmid": pmid, "title": "A systematic review with survey"})
    tcga_id = upsert_entity("tcga", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        tcga_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {"name": "tcga", "access": "public", "action": "keep", "reason": "survey"}
            ],
            "surveyed_methods": [{"name": "clam", "quote": "CLAM is widely used"}],
            "bindings": [],
            "limitations": [],
        },
        study_type="review",
    )
    with get_conn() as conn:
        active = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='USES_DATASET' AND status='active'""",
            (pmid,),
        ).fetchone()[0]
        superseded = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='USES_DATASET' AND status='superseded'""",
            (pmid,),
        ).fetchone()[0]
        surveys = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='SURVEYS_METHOD'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
    assert active == 0
    assert superseded == 1
    assert {r["name"] for r in surveys} == {"clam"}


def test_pass2_keep_cannot_invent_survey_dataset(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "44556677"
    paper_id = upsert_paper({"pmid": pmid, "title": "Algorithm paper"})
    cam_id = upsert_entity("camelyon16", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        cam_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "inbreast",
                    "access": "public",
                    "action": "keep",
                    "reason": "mentioned in related work only",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
        study_type="ai_algorithm",
    )
    with get_conn() as conn:
        names = {
            r["name"]
            for r in conn.execute(
                """SELECT e.name FROM relations r
                   JOIN entities e ON e.id=r.object_id
                   WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                     AND r.status='active'""",
                (pmid,),
            )
        }
    assert names == {"camelyon16"}


def test_drop_cannot_remove_public_alias(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "55667788"
    paper_id = upsert_paper({"pmid": pmid, "title": "Protect public alias"})
    tcga_id = upsert_entity("tcga", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        tcga_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "TCGA",
                    "access": "unknown",
                    "action": "drop",
                    "reason": "llm mistake",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
    )
    with get_conn() as conn:
        active = conn.execute(
            """SELECT e.name, r.status FROM relations r
               JOIN entities e ON e.id=r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET' AND r.status='active'""",
            (pmid,),
        ).fetchall()
    assert {r["name"] for r in active} == {"tcga"}


def test_release_keep_coexists_with_uses_dataset(monkeypatch):
    """dataset_benchmark + role=release adds RELEASES_DATASET without superseding USES."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "77889900"
    paper_id = upsert_paper({"pmid": pmid, "title": "Release coexistence"})
    ds_id = upsert_entity("camelyon16", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        ds_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "camelyon16",
                    "access": "public",
                    "action": "keep",
                    "role": "release",
                    "reason": "we release this dataset",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
        study_type="dataset_benchmark",
    )
    with get_conn() as conn:
        uses = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='USES_DATASET' AND status='active'""",
            (pmid,),
        ).fetchone()[0]
        releases = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='RELEASES_DATASET' AND status='active'""",
            (pmid,),
        ).fetchone()[0]
    assert uses == 1
    assert releases == 1


def test_release_merge_coexists_with_uses_dataset(monkeypatch):
    """dataset_benchmark role=release merge must not supersede USES on same object."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "77889901"
    paper_id = upsert_paper({"pmid": pmid, "title": "Release merge coexistence"})
    alias_id = upsert_entity("camelyon 16", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        alias_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "camelyon16",
                    "access": "public",
                    "action": "merge",
                    "role": "release",
                    "reason": "alias collapse into release",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
        study_type="dataset_benchmark",
    )
    with get_conn() as conn:
        uses_active = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
        releases_active = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='RELEASES_DATASET'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
    assert {r["name"] for r in uses_active} == {"camelyon 16"}
    assert {r["name"] for r in releases_active} == {"camelyon16"}


def test_ai_algorithm_release_role_does_not_create_releases(monkeypatch):
    """ai_algorithm enable_new is empty: role=release must not write RELEASES_DATASET."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "77889904"
    paper_id = upsert_paper({"pmid": pmid, "title": "AI algo no release"})
    ds_id = upsert_entity("camelyon16", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        ds_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "camelyon16",
                    "access": "public",
                    "action": "keep",
                    "role": "release",
                    "reason": "llm wrongly labeled release",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
        study_type="ai_algorithm",
    )
    with get_conn() as conn:
        releases = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='RELEASES_DATASET' AND status='active'""",
            (pmid,),
        ).fetchone()[0]
        uses = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='USES_DATASET' AND status='active'""",
            (pmid,),
        ).fetchone()[0]
    assert releases == 0
    assert uses == 1


def test_pretrain_keep_coexists_on_foundation_model(monkeypatch):
    """foundation_model + role=pretrain adds PRETRAINS_ON without superseding USES."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "77889905"
    paper_id = upsert_paper({"pmid": pmid, "title": "Pretrain coexistence"})
    ds_id = upsert_entity("tcga", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        ds_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "tcga",
                    "access": "public",
                    "action": "keep",
                    "role": "pretrain",
                    "reason": "pretraining corpus",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
        study_type="foundation_model",
    )
    with get_conn() as conn:
        uses = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='USES_DATASET' AND status='active'""",
            (pmid,),
        ).fetchone()[0]
        pretrains = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='PRETRAINS_ON' AND status='active'""",
            (pmid,),
        ).fetchone()[0]
    assert uses == 1
    assert pretrains == 1


def test_meta_analysis_pooled_keep_preserves_uses(monkeypatch):
    """meta_analysis keep + experimental + pooled-analysis reason keeps USES under mode=none."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "77889902"
    paper_id = upsert_paper({"pmid": pmid, "title": "Meta pooled keep"})
    ds_id = upsert_entity("tcga", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        ds_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "tcga",
                    "access": "public",
                    "action": "keep",
                    "role": "experimental",
                    "reason": "pooled analysis by the authors of primary cohorts",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
        study_type="meta_analysis",
    )
    with get_conn() as conn:
        active = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
    assert {r["name"] for r in active} == {"tcga"}


def test_review_without_meta_exception_clears_datasets(monkeypatch):
    """review keep without meta pooled/self-analysis exception still clears datasets."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "77889903"
    paper_id = upsert_paper({"pmid": pmid, "title": "Review clears datasets"})
    ds_id = upsert_entity("tcga", "Dataset", access_class="public")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        ds_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "tcga",
                    "access": "public",
                    "action": "keep",
                    "role": "experimental",
                    "reason": "pooled analysis by the authors",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
        study_type="review",
    )
    with get_conn() as conn:
        active = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='USES_DATASET' AND status='active'""",
            (pmid,),
        ).fetchone()[0]
        superseded = conn.execute(
            """SELECT COUNT(*) FROM relations
               WHERE source_pmid=? AND relation='USES_DATASET' AND status='superseded'""",
            (pmid,),
        ).fetchone()[0]
    assert active == 0
    assert superseded == 1


def test_limitation_merge_reactivates_canonical_edge(monkeypatch):
    """If Pass1 already had the canonical edge and merges supersede siblings,
    Pass2 must leave an active canonical (reactivate if needed)."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "99887766"
    paper_id = upsert_paper({"pmid": pmid, "title": "Limitation reactivate"})
    canon_id = upsert_entity("small sample size", "Limitation")
    frag_id = upsert_entity("small n", "Limitation")
    insert_relation(
        "Paper",
        paper_id,
        "REPORTS_LIMITATION",
        "Limitation",
        canon_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    insert_relation(
        "Paper",
        paper_id,
        "REPORTS_LIMITATION",
        "Limitation",
        frag_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    # Simulate a buggy LLM that also lists the canonical in merges.
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [],
            "bindings": [],
            "limitations": [
                {
                    "canonical": "small sample size",
                    "merges": ["small sample size", "small n"],
                    "quote": "n is small",
                }
            ],
        },
    )
    with get_conn() as conn:
        active = conn.execute(
            """SELECT e.name, r.extraction_pass, r.status FROM relations r
               JOIN entities e ON e.id=r.object_id
               WHERE r.source_pmid=? AND r.relation='REPORTS_LIMITATION'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
        superseded = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id=r.object_id
               WHERE r.source_pmid=? AND r.relation='REPORTS_LIMITATION'
                 AND r.status='superseded'""",
            (pmid,),
        ).fetchall()
    assert len(active) == 1
    assert active[0]["name"] == "small sample size"
    assert active[0]["extraction_pass"] == "fulltext_reconcile"
    assert {r["name"] for r in superseded} == {"small n"}
