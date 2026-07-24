"""Unit tests for PubMed PubDate parsing + date_precision."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fetcher.pubmed_fetcher import _parse_date  # noqa: E402


def _article_with_pubdate(inner_xml: str) -> ET.Element:
    root = ET.fromstring(
        f"<Article><Journal><JournalIssue><PubDate>{inner_xml}</PubDate>"
        f"</JournalIssue></Journal></Article>"
    )
    return root


def test_parse_date_day_precision():
    art = _article_with_pubdate("<Year>2020</Year><Month>Sep</Month><Day>18</Day>")
    pub_date, year, precision = _parse_date(art)
    assert pub_date == "2020-09-18"
    assert year == 2020
    assert precision == "day"


def test_parse_date_month_precision():
    art = _article_with_pubdate("<Year>2019</Year><Month>12</Month>")
    pub_date, year, precision = _parse_date(art)
    assert pub_date == "2019-12-01"
    assert year == 2019
    assert precision == "month"


def test_parse_date_year_precision():
    art = _article_with_pubdate("<Year>2018</Year>")
    pub_date, year, precision = _parse_date(art)
    assert pub_date == "2018-01-01"
    assert year == 2018
    assert precision == "year"


def test_parse_date_missing_pubdate():
    art = ET.fromstring("<Article><ArticleTitle>x</ArticleTitle></Article>")
    pub_date, year, precision = _parse_date(art)
    assert pub_date == ""
    assert year == 0
    assert precision == "unknown"


def test_parse_date_medline_date_year():
    art = _article_with_pubdate("<MedlineDate>2020 Spring</MedlineDate>")
    pub_date, year, precision = _parse_date(art)
    assert year == 2020
    assert pub_date == "2020-03-01"
    assert precision == "month"
