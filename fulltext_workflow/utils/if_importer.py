"""Import journal Impact Factor data into fulltext_workflow SQLite."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd
from rapidfuzz import fuzz, process

import config
from db.schema import (
    get_all_journals,
    get_conn,
    link_paper_journal,
    update_journal_if,
    upsert_journal,
)

_COL_ALIASES: dict[str, list[str]] = {
    "name": ["journal name", "journal", "full name", "name", "title", "期刊名称", "期刊"],
    "abbr": ["abbreviation", "abbr", "iso abbreviation", "缩写"],
    "issn": ["issn", "issn (print)", "print issn", "p-issn"],
    "eissn": ["eissn", "e-issn", "electronic issn", "online issn"],
    "if": ["impact factor", "if", "jif", "2024jif", "2023jif", "影响因子"],
    "if_year": ["if year", "year", "jif year", "年份"],
    "quartile": ["quartile", "jci quartile", "q", "分区", "jcr分区"],
}


def _find_column(df_columns: list[str], aliases: list[str]) -> Optional[str]:
    lower_cols = {c.lower().strip(): c for c in df_columns}
    for alias in aliases:
        if alias.lower() in lower_cols:
            return lower_cols[alias.lower()]
    return None


def _normalize_issn(issn: str) -> str:
    if not issn:
        return ""
    cleaned = str(issn).strip().replace(" ", "").replace("–", "-").replace("—", "-")
    if "-" not in cleaned and len(cleaned) == 8:
        cleaned = cleaned[:4] + "-" + cleaned[4:]
    return cleaned.upper()


def _build_journal_lookup(db_journals):
    by_issn, by_name, by_abbr = {}, {}, {}
    for j in db_journals:
        if j["issn"]:
            by_issn[_normalize_issn(j["issn"])] = j["id"]
        if j["name"]:
            by_name[j["name"].lower().strip()] = j["id"]
        if j["abbr"]:
            by_abbr[j["abbr"].lower().strip()] = j["id"]
    return by_issn, by_name, by_abbr


def _fuzzy_match(query: str, candidates: list[str], threshold: int) -> Optional[str]:
    if not candidates or not query:
        return None
    result = process.extractOne(
        query.lower(),
        [c.lower() for c in candidates],
        scorer=fuzz.token_sort_ratio,
    )
    if result and result[1] >= threshold:
        return candidates[result[2]]
    return None


def _read_file(file_path: str) -> pd.DataFrame:
    path = Path(file_path)
    if path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(file_path, dtype=str)
    for enc in ["utf-8-sig", "utf-8", "gbk", "gb18030", "latin1"]:
        try:
            return pd.read_csv(file_path, dtype=str, encoding=enc)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"Cannot read file: {file_path}")


def import_impact_factors(excel_path: str, if_year: Optional[int] = None) -> None:
    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {excel_path}")

    print(f"[IF Importer] Reading {path.name}...")
    df = _read_file(excel_path)
    df.columns = [str(c).strip() for c in df.columns]

    col_name = _find_column(list(df.columns), _COL_ALIASES["name"])
    col_abbr = _find_column(list(df.columns), _COL_ALIASES["abbr"])
    col_issn = _find_column(list(df.columns), _COL_ALIASES["issn"])
    col_eissn = _find_column(list(df.columns), _COL_ALIASES["eissn"])
    col_if = _find_column(list(df.columns), _COL_ALIASES["if"])
    col_if_year = _find_column(list(df.columns), _COL_ALIASES["if_year"])
    col_quartile = _find_column(list(df.columns), _COL_ALIASES["quartile"])

    if col_name is None or col_if is None:
        raise ValueError(f"Need journal name + IF columns. Found: {list(df.columns)}")

    db_journals = get_all_journals()
    by_issn, by_name, by_abbr = _build_journal_lookup(db_journals)
    name_list = list(by_name.keys())
    matched = inserted = 0

    for _, row in df.iterrows():
        name_val = str(row.get(col_name, "") or "").strip()
        if not name_val or name_val.lower() == "nan":
            continue
        abbr_val = str(row.get(col_abbr, "") or "").strip() if col_abbr else ""
        issn_val = _normalize_issn(str(row.get(col_issn, "") or "")) if col_issn else ""
        eissn_val = _normalize_issn(str(row.get(col_eissn, "") or "")) if col_eissn else ""
        try:
            if_value = float(str(row.get(col_if, "") or "").replace(",", "."))
        except ValueError:
            continue
        year_raw = str(row.get(col_if_year, "") or "").strip() if col_if_year else ""
        try:
            year_int = int(float(year_raw)) if year_raw else (if_year or 2024)
        except ValueError:
            year_int = if_year or 2024
        quartile_val = str(row.get(col_quartile, "") or "").strip() if col_quartile else ""

        journal_id = None
        if issn_val and issn_val in by_issn:
            journal_id = by_issn[issn_val]
        elif eissn_val and eissn_val in by_issn:
            journal_id = by_issn[eissn_val]
        elif name_val.lower() in by_name:
            journal_id = by_name[name_val.lower()]
        elif abbr_val and abbr_val.lower() in by_abbr:
            journal_id = by_abbr[abbr_val.lower()]
        else:
            best = _fuzzy_match(name_val, name_list, config.JOURNAL_FUZZY_THRESHOLD)
            if best:
                journal_id = by_name[best.lower()]

        if journal_id is not None:
            update_journal_if(journal_id, if_value, year_int, quartile_val)
            matched += 1
        else:
            journal_id = upsert_journal(name_val, abbr_val, issn_val)
            update_journal_if(journal_id, if_value, year_int, quartile_val)
            by_name[name_val.lower()] = journal_id
            if issn_val:
                by_issn[issn_val] = journal_id
            name_list.append(name_val.lower())
            inserted += 1

    print(f"[IF Importer] Done: {matched} matched, {inserted} newly inserted.")
    _link_papers_to_journals()


def _link_papers_to_journals() -> None:
    with get_conn() as conn:
        papers = conn.execute(
            "SELECT id, journal_name, journal_abbr, issn FROM papers WHERE journal_id IS NULL"
        ).fetchall()
    db_journals = get_all_journals()
    by_issn, by_name, by_abbr = _build_journal_lookup(db_journals)
    updated = 0
    for paper in papers:
        jid = None
        issn = _normalize_issn(paper["issn"] or "")
        if issn and issn in by_issn:
            jid = by_issn[issn]
        elif (paper["journal_name"] or "").lower() in by_name:
            jid = by_name[(paper["journal_name"] or "").lower()]
        elif (paper["journal_abbr"] or "").lower() in by_abbr:
            jid = by_abbr[(paper["journal_abbr"] or "").lower()]
        if jid:
            link_paper_journal(paper["id"], jid)
            updated += 1
    print(f"[IF Importer] Linked {updated} paper→journal FKs.")
