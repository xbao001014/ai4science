"""HTTP client for Fangxin pathology query API (api_document.md)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import config


class PathologyHttpError(RuntimeError):
    """Raised when the pathology API returns a non-success response."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class HttpPathologyApi:
    """Thin wrapper around GET /api/v1/pathology/* endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or config.PATHOLOGY_API_BASE_URL).rstrip("/")
        self.api_key = api_key or config.PATHOLOGY_API_KEY
        self.timeout = timeout if timeout is not None else config.PATHOLOGY_API_TIMEOUT

    def _request(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {k: v for k, v in (params or {}).items() if v is not None and v != ""},
            doseq=True,
        )
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(
            url,
            headers={
                "X-AiData-Key": self.api_key,
                "Accept": "application/json",
            },
            method="GET",
        )
        last_err: Exception | None = None
        retries = max(1, config.PATHOLOGY_API_RETRIES)
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise PathologyHttpError(
                    f"HTTP {exc.code} for {path}: {body[:300]}",
                    status=exc.code,
                ) from exc
            except urllib.error.URLError as exc:
                last_err = exc
                if attempt + 1 < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                host = urllib.parse.urlparse(self.base_url).hostname or self.base_url
                raise PathologyHttpError(
                    f"Cannot reach pathology API at {host} ({exc.reason}). "
                    f"Check VPN/network/DNS, then retry. URL: {url}"
                ) from exc
        else:
            raise PathologyHttpError(f"Network error for {path}: {last_err}") from last_err

        code = str(payload.get("code", ""))
        if code and code != "200":
            raise PathologyHttpError(
                payload.get("message") or f"API code {code}",
                code=code,
            )
        data = payload.get("data")
        if data is None:
            return []
        if isinstance(data, list):
            return data
        return [data]

    def list_diseases(self, keyword: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"Limit": min(limit, 1000)}
        if keyword:
            params["Keyword"] = keyword
        return self._request("/diseases", params)

    def patient_count_by_province(
        self,
        *,
        disease_code: str | None = None,
        disease_id: int | None = None,
        disease_name: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._request(
            "/diseases/patient-count-by-province",
            self._disease_params(disease_code, disease_id, disease_name),
        )

    def sample_count_by_hospital(
        self,
        *,
        disease_code: str | None = None,
        disease_id: int | None = None,
        disease_name: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._request(
            "/diseases/sample-count-by-hospital",
            self._disease_params(disease_code, disease_id, disease_name),
        )

    def list_patients(
        self,
        *,
        disease_code: str | None = None,
        disease_id: int | None = None,
        disease_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params = self._disease_params(disease_code, disease_id, disease_name)
        params["Limit"] = min(limit, 1000)
        return self._request("/diseases/patients", params)

    def list_specimens(
        self,
        *,
        disease_code: str | None = None,
        disease_id: int | None = None,
        disease_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params = self._disease_params(disease_code, disease_id, disease_name)
        params["Limit"] = min(limit, 1000)
        return self._request("/diseases/specimens", params)

    def list_slides(
        self,
        *,
        disease_code: str | None = None,
        disease_id: int | None = None,
        disease_name: str | None = None,
        stain_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params = self._disease_params(disease_code, disease_id, disease_name)
        params["Limit"] = min(limit, 1000)
        if stain_type:
            params["StainType"] = stain_type
        return self._request("/diseases/slides", params)

    def list_disease_subtypes(
        self,
        patient_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"Limit": min(limit, 1000)}
        if patient_id:
            params["PatientId"] = patient_id
        return self._request("/patients/disease-subtypes", params)

    def list_disease_attributes(
        self,
        patient_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"Limit": min(limit, 1000)}
        if patient_id:
            params["PatientId"] = patient_id
        return self._request("/patients/disease-attributes", params)

    def list_molecular_results(
        self,
        *,
        patient_id: str | None = None,
        biomarker_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"Limit": min(limit, 1000)}
        if patient_id:
            params["PatientId"] = patient_id
        if biomarker_name:
            params["BiomarkerName"] = biomarker_name
        return self._request("/molecular-results", params)

    def list_text_disease_matches(
        self,
        *,
        patient_id: str | None = None,
        disease_code: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"Limit": min(limit, 1000)}
        if patient_id:
            params["PatientId"] = patient_id
        if disease_code:
            params["DiseaseCode"] = disease_code
        return self._request("/text-disease-matches", params)

    @staticmethod
    def _disease_params(
        disease_code: str | None,
        disease_id: int | None,
        disease_name: str | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if disease_id is not None:
            params["DiseaseId"] = disease_id
        if disease_code:
            params["DiseaseCode"] = disease_code
        if disease_name:
            params["DiseaseName"] = disease_name
        return params
