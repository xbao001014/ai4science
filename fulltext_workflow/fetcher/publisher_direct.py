"""Campus-IP publisher PDF direct download (IEEE / Elsevier). Opt-in via config."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import requests

Publisher = Literal["ieee", "elsevier"]

_IEEE_PREFIX = "10.1109/"
_ELSEVIER_PREFIX = "10.1016/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def publisher_for_doi(doi: str) -> Publisher | None:
    d = (doi or "").strip().lower()
    if d.startswith(_IEEE_PREFIX):
        return "ieee"
    if d.startswith(_ELSEVIER_PREFIX):
        return "elsevier"
    return None


def looks_like_pdf(first_bytes: bytes, content_type: str | None = None) -> bool:
    ctype = (content_type or "").lower()
    if "text/html" in ctype:
        return False
    head = first_bytes.lstrip()[:8]
    return head.startswith(b"%PDF")


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = True  # honor system proxy / campus VPN tooling
    s.headers.update({"User-Agent": _USER_AGENT})
    return s


def _fail(source: str, reason: str) -> dict[str, Any]:
    return {"success": False, "file": "", "source": source, "reason": reason}


def _write_pdf_atomic(output_path: Path, first: bytes, iterator) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".part")
    try:
        with tmp.open("wb") as fh:
            fh.write(first)
            for chunk in iterator:
                if chunk:
                    fh.write(chunk)
        tmp.replace(output_path)
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


def _download_url_to_path(url: str, output_path: Path, *, timeout: float) -> bool:
    sess = _session()
    try:
        with sess.get(
            url,
            timeout=timeout,
            stream=True,
            allow_redirects=True,
            headers={"Accept": "application/pdf,*/*"},
        ) as resp:
            if resp.status_code >= 400:
                return False
            iterator = resp.iter_content(chunk_size=8192)
            first = next(iterator, b"")
            if not looks_like_pdf(first, resp.headers.get("Content-Type")):
                return False
            return _write_pdf_atomic(output_path, first, iterator)
    except requests.RequestException:
        return False


def _resolve_doi_url(doi: str, *, timeout: float) -> str | None:
    sess = _session()
    try:
        resp = sess.head(
            f"https://doi.org/{doi}",
            allow_redirects=True,
            timeout=timeout,
        )
        if resp.status_code < 400 and resp.url:
            return resp.url
    except requests.RequestException:
        pass
    try:
        resp = sess.get(
            f"https://doi.org/{doi}",
            allow_redirects=True,
            timeout=timeout,
        )
        if resp.status_code < 400 and resp.url:
            return resp.url
    except requests.RequestException:
        return None
    return None


def _extract_arnumber(url: str, html: str = "") -> str | None:
    qs = parse_qs(urlparse(url).query)
    if "arnumber" in qs and qs["arnumber"]:
        return qs["arnumber"][0]
    m = re.search(r"arnumber=(\d+)", url) or re.search(r"arnumber=(\d+)", html)
    if m:
        return m.group(1)
    m = re.search(r"/document/(\d+)", url) or re.search(r"/document/(\d+)", html)
    if m:
        return m.group(1)
    return None


def _try_ieee(doi: str, output_path: Path, *, timeout: float = 25.0) -> dict[str, Any]:
    resolved = _resolve_doi_url(doi, timeout=timeout) or ""
    html = ""
    if resolved and "ieeexplore" in resolved.lower():
        try:
            r = _session().get(resolved, timeout=timeout, allow_redirects=True)
            html = r.text[:200_000] if r.status_code < 400 else ""
            resolved = r.url or resolved
        except requests.RequestException:
            pass
    arnumber = _extract_arnumber(resolved, html)
    candidates: list[str] = []
    if arnumber:
        candidates.extend(
            [
                f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}",
                f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={arnumber}",
            ]
        )
    for url in candidates:
        if _download_url_to_path(url, output_path, timeout=timeout):
            return {
                "success": True,
                "file": str(output_path),
                "source": "ieee_direct",
                "reason": "",
            }
    return _fail("ieee_direct", "ieee_pdf_not_found")


def _extract_elsevier_pii(resolved: str, html: str) -> str | None:
    """Extract Elsevier PII from ScienceDirect or linkinghub landing URLs."""
    patterns = (
        r"/science/article/pii/([A-Z0-9]+)",
        r"/retrieve/pii/([A-Z0-9]+)",
    )
    for text in (resolved, html):
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1)
    return None


def _extract_elsevier_pdf_urls(resolved: str, html: str) -> list[str]:
    urls: list[str] = []
    m = re.search(
        r'citation_pdf_url["\s]+content=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if m:
        urls.append(m.group(1))
    # ScienceDirect PII pdfft (from article page or linkinghub retrieve/pii)
    pii = _extract_elsevier_pii(resolved, html)
    if pii:
        urls.append(
            f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft"
            "?isDTMRedir=true&download=true"
        )
        urls.append(
            f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft"
        )
    for m in re.finditer(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
        href = m.group(1)
        if href.startswith("/"):
            host = f"{urlparse(resolved).scheme}://{urlparse(resolved).netloc}"
            href = host + href
        if href.startswith("http"):
            urls.append(href)
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _try_elsevier(doi: str, output_path: Path, *, timeout: float = 25.0) -> dict[str, Any]:
    resolved = _resolve_doi_url(doi, timeout=timeout)
    if not resolved:
        return _fail("elsevier_direct", "doi_resolve_failed")
    html = ""
    try:
        r = _session().get(resolved, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return _fail("elsevier_direct", f"landing_http_{r.status_code}")
        html = r.text[:300_000]
        resolved = r.url or resolved
    except requests.RequestException as e:
        return _fail("elsevier_direct", f"landing_error:{type(e).__name__}")

    for url in _extract_elsevier_pdf_urls(resolved, html):
        if _download_url_to_path(url, output_path, timeout=timeout):
            return {
                "success": True,
                "file": str(output_path),
                "source": "elsevier_direct",
                "reason": "",
            }
    return _fail("elsevier_direct", "elsevier_pdf_not_found")


def try_publisher_direct(
    doi: str,
    output_path: Path,
    *,
    timeout: float = 25.0,
) -> dict[str, Any]:
    pub = publisher_for_doi(doi)
    if pub is None:
        return _fail("none", "unsupported_publisher")
    if pub == "ieee":
        return _try_ieee(doi, output_path, timeout=timeout)
    return _try_elsevier(doi, output_path, timeout=timeout)
