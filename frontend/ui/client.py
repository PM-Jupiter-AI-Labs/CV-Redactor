"""HTTP client for the redaction API.

The UI never imports the redactor. Everything goes through here, so the two
halves can be deployed on separate hosts -- which is exactly what you have to do
if the Streamlit app lives on Community Cloud.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

#: Where the API lives. Set CV_REDACTOR_API_URL when the two are not colocated.
DEFAULT_API_URL: str = os.environ.get("CV_REDACTOR_API_URL", "http://127.0.0.1:8000")

#: Redacting a large batch, and especially OCR, is slow. Be patient rather than
#: dropping the connection halfway through someone's fifty CVs.
DEFAULT_TIMEOUT: float = 600.0

Upload = tuple[str, bytes]


class ApiError(RuntimeError):
    """The API refused or failed a request, with the reason it gave."""


@dataclass(frozen=True, slots=True)
class RedactionBundle:
    """A finished batch: the zip to download and the manifest describing it."""

    archive: bytes
    manifest: dict


class RedactorClient:
    """Thin wrapper over the four endpoints."""

    def __init__(
        self, base_url: str = DEFAULT_API_URL, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        self.base_url: str = base_url.rstrip("/")
        self.timeout: float = timeout

    # -- plumbing ---------------------------------------------------------

    @property
    def _prefix(self) -> str:
        return f"{self.base_url}/api/v1"

    @staticmethod
    def _files(uploads: list[Upload]) -> list[tuple[str, tuple[str, bytes, str]]]:
        return [("files", (name, data, "application/octet-stream")) for name, data in uploads]

    def _raise(self, response: httpx.Response) -> None:
        """Turn an error response into an ApiError carrying the server's reason."""
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(f"{response.status_code}: {detail}")

    # -- endpoints --------------------------------------------------------

    def health(self) -> dict:
        try:
            response = httpx.get(f"{self._prefix}/health", timeout=10.0)
        except httpx.HTTPError as exc:
            raise ApiError(f"cannot reach the API at {self.base_url}: {exc}") from exc
        if response.status_code != 200:
            self._raise(response)
        return response.json()

    def scan(self, uploads: list[Upload]) -> list[dict]:
        response = httpx.post(
            f"{self._prefix}/scan", files=self._files(uploads), timeout=self.timeout
        )
        if response.status_code != 200:
            self._raise(response)
        return response.json()["documents"]

    def redact(self, uploads: list[Upload], plans: list[dict]) -> RedactionBundle:
        response = httpx.post(
            f"{self._prefix}/redact",
            files=self._files(uploads),
            data={"plans": json.dumps(plans)},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            self._raise(response)

        manifest: dict = {}
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            if "manifest.json" in bundle.namelist():
                manifest = json.loads(bundle.read("manifest.json"))
        return RedactionBundle(archive=response.content, manifest=manifest)

    def verify(self, uploads: list[Upload], plans: list[dict]) -> dict:
        response = httpx.post(
            f"{self._prefix}/verify",
            files=self._files(uploads),
            data={"plans": json.dumps(plans)},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            self._raise(response)
        return response.json()
