# IEEE / Elsevier Publisher Direct PDF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opt-in campus-IP direct PDF download for IEEE (`10.1109/`) and Elsevier (`10.1016/`) before ScanSci OA fallback.

**Architecture:** New `fetcher/publisher_direct.py` resolves DOI → publisher PDF with `trust_env=True` and `%PDF` validation. `scansci_fetcher.download_pdf` calls it only when `FULLTEXT_PUBLISHER_DIRECT` is true; on miss, existing ScanSci path runs unchanged.

**Tech Stack:** Python 3, `requests`, pytest, existing fulltext Tier-2 PDF path.

**Spec:** `docs/superpowers/specs/2026-08-10-ieee-elsevier-publisher-direct-design.md`

## Global Constraints

- Default **off**: `FULLTEXT_PUBLISHER_DIRECT=false`.
- Access model: campus / VPN **IP passthrough only** (no CARSI, no API keys, no Sci-Hub).
- Do **not** modify `scansci_pdf` site-packages.
- Do **not** change `full_text_status` state machine, PDF attempt counters, or cooldown.
- Publisher miss must **not** mark papers unavailable by itself; fall through to ScanSci.
- Success sources: `ieee_direct` / `elsevier_direct`; cache path stays `raw/pdfs/{pmid}_{doi_safe}.pdf`.
- Run pytest from `fulltext_workflow/`.
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the tree dirty and note the suggested commit message.
- Do not commit `data/`, `raw/`, `output/`, or secrets.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/fetcher/publisher_direct.py` | Prefix router; IEEE / Elsevier download; PDF validation; atomic write |
| `fulltext_workflow/fetcher/scansci_fetcher.py` | Call publisher_direct when flag on, then ScanSci |
| `fulltext_workflow/config.py` | `FULLTEXT_PUBLISHER_DIRECT` bool |
| `fulltext_workflow/tests/test_publisher_direct.py` | Unit tests (routing, validation, mocked HTTP, flag wiring) |
| `.env.example` | Document env flag |
| `fulltext_workflow/SCRIPTS.md` | Document usage + campus/VPN requirement |

---

### Task 1: `publisher_direct` module (TDD)

**Files:**
- Create: `fulltext_workflow/fetcher/publisher_direct.py`
- Create: `fulltext_workflow/tests/test_publisher_direct.py`

**Interfaces:**
- Produces:
  - `looks_like_pdf(first_bytes: bytes, content_type: str | None = None) -> bool`
  - `publisher_for_doi(doi: str) -> Literal["ieee", "elsevier"] | None`
  - `try_publisher_direct(doi: str, output_path: Path, *, timeout: float = 25.0) -> dict[str, Any]`
    - Return shape matches ScanSci wrapper: `{success: bool, file: str, source: str, reason: str}`
    - On success: `source` is `ieee_direct` or `elsevier_direct`, `file` is `str(output_path)`
    - On skip/fail: `success=False`, `source` is `none` / `ieee_direct` / `elsevier_direct`, `reason` set
  - Internal helpers OK: `_resolve_doi_url`, `_session`, `_download_url_to_path`, `_try_ieee`, `_try_elsevier`

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_publisher_direct.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fetcher import publisher_direct as pd


def test_publisher_for_doi_routing():
    assert pd.publisher_for_doi("10.1109/TMI.2023.3263010") == "ieee"
    assert pd.publisher_for_doi("10.1016/j.compmedimag.2022.102176") == "elsevier"
    assert pd.publisher_for_doi("10.1038/s41586-024-00000-0") is None
    assert pd.publisher_for_doi("") is None


def test_looks_like_pdf_magic_and_reject_html():
    assert pd.looks_like_pdf(b"%PDF-1.6 ....")
    assert pd.looks_like_pdf(b"%PDF-1.4", "application/pdf")
    assert not pd.looks_like_pdf(b"<!DOCTYPE html>")
    assert not pd.looks_like_pdf(b"\n\n<html>")
    assert not pd.looks_like_pdf(b"%PDF-1.4", "text/html; charset=utf-8")


def test_try_publisher_direct_skips_unknown_prefix(tmp_path: Path):
    out = tmp_path / "x.pdf"
    result = pd.try_publisher_direct("10.1038/s41586-024-00000-0", out)
    assert result["success"] is False
    assert result["reason"] == "unsupported_publisher"
    assert not out.exists()


def test_try_publisher_direct_ieee_success(monkeypatch, tmp_path: Path):
    out = tmp_path / "ieee.pdf"
    pdf_bytes = b"%PDF-1.6 fake-ieee-content"

    def fake_ieee(doi, output_path, *, timeout=25.0):
        output_path.write_bytes(pdf_bytes)
        return {
            "success": True,
            "file": str(output_path),
            "source": "ieee_direct",
            "reason": "",
        }

    monkeypatch.setattr(pd, "_try_ieee", fake_ieee)
    result = pd.try_publisher_direct("10.1109/TMI.2023.3263010", out)
    assert result["success"] is True
    assert result["source"] == "ieee_direct"
    assert out.read_bytes().startswith(b"%PDF")


def test_try_publisher_direct_elsevier_success(monkeypatch, tmp_path: Path):
    out = tmp_path / "elsevier.pdf"

    def fake_elsevier(doi, output_path, *, timeout=25.0):
        output_path.write_bytes(b"%PDF-1.7 elsevier")
        return {
            "success": True,
            "file": str(output_path),
            "source": "elsevier_direct",
            "reason": "",
        }

    monkeypatch.setattr(pd, "_try_elsevier", fake_elsevier)
    result = pd.try_publisher_direct("10.1016/j.ygyno.2021.07.015", out)
    assert result["success"] is True
    assert result["source"] == "elsevier_direct"


def test_download_url_rejects_html(monkeypatch, tmp_path: Path):
    out = tmp_path / "bad.pdf"
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    resp.iter_content = lambda chunk_size=8192: iter([b"<html>paywall</html>"])
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda *a: None

    sess = MagicMock()
    sess.get.return_value = resp
    monkeypatch.setattr(pd, "_session", lambda: sess)

    ok = pd._download_url_to_path("https://example.com/x", out, timeout=5.0)
    assert ok is False
    assert not out.exists()
    assert not list(tmp_path.glob("*.part"))
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd D:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_publisher_direct.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `fetcher.publisher_direct`.

- [ ] **Step 3: Implement `publisher_direct.py`**

Create `fulltext_workflow/fetcher/publisher_direct.py` with at least:

```python
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


