"""Tests for NCBI PMID→PMCID fallback used by fetch-fulltext."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fetcher.pmc_fetcher import _idconv_pmid_to_pmc, _parse_idconv_pmid_to_pmc

_SAMPLE_IDCONV = {
    "status": "ok",
    "records": [
        {"pmid": "19304878", "pmcid": "PMC2682512"},
        {"pmid": 25593355, "pmcid": "PMC4292325"},
        {"pmid": "99999999", "status": "error", "errmsg": "Identifier not found in PMC"},
        {"pmid": "111", "pmcid": "4292325"},  # missing PMC prefix → normalize
    ],
}


def test_parse_idconv_pmid_to_pmc() -> None:
    mapping = _parse_idconv_pmid_to_pmc(_SAMPLE_IDCONV)
    assert mapping == {
        "19304878": "PMC2682512",
        "25593355": "PMC4292325",
        "111": "PMC4292325",
    }


def test_idconv_calls_ncbi_converter_api() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = _SAMPLE_IDCONV
    mock_resp.raise_for_status = MagicMock()

    with patch("fetcher.pmc_fetcher.requests.get", return_value=mock_resp) as mock_get:
        mapping = _idconv_pmid_to_pmc(["19304878", "25593355"])

    mock_get.assert_called_once()
    assert "pmc/utils/idconv" in mock_get.call_args.args[0]
    params = mock_get.call_args.kwargs["params"]
    assert params["ids"] == "19304878,25593355"
    assert params["format"] == "json"
    assert mapping is not None
    assert mapping["19304878"] == "PMC2682512"
    assert mapping["25593355"] == "PMC4292325"


def test_idconv_returns_none_after_hard_failures() -> None:
    with patch("fetcher.pmc_fetcher.time.sleep"):
        with patch(
            "fetcher.pmc_fetcher.requests.get",
            side_effect=ConnectionError("boom"),
        ):
            assert _idconv_pmid_to_pmc(["19304878"]) is None
