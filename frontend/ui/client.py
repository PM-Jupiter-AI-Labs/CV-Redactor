"""How the UI reaches the redactor.

Two implementations of the same four calls:

    RedactorClient  over HTTP, to a FastAPI service that may be on another host
    LocalClient     in this process, for a host that will only run one

`make_client` picks between them, and `app.py` is written against whichever it
gets. See local_client.py for why the second one exists.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass
from typing import Protocol

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


class Client(Protocol):
    """What the UI needs, whichever side of an HTTP hop the work happens on."""

    base_url: str

    def health(self) -> dict: ...
    def scan(self, uploads: list[Upload]) -> list[dict]: ...
    def redact(self, uploads: list[Upload], plans: list[dict]) -> RedactionBundle: ...
    def verify(self, uploads: list[Upload], plans: list[dict]) -> dict: ...


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


# Imported here rather than at the top: local_client needs names from this
# module, so importing it earlier would be circular. Re-exported so callers
# have a single place to import either client from.
from frontend.ui.local_client import LocalClient  # noqa: E402

__all__ = [
    "ApiError",
    "Client",
    "LocalClient",
    "RedactionBundle",
    "RedactorClient",
    "Upload",
    "make_client",
]


def make_client(api_url: str | None = None) -> Client:
    """The client this deployment should use.

    An explicit `api_url`, or CV_REDACTOR_API_URL in the environment, means
    there is a service to talk to. With neither, there is no second process to
    reach and the work happens here.

    Defaulting to in-process is what makes a single-process host work with no
    configuration at all; `docker compose` and the local two-terminal setup both
    set CV_REDACTOR_API_URL, so they keep the HTTP path.
    """
    url: str | None = api_url if api_url is not None else os.environ.get("CV_REDACTOR_API_URL")
    if url and url.strip() and url.strip() != LocalClient.base_url:
        return RedactorClient(url.strip())
    return LocalClient()
