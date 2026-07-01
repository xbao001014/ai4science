"""Citation enrichment: OpenAlex (default) with optional Semantic Scholar fallback."""
from __future__ import annotations

import time
from typing import Any

import requests
from tqdm import tqdm

import config
from db.schema import get_conn

_OPENALEX = "https://api.openalex.org/works"
_S2_BASE = "https://api.semanticscholar.org/graph/v1"
_OPENALEX_BATCH = 50
_S2_BATCH = 100
_RATE_DELAY = 0.35
_TIMEOUT = 60


def _mailto_params() -> dict[str, str]:
    if config.PUBMED_EMAIL and "@" in config.PUBMED_EMAIL:
        return {"mailto": config.PUBMED_EMAIL}
    return {}


def _s2_headers() -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    if config.S2_API_KEY:
        h["x-api-key"] = config.S2_API_KEY
    return h


def _probe_s2() -> bool:
    """Return True if S2 API accepts authenticated requests."""
    if not config.S2_API_KEY:
        return False
    try:
        resp = requests.get(
            f"{_S2_BASE}/paper/PMID:38123456",
            params={"fields": "paperId,citationCount"},
            headers=_s2_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return True
        print(f"  [S2] Probe failed ({resp.status_code}): {resp.text[:120]}")
        return False
    except Exception as e:
        print(f"  [S2] Probe error: {e}")
        return False


def _openalex_fetch_batch(pmids: list[str]) -> dict[str, dict[str, Any]]:
    if not pmids:
        return {}
    params = {
        "filter": f"ids.pmid:{'|'.join(pmids)}",
        "per-page": min(200, len(pmids)),
        "select": "id,cited_by_count,ids,open_access",
        **_mailto_params(),
    }
    resp = requests.get(_OPENALEX, params=params, timeout=_TIMEOUT)
    if resp.status_code == 429:
        time.sleep(10)
        resp = requests.get(_OPENALEX, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()

    out: dict[str, dict[str, Any]] = {}
    for work in resp.json().get("results") or []:
        ext = work.get("ids") or {}
        pmid = str(ext.get("pmid") or "").replace("https://pubmed.ncbi.nlm.nih.gov/", "")
        if not pmid:
            continue
        oa = work.get("open_access") or {}
        out[pmid] = {
            "external_id": (work.get("id") or "").rsplit("/", 1)[-1],
            "citation_count": int(work.get("cited_by_count") or 0),
            "open_access": int(bool(oa.get("is_oa"))),
            "source": "openalex",
        }
    return out


def _s2_fetch_batch(paper_ids: list[str]) -> list[dict | None]:
    url = f"{_S2_BASE}/paper/batch"
    resp = requests.post(
        url,
        params={"fields": "paperId,externalIds,citationCount,isOpenAccess,abstract"},
        json={"ids": paper_ids},
        headers={**_s2_headers(), "Content-Type": "application/json"},
        timeout=_TIMEOUT,
    )
    if resp.status_code == 429:
        print("  [S2] Rate limited — waiting 60s...")
        time.sleep(60)
        resp = requests.post(
            url,
            params={"fields": "paperId,externalIds,citationCount,isOpenAccess,abstract"},
            json={"ids": paper_ids},
            headers={**_s2_headers(), "Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
    resp.raise_for_status()
    return resp.json()


def _apply_row(
    conn,
    paper_id: int,
    *,
    external_id: str,
    citation_count: int,
    open_access: int,
    source: str,
    abstract: str = "",
    had_abstract: bool = True,
) -> None:
    if abstract and not had_abstract:
        conn.execute(
            """UPDATE papers SET
               s2id=?, citation_count=?, open_access=?, citation_source=?, abstract=?
               WHERE id=?""",
            (external_id, citation_count, open_access, source, abstract, paper_id),
        )
    else:
        conn.execute(
            """UPDATE papers SET
               s2id=?, citation_count=?, open_access=?, citation_source=?
               WHERE id=?""",
            (external_id, citation_count, open_access, source, paper_id),
        )


def _enrich_openalex(papers: list[dict[str, Any]]) -> int:
    enriched = 0
    batches = [papers[i : i + _OPENALEX_BATCH] for i in range(0, len(papers), _OPENALEX_BATCH)]
    for batch in tqdm(batches, desc="  [OpenAlex]", unit="batch"):
        pmids = [str(p["pmid"]) for p in batch if p.get("pmid")]
        try:
            found = _openalex_fetch_batch(pmids)
        except Exception as e:
            print(f"  [OpenAlex] Batch error: {e}")
            time.sleep(5)
            continue

        with get_conn() as conn:
            for paper in batch:
                pmid = str(paper["pmid"])
                hit = found.get(pmid)
                if hit:
                    _apply_row(
                        conn,
                        paper["id"],
                        external_id=hit["external_id"],
                        citation_count=hit["citation_count"],
                        open_access=hit["open_access"],
                        source="openalex",
                    )
                    enriched += 1
                else:
                    conn.execute(
                        """UPDATE papers SET s2id='NONE', citation_source='unavailable'
                           WHERE id=?""",
                        (paper["id"],),
                    )
        time.sleep(_RATE_DELAY)
    return enriched


def _enrich_s2(papers: list[dict[str, Any]]) -> int:
    enriched = 0
    batches = [papers[i : i + _S2_BATCH] for i in range(0, len(papers), _S2_BATCH)]
    for batch in tqdm(batches, desc="  [S2]", unit="batch"):
        s2_ids = []
        for p in batch:
            if p.get("pmid"):
                s2_ids.append(f"PMID:{p['pmid']}")
            elif p.get("doi"):
                s2_ids.append(f"DOI:{p['doi']}")
        try:
            results = _s2_fetch_batch(s2_ids)
        except Exception as e:
            print(f"  [S2] Batch error: {e}")
            time.sleep(5)
            continue

        with get_conn() as conn:
            for paper_data, s2_result in zip(batch, results):
                if not s2_result:
                    conn.execute(
                        """UPDATE papers SET s2id='NONE', citation_source='unavailable'
                           WHERE id=?""",
                        (paper_data["id"],),
                    )
                    continue
                s2id = s2_result.get("paperId", "")
                citation_count = int(s2_result.get("citationCount") or 0)
                open_access = int(bool(s2_result.get("isOpenAccess")))
                s2_abstract = (s2_result.get("abstract") or "").strip()
                had_abstract = bool((paper_data.get("abstract") or "").strip())
                _apply_row(
                    conn,
                    paper_data["id"],
                    external_id=s2id,
                    citation_count=citation_count,
                    open_access=open_access,
                    source="semantic_scholar",
                    abstract=s2_abstract,
                    had_abstract=had_abstract,
                )
                enriched += 1
        time.sleep(max(_RATE_DELAY, 1.0))
    return enriched


def enrich_citations(provider: str | None = None) -> None:
    """Fill citation_count via OpenAlex (default) or Semantic Scholar."""
    pref = (provider or config.CITATION_PROVIDER or "auto").lower()

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, pmid, doi, abstract FROM papers
               WHERE pmid IS NOT NULL
                 AND (citation_source IS NULL OR citation_source = '')"""
        ).fetchall()
    papers = [dict(r) for r in rows]
    print(f"[Citations] {len(papers)} papers to enrich.")

    if not papers:
        return

    use_s2 = pref == "semantic_scholar" or (pref == "auto" and _probe_s2())
    if use_s2:
        print("[Citations] Using Semantic Scholar.")
        count = _enrich_s2(papers)
        source_label = "S2"
    else:
        if pref == "semantic_scholar":
            print("[Citations] S2 unavailable — falling back to OpenAlex.")
        else:
            print("[Citations] Using OpenAlex (recommended when S2 returns 403).")
        count = _enrich_openalex(papers)
        source_label = "OpenAlex"

    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE citation_source IS NOT NULL AND citation_source != ''"
        ).fetchone()[0]
    print(f"[Citations] Done via {source_label}. Updated {count} papers ({total} total enriched).")


def enrich_from_s2() -> None:
    """Backward-compatible alias."""
    enrich_citations()
