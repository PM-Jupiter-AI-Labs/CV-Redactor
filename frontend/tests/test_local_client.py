"""The in-process client must behave like the HTTP one.

`app.py` is written against whichever it is handed, so the two have to agree on
shapes and on failure. These tests run the same operations through both and
compare, which is the only thing that stops the local path quietly drifting the
day someone changes a response model.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from frontend.api.main import create_app
from frontend.api.settings import get_settings
from frontend.tests.test_api import SURNAME, make_cv, text_of
from frontend.ui.client import ApiError, LocalClient, RedactorClient, make_client

FILENAME: str = "Priya_Sharma_CV.pdf"
OUTPUT: str = "Priya_Backend_Engineer.pdf"


@pytest.fixture
def local() -> LocalClient:
    get_settings.cache_clear()
    return LocalClient()


@pytest.fixture
def uploads() -> list[tuple[str, bytes]]:
    return [(FILENAME, make_cv())]


@pytest.fixture
def plans() -> list[dict]:
    return [{"filename": FILENAME, "surnames": [SURNAME], "output_name": OUTPUT}]


# ---------------------------------------------------------------------------
# It does the job
# ---------------------------------------------------------------------------


def test_health_reports_in_process(local: LocalClient) -> None:
    body = local.health()
    assert body["status"] == "ok"
    assert body["version"]
    assert local.base_url == "in-process"


def test_scan_reads_the_header(local: LocalClient, uploads) -> None:
    document = local.scan(uploads)[0]
    assert any("PRIYA SHARMA" in line for line in document["header_lines"])
    assert "Sharma" in document["suggested_surnames"]


def test_redaction_works_without_an_api(local: LocalClient, uploads, plans) -> None:
    bundle = local.redact(uploads, plans)
    with zipfile.ZipFile(io.BytesIO(bundle.archive)) as archive:
        output = archive.read(OUTPUT)
    text = text_of(output)
    assert SURNAME.lower() not in text.lower()
    assert "PRIYA" in text
    assert bundle.manifest["failed"] == 0


def test_verify_round_trip(local: LocalClient, uploads, plans) -> None:
    bundle = local.redact(uploads, plans)
    with zipfile.ZipFile(io.BytesIO(bundle.archive)) as archive:
        output = archive.read(OUTPUT)
    audit = local.verify([(OUTPUT, output)], [{"filename": OUTPUT, "surnames": [SURNAME]}])
    assert audit["passed"] is True


# ---------------------------------------------------------------------------
# It agrees with the HTTP client
# ---------------------------------------------------------------------------


class _TestClientTransport(RedactorClient):
    """RedactorClient routed through FastAPI's TestClient instead of the network."""

    def __init__(self, api: TestClient) -> None:
        super().__init__("http://testserver")
        self._api = api

    def health(self) -> dict:
        return self._api.get("/api/v1/health").json()

    def scan(self, uploads: list) -> list[dict]:
        return self._api.post("/api/v1/scan", files=self._files(uploads)).json()["documents"]

    def verify(self, uploads: list, plans: list) -> dict:
        return self._api.post(
            "/api/v1/verify", files=self._files(uploads), data={"plans": json.dumps(plans)}
        ).json()


@pytest.fixture
def over_http() -> _TestClientTransport:
    return _TestClientTransport(TestClient(create_app()))


def test_scan_shapes_match(local: LocalClient, over_http, uploads) -> None:
    assert sorted(local.scan(uploads)[0]) == sorted(over_http.scan(uploads)[0])


def test_scan_values_match(local: LocalClient, over_http, uploads) -> None:
    mine, theirs = local.scan(uploads)[0], over_http.scan(uploads)[0]
    for key in ("filename", "pages", "has_text_layer", "suggested_output_name"):
        assert mine[key] == theirs[key], key


def test_health_shapes_match(local: LocalClient, over_http) -> None:
    assert sorted(local.health()) == sorted(over_http.health())


def test_verify_shapes_match(local: LocalClient, over_http, uploads, plans) -> None:
    bundle = local.redact(uploads, plans)
    with zipfile.ZipFile(io.BytesIO(bundle.archive)) as archive:
        output = archive.read(OUTPUT)
    files = [(OUTPUT, output)]
    audit_plan = [{"filename": OUTPUT, "surnames": [SURNAME]}]
    assert sorted(local.verify(files, audit_plan)) == sorted(
        over_http.verify(files, audit_plan)
    )


# ---------------------------------------------------------------------------
# It enforces the same limits the HTTP layer would
# ---------------------------------------------------------------------------


def test_batch_size_is_capped(monkeypatch: pytest.MonkeyPatch, uploads) -> None:
    monkeypatch.setenv("CV_REDACTOR_MAX_FILES", "0")
    get_settings.cache_clear()
    try:
        with pytest.raises(ApiError, match="too many files"):
            LocalClient().scan(uploads)
    finally:
        get_settings.cache_clear()


def test_file_size_is_capped(monkeypatch: pytest.MonkeyPatch, uploads) -> None:
    monkeypatch.setenv("CV_REDACTOR_MAX_UPLOAD_MB", "0")
    get_settings.cache_clear()
    try:
        with pytest.raises(ApiError, match="limit is 0 MB"):
            LocalClient().scan(uploads)
    finally:
        get_settings.cache_clear()


def test_a_bad_plan_raises_the_shared_error(local: LocalClient, uploads) -> None:
    with pytest.raises(ApiError, match="invalid redaction plan"):
        local.redact(uploads, [{"surnames": ["Sharma"]}])  # no filename


def test_ocr_can_be_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment without the OCR models should say so, not pretend."""
    monkeypatch.setenv("CV_REDACTOR_ENABLE_OCR", "0")
    get_settings.cache_clear()
    try:
        assert LocalClient().health()["ocr_available"] is False
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# The chooser
# ---------------------------------------------------------------------------


def test_no_api_configured_runs_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CV_REDACTOR_API_URL", raising=False)
    assert isinstance(make_client(), LocalClient)


def test_a_configured_api_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_REDACTOR_API_URL", "http://api:8000")
    client = make_client()
    assert isinstance(client, RedactorClient)
    assert client.base_url == "http://api:8000"


def test_an_explicit_url_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_REDACTOR_API_URL", "http://api:8000")
    assert make_client("http://other:9000").base_url == "http://other:9000"


def test_blank_configuration_falls_back_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_REDACTOR_API_URL", "   ")
    assert isinstance(make_client(), LocalClient)
