"""
utils/if_importer.py
Import journal Impact Factor data from an Excel file into the SQLite database.

Expected Excel columns (flexible column name matching):
  - Journal name / full name  (required)
  - Abbreviation / abbr       (optional)
  - ISSN                      (optional, used for precise matching)
  - Impact Factor / IF        (required)
  - IF Year / Year            (optional, defaults to most recent)
  - Quartile / Q              (optional, e.g. Q1/Q2/Q3/Q4)

Matching strategy (priority order):
  1. Exact ISSN match
  2. Exact name match (case-insensitive)
  3. Exact abbreviation match (case-insensitive)
  4. rapidfuzz fuzzy name match (threshold from config)

Unmatched journals are saved to data/unmatched_journals.csv for review.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd
from rapidfuzz import fuzz, process

import config
from utils.db import get_conn, get_all_journals, update_journal_if, upsert_journal, link_paper_journal

# ─────────────────────────────────────────────────────────────────────────────
# Column name aliases (handles various Excel formats)
# ─────────────────────────────────────────────────────────────────────────────

_COL_ALIASES: dict[str, list[str]] = {
    "name":   ["journal name", "journal", "full name", "name", "title",
               "期刊名称", "期刊", "来源期刊"],
    "abbr":   ["abbreviation", "abbr", "iso abbreviation", "缩写", "简称"],
    "issn":   ["issn", "issn (print)", "print issn", "issn号", "p-issn"],
    "eissn":  ["eissn", "e-issn", "electronic issn", "online issn"],
    "if":     ["impact factor", "if", "jif", "2024jif", "2023jif", "2024 jif", "2023 jif",
               "2022 jif", "2024if", "影响因子", "if值"],
    "if_year":["if year", "year", "jif year", "年份", "if年份"],
    "quartile":["quartile", "jci quartile", "q", "分区", "jcr分区", "科院分区"],
}


def _find_column(df_columns: list[str], aliases: list[str]) -> Optional[str]:
    """Return the first df column that matches any alias (case-insensitive)."""
    lower_cols = {c.lower().strip(): c for c in df_columns}
    for alias in aliases:
        if alias.lower() in lower_cols:
            return lower_cols[alias.lower()]
    return None


def _normalize_issn(issn: str) -> str:
    """Normalize ISSN to XXXX-XXXX format."""
    if not issn:
        return ""
    cleaned = str(issn).strip().replace(" ", "").replace("–", "-").replace("—", "-")
    if "-" not in cleaned and len(cleaned) == 8:
        cleaned = cleaned[:4] + "-" + cleaned[4:]
    return cleaned.upper()


# ─────────────────────────────────────────────────────────────────────────────
# Matching helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_journal_lookup(
    db_journals: list[sqlite3.Row],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Build lookup dicts: issn→id, lower_name→id, lower_abbr→id."""
    by_issn: dict[str, int] = {}
    by_name: dict[str, int] = {}
    by_abbr: dict[str, int] = {}
    for j in db_journals:
        if j["issn"]:
            by_issn[_normalize_issn(j["issn"])] = j["id"]
        if j["name"]:
            by_name[j["name"].lower().strip()] = j["id"]
        if j["abbr"]:
            by_abbr[j["abbr"].lower().strip()] = j["id"]
    return by_issn, by_name, by_abbr


def _fuzzy_match(
    query: str,
    candidates: list[str],
    threshold: int,
) -> Optional[str]:
    """Return best fuzzy match above threshold, or None."""
    if not candidates or not query:
        return None
    result = process.extractOne(
        query.lower(),
        [c.lower() for c in candidates],
        scorer=fuzz.token_sort_ratio,
    )
    if result and result[1] >= threshold:
        # Return original casing
        return candidates[result[2]]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main import function
# ─────────────────────────────────────────────────────────────────────────────

