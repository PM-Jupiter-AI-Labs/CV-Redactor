"""End-to-end tests for the API, against generated CVs rather than real ones.

Building the fixture PDFs here rather than committing samples keeps candidate
data out of the repository, and makes the assertions readable: the test says
which email it planted, so it can say exactly what should be gone.
"""

from __future__ import annotations

import io
import json
import zipfile

import pymupdf
import pytest
from fastapi.testclient import TestClient

from frontend.api.main import create_app
from resume_scrubber import pymupdf_compat as M

CONTACT_EMAIL: str = "priya.sharma@example.com"
CONTACT_PHONE: str = "+91 98765 43210"
SURNAME: str = "Sharma"


def make_cv(name: str = "PRIYA SHARMA") -> bytes:
    """A one-page CV with a contact block and a body worth keeping."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), name, fontsize=18)
    page.insert_text(
        (72, 115), f"{CONTACT_EMAIL} | {CONTACT_PHONE} | Pune, India", fontsize=10
    )
    page.insert_text((72, 140), "linkedin.com/in/priya-sharma-123", fontsize=10)
    page.insert_text((72, 175), "PROFESSIONAL SUMMARY", fontsize=12)
    page.insert_text(
        (72, 195), "Backend engineer with six years of Python experience.", fontsize=10
    )
    page.insert_text(
        (72, 215), "Built payment systems at Acme Technologies, Bangalore.", fontsize=10
    )
    data: bytes = doc.tobytes()
    doc.close()
    return data


def text_of(data: bytes) -> str:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        return "\n".join(M.page_text(page) for page in M.pages(doc))
    finally:
        doc.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def cv() -> bytes:
    return make_cv()


def upload(data: bytes, name: str = "Priya_Sharma_CV.pdf") -> list:
    return [("files", (name, data, "application/pdf"))]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_reports_version(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["version"]


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def test_scan_returns_the_header_for_reading(client: TestClient, cv: bytes) -> None:
    body = client.post("/api/v1/scan", files=upload(cv)).json()
    document = body["documents"][0]
    assert document["pages"] == 1
    assert document["has_text_layer"] is True
    assert any("PRIYA SHARMA" in line for line in document["header_lines"])


def test_scan_suggests_a_surname_from_the_filename(client: TestClient, cv: bytes) -> None:
    body = client.post("/api/v1/scan", files=upload(cv)).json()
    document = body["documents"][0]
    assert "Sharma" in document["suggested_surnames"]
    # "CV" is noise, not a name.
    assert "CV" not in document["suggested_surnames"]
    assert document["suggested_output_name"].startswith("Priya_")


def test_scan_rejects_an_unsupported_type(client: TestClient) -> None:
    files = [("files", ("notes.txt", b"hello", "text/plain"))]
    document = client.post("/api/v1/scan", files=files).json()["documents"][0]
    assert document["error"] is not None
    assert ".txt" in document["error"]


def test_scan_needs_a_file(client: TestClient) -> None:
    assert client.post("/api/v1/scan").status_code == 422


# ---------------------------------------------------------------------------
# Redact
# ---------------------------------------------------------------------------


def redact(client: TestClient, cv: bytes, surnames: list[str]) -> tuple[dict, bytes]:
    plans = [
        {
            "filename": "Priya_Sharma_CV.pdf",
            "surnames": surnames,
            "output_name": "Priya_Backend_Engineer.pdf",
        }
    ]
    response = client.post(
        "/api/v1/redact", files=upload(cv), data={"plans": json.dumps(plans)}
    )
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        output = bundle.read("Priya_Backend_Engineer.pdf")
    return manifest, output


def test_redaction_removes_contact_data(client: TestClient, cv: bytes) -> None:
    _, output = redact(client, cv, [SURNAME])
    text = text_of(output)
    assert CONTACT_EMAIL not in text
    assert "98765" not in text
    assert "linkedin.com" not in text


def test_redaction_removes_the_surname_and_keeps_the_first_name(
    client: TestClient, cv: bytes
) -> None:
    _, output = redact(client, cv, [SURNAME])
    text = text_of(output)
    assert SURNAME.lower() not in text.lower()
    assert "PRIYA" in text


def test_redaction_keeps_the_professional_content(client: TestClient, cv: bytes) -> None:
    _, output = redact(client, cv, [SURNAME])
    text = text_of(output)
    assert "Backend engineer with six years" in text
    assert "Acme Technologies" in text


def test_manifest_describes_the_batch(client: TestClient, cv: bytes) -> None:
    manifest, _ = redact(client, cv, [SURNAME])
    assert manifest["failed"] == 0
    assert manifest["total_redactions"] > 0
    entry = manifest["results"][0]
    assert entry["output_name"] == "Priya_Backend_Engineer.pdf"
    assert entry["unmapped"] is False


def test_a_missing_surname_is_flagged_not_refused(client: TestClient, cv: bytes) -> None:
    """The pattern rules still run; the caller is told the name will remain."""
    manifest, output = redact(client, cv, [])
    assert manifest["results"][0]["unmapped"] is True
    assert CONTACT_EMAIL not in text_of(output)
    assert "SHARMA" in text_of(output)


def test_one_bad_file_does_not_lose_the_batch(client: TestClient, cv: bytes) -> None:
    files = [
        ("files", ("Priya_Sharma_CV.pdf", cv, "application/pdf")),
        ("files", ("broken.pdf", b"not a pdf at all", "application/pdf")),
    ]
    response = client.post("/api/v1/redact", files=files)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        names = bundle.namelist()
    assert manifest["failed"] == 1
    assert any(n.startswith("Priya") for n in names)


def test_a_plan_cannot_escape_the_workspace(client: TestClient, cv: bytes) -> None:
    """A client-supplied output name is a filename, never a path."""
    plans = [
        {
            "filename": "Priya_Sharma_CV.pdf",
            "surnames": [SURNAME],
            "output_name": "../../escaped.pdf",
        }
    ]
    response = client.post(
        "/api/v1/redact", files=upload(cv), data={"plans": json.dumps(plans)}
    )
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        names = [n for n in bundle.namelist() if n != "manifest.json"]
    assert names == ["escaped.pdf"]


def test_a_malformed_plan_is_rejected(client: TestClient, cv: bytes) -> None:
    response = client.post("/api/v1/redact", files=upload(cv), data={"plans": "{not json"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def test_verify_passes_a_redacted_file(client: TestClient, cv: bytes) -> None:
    _, output = redact(client, cv, [SURNAME])
    files = [("files", ("Priya_Backend_Engineer.pdf", output, "application/pdf"))]
    plans = [{"filename": "Priya_Backend_Engineer.pdf", "surnames": [SURNAME]}]
    body = client.post("/api/v1/verify", files=files, data={"plans": json.dumps(plans)}).json()
    assert body["passed"] is True
    assert body["checked"] == 1


def test_verify_catches_an_unredacted_file(client: TestClient, cv: bytes) -> None:
    files = [("files", ("original.pdf", cv, "application/pdf"))]
    plans = [{"filename": "original.pdf", "surnames": [SURNAME]}]
    body = client.post("/api/v1/verify", files=files, data={"plans": json.dumps(plans)}).json()
    assert body["passed"] is False
    findings = " ".join(body["leaks"][0]["findings"])
    assert "EMAIL" in findings
    assert "NAME" in findings


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


def test_too_many_files_is_refused(monkeypatch: pytest.MonkeyPatch, cv: bytes) -> None:
    monkeypatch.setenv("CV_REDACTOR_MAX_FILES", "1")
    from frontend.api.settings import get_settings

    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        files = [
            ("files", ("a.pdf", cv, "application/pdf")),
            ("files", ("b.pdf", cv, "application/pdf")),
        ]
        assert client.post("/api/v1/scan", files=files).status_code == 413
    finally:
        get_settings.cache_clear()
