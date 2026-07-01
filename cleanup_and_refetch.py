"""
cleanup_and_refetch.py
三步清理：
  1. 删除题目过短（<15字符）的论文
  2. 删除 Editorial / Erratum / Letter / Reply / Correction 类文章
  3. 重新从 PubMed 下载被截断 abstract 的论文（末尾无句号，长度<1500）
"""
from __future__ import annotations
import time
import xml.etree.ElementTree as ET
from Bio import Entrez
import config
from utils.db import get_conn, init_db

Entrez.email = config.PUBMED_EMAIL
Entrez.api_key = config.PUBMED_API_KEY or None

init_db()

# ─────────────────────────────────────────────────────────────────────────────
# 辅助：删除一篇论文的所有关联数据
# ─────────────────────────────────────────────────────────────────────────────
def delete_paper(conn, pmid: str):
    conn.execute("DELETE FROM paper_authors WHERE paper_id = (SELECT id FROM papers WHERE pmid=?)", (pmid,))
    conn.execute("DELETE FROM citations     WHERE citing_pmid=? OR cited_pmid=?", (pmid, pmid))
    conn.execute("DELETE FROM relations     WHERE source_pmid=?", (pmid,))
    conn.execute("DELETE FROM papers        WHERE pmid=?", (pmid,))


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: 删除题目过短的论文
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 1: 删除题目过短（<15字符）的论文")
print("="*60)

with get_conn() as conn:
    rows = conn.execute("""
        SELECT pmid, title FROM papers
        WHERE title IS NULL OR LENGTH(TRIM(title)) < 15
    """).fetchall()

    for r in rows:
        pmid, title = r["pmid"], r["title"]
        print(f"  删除 PMID={pmid}  title={repr(title)}")
        delete_paper(conn, pmid)
    conn.commit()

print(f"  → 共删除 {len(rows)} 篇")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: 删除 Editorial/Erratum/Letter/Reply/Correction/Corrigendum
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 2: 删除 Editorial/Erratum/Letter/Reply/Correction 类文章")
print("="*60)

JUNK_TITLE_PREFIXES = (
    "editorial:", "erratum", "corrigendum", "correction:",
    "reply ", "reply:", "response to", "re:", "letter to",
    "authors' reply", "author's reply",
    # 带方括号的中文期刊编辑类
)
JUNK_TITLE_KEYWORDS = [
    "erratum to ", "correction to ", "corrigendum to ",
    "erratum:", "corrigendum:", "correction:",
]

with get_conn() as conn:
    rows = conn.execute("SELECT pmid, title FROM papers").fetchall()
    to_delete = []
    for r in rows:
        title_lower = (r["title"] or "").lower().strip()
        is_junk = False
        # 前缀匹配
        for prefix in JUNK_TITLE_PREFIXES:
            if title_lower.startswith(prefix):
                is_junk = True
                break
        # 关键词匹配
        if not is_junk:
            for kw in JUNK_TITLE_KEYWORDS:
                if kw in title_lower:
                    is_junk = True
                    break
        if is_junk:
            to_delete.append((r["pmid"], r["title"]))

    for pmid, title in to_delete:
        t = (title or "")[:70]
        print(f"  删除 PMID={pmid}  {t}")
        delete_paper(conn, pmid)
    conn.commit()

print(f"  → 共删除 {len(to_delete)} 篇")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: 重新下载被截断 abstract 的论文
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 3: 重新下载被截断 abstract（200~1500字符，末尾无句号）")
print("="*60)

with get_conn() as conn:
    rows = conn.execute("""
        SELECT pmid, title, abstract
        FROM papers
        WHERE abstract IS NOT NULL AND LENGTH(TRIM(abstract)) BETWEEN 200 AND 1500
    """).fetchall()

truncated_pmids = []
for r in rows:
    tail = (r["abstract"] or "").strip()
    if tail and tail[-1] not in '.?!)";\u3002\u300f':
        truncated_pmids.append(r["pmid"])

print(f"  需要重新下载：{len(truncated_pmids)} 篇")


def _fetch_batch_xml(pmids: list[str]) -> bytes:
    handle = Entrez.efetch(db="pubmed", id=pmids, rettype="xml", retmode="xml")
    raw = handle.read()
    handle.close()
    return raw


def _parse_abstract(raw_xml: bytes) -> dict[str, str]:
    """Return {pmid: abstract_text}"""
    root = ET.fromstring(raw_xml)
    result = {}
    for pub_article in root.findall("PubmedArticle"):
        medline = pub_article.find("MedlineCitation")
        if medline is None:
            continue
        pmid = medline.findtext("PMID", "")
        article = medline.find("Article")
        if article is None:
            continue
        parts = article.findall(".//AbstractText")
        texts = []
        for part in parts:
            label = part.get("Label", "")
            text = part.text or ""
            if label:
                texts.append(f"{label}: {text}")
            else:
                texts.append(text)
        abstract = " ".join(texts).strip()
        if pmid and abstract:
            result[pmid] = abstract
    return result


BATCH = 100
updated = 0
failed = 0

with get_conn() as conn:
    for i in range(0, len(truncated_pmids), BATCH):
        batch = truncated_pmids[i:i+BATCH]
        print(f"  [{i+1}-{min(i+BATCH, len(truncated_pmids))}/{len(truncated_pmids)}] 下载中...", end=" ", flush=True)
        try:
            raw_xml = _fetch_batch_xml(batch)
            abstracts = _parse_abstract(raw_xml)
            for pmid, abstract in abstracts.items():
                # 只更新比原来更长的（真正补全了）
                conn.execute(
                    "UPDATE papers SET abstract=? WHERE pmid=? AND LENGTH(COALESCE(abstract,'')) < LENGTH(?)",
                    (abstract, pmid, abstract)
                )
            batch_updated = sum(
                1 for pmid in batch
                if pmid in abstracts and len(abstracts[pmid]) > 0
            )
            updated += batch_updated
            print(f"OK ({batch_updated} 篇更新)")
        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1
        time.sleep(0.4)
    conn.commit()

print(f"\n  → 重新下载完成：更新 {updated} 篇，失败批次 {failed} 个")


# ─────────────────────────────────────────────────────────────────────────────
# 最终统计
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("最终统计")
print("="*60)
with get_conn() as conn:
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    no_abs = conn.execute("SELECT COUNT(*) FROM papers WHERE abstract IS NULL OR TRIM(abstract)=''").fetchone()[0]
    short_abs = conn.execute("SELECT COUNT(*) FROM papers WHERE LENGTH(TRIM(COALESCE(abstract,''))) BETWEEN 1 AND 199").fetchone()[0]
    print(f"  总论文数: {total}")
    print(f"  无 abstract: {no_abs}")
    print(f"  abstract < 200字符: {short_abs}")