def _read_file(file_path: str) -> pd.DataFrame:
    """Read Excel or CSV, auto-detecting encoding for CSV."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(file_path, dtype=str)
    # CSV — try encodings in order
    for enc in ["utf-8-sig", "utf-8", "gbk", "gb18030", "latin1"]:
        try:
            df = pd.read_csv(file_path, dtype=str, encoding=enc)
            print(f"  [IF Importer] CSV encoding detected: {enc}")
            return df
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"Cannot read file with any known encoding: {file_path}")


def import_impact_factors(excel_path: str, if_year: Optional[int] = None) -> None:
    """
    Read IF data from Excel or CSV and update journals table in SQLite.

    Args:
        excel_path: Path to .xlsx/.xls/.csv file.
        if_year:    Override IF year for all records (useful if year column is absent).
    """
    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {excel_path}")

    print(f"[IF Importer] Reading {path.name}...")
    df = _read_file(excel_path)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"  Columns found: {list(df.columns)}")

    # Resolve column names
    col_name     = _find_column(list(df.columns), _COL_ALIASES["name"])
    col_abbr     = _find_column(list(df.columns), _COL_ALIASES["abbr"])
    col_issn     = _find_column(list(df.columns), _COL_ALIASES["issn"])
    col_eissn    = _find_column(list(df.columns), _COL_ALIASES["eissn"])
    col_if       = _find_column(list(df.columns), _COL_ALIASES["if"])
    col_if_year  = _find_column(list(df.columns), _COL_ALIASES["if_year"])
    col_quartile = _find_column(list(df.columns), _COL_ALIASES["quartile"])

    if col_name is None:
        raise ValueError(f"Cannot find journal name column. Available: {list(df.columns)}")
    if col_if is None:
        raise ValueError(f"Cannot find impact factor column. Available: {list(df.columns)}")

    print(f"  Mapped columns -> name:{col_name}, if:{col_if}, issn:{col_issn}, "
          f"eissn:{col_eissn}, abbr:{col_abbr}, year:{col_if_year}, quartile:{col_quartile}")

    # Load existing DB journals
    db_journals = get_all_journals()
    by_issn, by_name, by_abbr = _build_journal_lookup(db_journals)
    name_list = list(by_name.keys())

    matched = 0
    inserted = 0
    unmatched: list[dict] = []

    for _, row in df.iterrows():
        name_val = str(row.get(col_name, "") or "").strip()
        if not name_val or name_val.lower() in ("nan", ""):
            continue

        abbr_val     = str(row.get(col_abbr, "") or "").strip() if col_abbr else ""
        issn_val     = _normalize_issn(str(row.get(col_issn, "") or "")) if col_issn else ""
        eissn_val    = _normalize_issn(str(row.get(col_eissn, "") or "")) if col_eissn else ""
        if_val_raw   = str(row.get(col_if, "") or "").strip()
        year_val_raw = str(row.get(col_if_year, "") or "").strip() if col_if_year else ""
        quartile_val = str(row.get(col_quartile, "") or "").strip() if col_quartile else ""

        # Parse IF value
        try:
            if_value = float(if_val_raw.replace(",", "."))
        except ValueError:
            continue   # skip rows without valid IF

        # Parse IF year
        try:
            year_int = int(float(year_val_raw)) if year_val_raw else (if_year or 2024)
        except ValueError:
            year_int = if_year or 2024

        # ── Find matching DB journal ──────────────────────────────────────
        journal_id: Optional[int] = None
        match_method = ""

        # 1. Print ISSN exact
        if issn_val and issn_val in by_issn:
            journal_id = by_issn[issn_val]
            match_method = "issn_exact"

        # 2. eISSN exact
        if journal_id is None and eissn_val and eissn_val in by_issn:
            journal_id = by_issn[eissn_val]
            match_method = "eissn_exact"

        # 3. Name exact
        if journal_id is None and name_val.lower() in by_name:
            journal_id = by_name[name_val.lower()]
            match_method = "name_exact"

        # 4. Abbr exact
        if journal_id is None and abbr_val and abbr_val.lower() in by_abbr:
            journal_id = by_abbr[abbr_val.lower()]
            match_method = "abbr_exact"

        # 5. Fuzzy name match
        if journal_id is None:
            best = _fuzzy_match(name_val, name_list, config.JOURNAL_FUZZY_THRESHOLD)
            if best:
                journal_id = by_name[best.lower()]
                match_method = f"fuzzy({best})"

        if journal_id is not None:
            update_journal_if(journal_id, if_value, year_int, quartile_val)
            matched += 1
        else:
            # Not found — insert as new journal entry
            journal_id = upsert_journal(name_val, abbr_val, issn_val)
            update_journal_if(journal_id, if_value, year_int, quartile_val)
            # Update lookup dicts for subsequent rows
            by_name[name_val.lower()] = journal_id
            if issn_val:
                by_issn[issn_val] = journal_id
            name_list.append(name_val.lower())
            inserted += 1
            unmatched.append({
                "name": name_val,
                "abbr": abbr_val,
                "issn": issn_val,
                "if": if_value,
                "year": year_int,
                "note": "inserted_new",
            })

    print(f"[IF Importer] Done: {matched} matched, {inserted} newly inserted.")

    # Save unmatched for review
    if unmatched:
        unmatched_path = os.path.join(config.DATA_DIR, "unmatched_journals.csv")
        os.makedirs(config.DATA_DIR, exist_ok=True)
        pd.DataFrame(unmatched).to_csv(unmatched_path, index=False)
        print(f"  {len(unmatched)} new journals written to {unmatched_path}")

    # ── Link papers to their journals (fill journal_id FK) ────────────────
    _link_papers_to_journals()


def _link_papers_to_journals() -> None:
    """
    After importing IF data, resolve journal_id FK for papers whose
    journal_name/issn wasn't linked at ingest time.
    """
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


if __name__ == "__main__":
    import sys
    from utils.db import init_db
    init_db()
    if len(sys.argv) < 2:
        print("Usage: python -m utils.if_importer <path_to_excel.xlsx> [if_year]")
        sys.exit(1)
    year_arg = int(sys.argv[2]) if len(sys.argv) > 2 else None
    import_impact_factors(sys.argv[1], if_year=year_arg)