def _extract_elsevier_pdf_urls(resolved: str, html: str) -> list[str]:
    urls: list[str] = []
    m = re.search(
        r'citation_pdf_url["\s]+content=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if m:
        urls.append(m.group(1))
    # ScienceDirect PII pdfft
    m = re.search(r"/science/article/pii/([A-Z0-9]+)", resolved, re.I)
    if not m:
        m = re.search(r"/science/article/pii/([A-Z0-9]+)", html, re.I)
    if m:
        pii = m.group(1)
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
```

Tighten URL patterns only if campus probes for acceptance PMIDs show better endpoints; keep contract “valid PDF or fail”.

- [ ] **Step 4: Run tests to verify they pass**

```powershell
cd D:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_publisher_direct.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit (only if user requested commits)**

Suggested message: `feat: add IEEE/Elsevier campus-IP publisher PDF downloader`

```powershell
git add fulltext_workflow/fetcher/publisher_direct.py fulltext_workflow/tests/test_publisher_direct.py
```

---

### Task 2: Config flag + wire `download_pdf` + docs

**Files:**
- Modify: `fulltext_workflow/config.py` (near `SCANSCI_*` block ~lines 50–64)
- Modify: `fulltext_workflow/fetcher/scansci_fetcher.py`
- Modify: `fulltext_workflow/tests/test_publisher_direct.py` (add wiring tests)
- Modify: `.env.example`
- Modify: `fulltext_workflow/SCRIPTS.md` (fetch-fulltext env comment block ~lines 76–81)

**Interfaces:**
- Consumes: `try_publisher_direct(doi, output_path) -> dict`
- Produces: `config.FULLTEXT_PUBLISHER_DIRECT: bool` (default False)
- `download_pdf` still returns `{success, file, source, reason}`; may return `ieee_direct` / `elsevier_direct` before ScanSci

- [ ] **Step 1: Write failing wiring tests**

Append to `tests/test_publisher_direct.py`. Implement `download_pdf` so the flag branch does `from fetcher.publisher_direct import try_publisher_direct` (or imports the module) so monkeypatching `fetcher.publisher_direct.try_publisher_direct` works. Keep ScanSci as a lazy `from scansci_pdf.sources import download` and pre-inject `sys.modules` in tests.

```python
def _install_fake_scansci(download_fn) -> None:
    import sys
    import types

    pkg = types.ModuleType("scansci_pdf")
    sources = types.ModuleType("scansci_pdf.sources")
    sources.download = download_fn
    sys.modules["scansci_pdf"] = pkg
    sys.modules["scansci_pdf.sources"] = sources


def test_download_pdf_skips_publisher_when_flag_off(monkeypatch, tmp_path: Path):
    import config
    import fetcher.publisher_direct as pubmod
    from fetcher import scansci_fetcher as sf

    monkeypatch.setattr(config, "FULLTEXT_PUBLISHER_DIRECT", False)
    monkeypatch.setattr(config, "RAW_PDF_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SCANSCI_RATE_DELAY", 0)

    called = {"n": 0}

    def tracker(*a, **k):
        called["n"] += 1
        return {"success": False, "file": "", "source": "none", "reason": "tracked"}

    monkeypatch.setattr(pubmod, "try_publisher_direct", tracker)

    def fake_download(doi, output_dir, **kwargs):
        p = Path(output_dir) / "tmp.pdf"
        p.write_bytes(b"%PDF-1.4 x")
        return {"success": True, "file": str(p), "source": "unpaywall", "reason": ""}

    _install_fake_scansci(fake_download)
    result = sf.download_pdf("10.1109/TMI.2023.3263010", "37030860")
    assert called["n"] == 0
    assert result["success"] is True
    assert result["source"] == "unpaywall"


def test_download_pdf_uses_publisher_when_flag_on(monkeypatch, tmp_path: Path):
    import config
    import fetcher.publisher_direct as pubmod
    from fetcher import scansci_fetcher as sf

    monkeypatch.setattr(config, "FULLTEXT_PUBLISHER_DIRECT", True)
    monkeypatch.setattr(config, "RAW_PDF_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SCANSCI_RATE_DELAY", 0)
    scansci_called = {"n": 0}

    def fake_pub(doi, output_path, **kwargs):
        output_path.write_bytes(b"%PDF-1.6 ieee")
        return {
            "success": True,
            "file": str(output_path),
            "source": "ieee_direct",
            "reason": "",
        }

    monkeypatch.setattr(pubmod, "try_publisher_direct", fake_pub)

    def fake_download(*a, **k):
        scansci_called["n"] += 1
        return {"success": False, "file": "", "source": "none", "reason": "no"}

    _install_fake_scansci(fake_download)
    result = sf.download_pdf("10.1109/TMI.2023.3263010", "37030860")
    assert result["source"] == "ieee_direct"
    assert scansci_called["n"] == 0
    assert Path(result["file"]).exists()


def test_download_pdf_falls_back_to_scansci_on_publisher_miss(monkeypatch, tmp_path: Path):
    import config
    import fetcher.publisher_direct as pubmod
    from fetcher import scansci_fetcher as sf

    monkeypatch.setattr(config, "FULLTEXT_PUBLISHER_DIRECT", True)
    monkeypatch.setattr(config, "RAW_PDF_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SCANSCI_RATE_DELAY", 0)

    monkeypatch.setattr(
        pubmod,
        "try_publisher_direct",
        lambda *a, **k: {
            "success": False,
            "file": "",
            "source": "ieee_direct",
            "reason": "ieee_pdf_not_found",
        },
    )

    def fake_download(doi, output_dir, **kwargs):
        p = Path(output_dir) / "oa.pdf"
        p.write_bytes(b"%PDF-1.4 oa")
        return {"success": True, "file": str(p), "source": "unpaywall", "reason": ""}

    _install_fake_scansci(fake_download)
    result = sf.download_pdf("10.1109/TMI.2023.3263010", "37030860")
    assert result["success"] is True
    assert result["source"] == "unpaywall"
```

- [ ] **Step 2: Run wiring tests — expect fail (flag / branch missing)**

```powershell
cd D:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_publisher_direct.py::test_download_pdf_uses_publisher_when_flag_on -v
```

Expected: FAIL (flag missing or branch not calling publisher).

- [ ] **Step 3: Implement config + `download_pdf` + docs**

In `config.py` after `SCANSCI_RATE_DELAY`:

```python
# Campus/VPN IP direct for IEEE (10.1109/) / Elsevier (10.1016/); default off
FULLTEXT_PUBLISHER_DIRECT: bool = os.getenv(
    "FULLTEXT_PUBLISHER_DIRECT", "false"
).lower() in ("1", "true", "yes", "on")
```

Replace `scansci_fetcher.py` body of `download_pdf` after cache hit with:

```python
    if config.FULLTEXT_PUBLISHER_DIRECT:
        from fetcher.publisher_direct import publisher_for_doi, try_publisher_direct

        if publisher_for_doi(doi) is not None:
            print(f"[INFO] Publisher direct - {doi}")
            pub = try_publisher_direct(doi, cached)
            if pub.get("success"):
                time.sleep(config.SCANSCI_RATE_DELAY)
                return {
                    "success": True,
                    "file": str(cached),
                    "source": pub.get("source", "publisher_direct"),
                    "reason": "",
                }
            print(
                f"[INFO]    Publisher direct miss "
                f"({pub.get('source')}: {pub.get('reason')}); falling back to ScanSci"
            )

    os.environ.setdefault("SCANSCI_PDF_SCIHUB_ENABLED", "false")
    from scansci_pdf.sources import download

    result = download(
        doi,
        output_dir=str(pdf_dir),
        strategy=config.SCANSCI_STRATEGY,
        scihub_enabled=False,
        rename=False,
    )

    if not result.get("success"):
        return {
            "success": False,
            "file": "",
            "source": result.get("source", "none"),
            "reason": result.get("reason", "download failed"),
        }

    downloaded = Path(result["file"])
    if downloaded.resolve() != cached.resolve():
        if cached.exists():
            cached.unlink()
        downloaded.rename(cached)

    time.sleep(config.SCANSCI_RATE_DELAY)
    return {
        "success": True,
        "file": str(cached),
        "source": result.get("source", "scansci"),
        "reason": "",
    }
```

Full `download_pdf` after the cache-hit early return must include the publisher-direct branch above, then the existing ScanSci block unchanged.

`.env.example` — after fulltext retry block:

```bash
# Campus/VPN IP: try IEEE (10.1109) / Elsevier (10.1016) PDF before ScanSci (default off)
# FULLTEXT_PUBLISHER_DIRECT=true
```

`SCRIPTS.md` — extend the env comment under fetch-fulltext:

```powershell
# env: FULLTEXT_RETRY_COOLDOWN_DAYS=7  FULLTEXT_PDF_RETRY_LIMIT=500
#      FULLTEXT_PUBLISHER_DIRECT=true   # needs campus/VPN IP; IEEE+Elsevier before ScanSci
# PDF 队列按 fulltext_pdf_attempts 升序优先从未尝试；失败重试冷却 7→14→28→56 天
```

- [ ] **Step 4: Run all publisher_direct tests**

```powershell
cd D:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_publisher_direct.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit (only if user requested commits)**

Suggested message: `feat: opt-in IEEE/Elsevier PDF via FULLTEXT_PUBLISHER_DIRECT`

```powershell
git add fulltext_workflow/config.py fulltext_workflow/fetcher/scansci_fetcher.py fulltext_workflow/tests/test_publisher_direct.py .env.example fulltext_workflow/SCRIPTS.md
```

---

### Task 3: Manual campus acceptance (no code merge required)

**Files:** none (ops check)

**Interfaces:** Uses Task 1–2 deliverables + live campus/VPN.

- [ ] **Step 1: Enable flag in local `.env` (not committed)**

```bash
FULLTEXT_PUBLISHER_DIRECT=true
```

Ensure campus network or institution VPN is connected.

- [ ] **Step 2: Probe three PMIDs without disturbing a long `fetch-fulltext` run if one is active**

Prefer a one-off script from `fulltext_workflow/`:

```powershell
cd D:\agent\prototype\build_kg_paper\fulltext_workflow
$env:FULLTEXT_PUBLISHER_DIRECT="true"
..\.venv\Scripts\python.exe -c @"
from pathlib import Path
import config
from fetcher.scansci_fetcher import download_pdf
print('flag', config.FULLTEXT_PUBLISHER_DIRECT)
cases = [
  ('37030860', '10.1109/TMI.2023.3263010'),
  ('36682215', '10.1016/j.compmedimag.2022.102176'),
  ('34275655', '10.1016/j.ygyno.2021.07.015'),
]
for pmid, doi in cases:
    # use a temp name to avoid clobbering; or delete target cache first
    target = Path(config.RAW_PDF_DIR) / f'{pmid}_{doi.replace(\"/\", \"_\")}.pdf'
    if target.exists():
        print(pmid, 'cache_exists', target.stat().st_size)
        continue
    r = download_pdf(doi, pmid)
    print(pmid, r)
"@
```

Expected on campus: `source` in `{ieee_direct, elsevier_direct}` and file size ≫ 1KB with `%PDF` magic. Off campus: miss → ScanSci fail/timeout is OK.

- [ ] **Step 3: Optional MinerU for one success**

If PDF landed and no long job conflict:

```powershell
..\.venv\Scripts\python.exe -c "from fetcher.mineru_parser import pdf_to_sections; from pathlib import Path; import config; p=list(Path(config.RAW_PDF_DIR).glob('37030860_*.pdf'))[0]; secs=pdf_to_sections(str(p),'37030860'); print(len(secs), secs[0]['section_type'] if secs else None)"
```

Expected: `len(secs) > 0`.

- [ ] **Step 4: Turn flag off again if not staying on campus**

Set `FULLTEXT_PUBLISHER_DIRECT=false` or remove from `.env` so overnight `fetch-fulltext` does not spam publisher timeouts.

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| Opt-in `FULLTEXT_PUBLISHER_DIRECT` default false | Task 2 |
| IEEE `10.1109/` + Elsevier `10.1016/` only | Task 1 |
| `trust_env=True`, PDF magic validation | Task 1 |
| Wire before ScanSci in `download_pdf` | Task 2 |
| Fail → fall through; no status-machine change | Task 2 |
| `.env.example` + `SCRIPTS.md` | Task 2 |
| Unit tests flag/routing/non-PDF | Task 1–2 |
| Manual PMIDs 37030860 / 36682215 / 34275655 | Task 3 |
| No scansci_pdf fork / no CARSI | honored in constraints |

## Placeholder scan

No TBD/TODO / “implement later” left; Task 2 wiring tests are a single clean block.
