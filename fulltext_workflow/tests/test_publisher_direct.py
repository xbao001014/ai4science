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


def test_extract_elsevier_pdf_urls_from_linkinghub_pii():
    resolved = "https://linkinghub.elsevier.com/retrieve/pii/S089561112200146X"
    html = "<html><body><p>Redirecting...</p></body></html>"
    urls = pd._extract_elsevier_pdf_urls(resolved, html)
    assert len(urls) == 2
    assert all("S089561112200146X" in u for u in urls)
    assert all("/pdfft" in u for u in urls)
    assert urls[0].startswith("https://www.sciencedirect.com/science/article/pii/")


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
