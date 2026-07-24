from analysis.difficulty_scoring import (
    assess_implementation_difficulty,
    difficulty_color,
    difficulty_ordinal,
    fangxin_tier,
    load_supporting_papers_by_pmids,
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


def test_load_public_datasets_from_v03_recommended(monkeypatch):
    from analysis import difficulty_scoring as ds

    def fake_assess(keyword: str) -> dict:
        return {
            "recommended_public": [
                {"dataset": "Camelyon17", "used_by_papers": 5, "alias_hit": True},
            ],
            "other_datasets": [
                {"dataset": "HospitalX", "access_class": "private"},
            ],
        }

    monkeypatch.setattr(
        "analysis.public_dataset_feasibility.assess_public_datasets",
        fake_assess,
    )
    assert ds.load_public_datasets_for_keyword("npc") == ["Camelyon17"]


def test_load_supporting_papers_empty_when_no_pmids(monkeypatch):
    from analysis import difficulty_scoring as ds

    monkeypatch.setattr(
        "analysis.focus_filter.resolve_topic_pmids",
        lambda kw: ([], "no_match"),
    )
    assert ds.load_supporting_papers_for_keyword("nothing") == []


def test_load_supporting_papers_joins_journal_fields(monkeypatch):
    from analysis import difficulty_scoring as ds

    monkeypatch.setattr(
        "analysis.focus_filter.resolve_topic_pmids",
        lambda kw: (["92000001"], "full_phrase"),
    )

    captured: dict = {}

    class FakeConn:
        def execute(self, sql, params=()):
            captured["sql"] = sql
            captured["params"] = params
            return self

        def fetchall(self):
            return [
                {
                    "pmid": "92000001",
                    "title": "Test paper",
                    "year": 2025,
                    "journal_name": "Nature",
                    "journal_abbr": "Nat",
                    "citation_count": 10,
                    "quartile": "Q1",
                    "impact_factor": 12.0,
                }
            ]

    class FakeCtx:
        def __enter__(self):
            return FakeConn()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("db.schema.get_conn", lambda: FakeCtx())

    rows = ds.load_supporting_papers_for_keyword("npc", limit=5)
    assert len(rows) == 1
    assert rows[0]["pmid"] == "92000001"
    assert rows[0]["quartile"] == "Q1"
    assert rows[0]["impact_factor"] == 12.0
    assert "left join journals" in captured["sql"].lower()
    assert captured["params"] == ("92000001", 5)


def test_load_supporting_papers_by_pmids_joins_journal_fields(monkeypatch):
    captured: dict = {}

    class FakeConn:
        def execute(self, sql, params=()):
            captured["sql"] = sql
            captured["params"] = params
            return self

        def fetchall(self):
            return [
                {
                    "pmid": "92000002",
                    "title": "Gap-linked paper",
                    "quartile": "Q1",
                    "impact_factor": 14.0,
                }
            ]

    class FakeCtx:
        def __enter__(self):
            return FakeConn()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("db.schema.get_conn", lambda: FakeCtx())

    rows = load_supporting_papers_by_pmids(["92000002", "92000003"], limit=1)

    assert rows[0]["pmid"] == "92000002"
    assert rows[0]["quartile"] == "Q1"
    assert "left join journals" in captured["sql"].lower()
    assert captured["params"] == ("92000002", "92000003", 1)
