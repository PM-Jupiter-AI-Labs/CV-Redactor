"""The HTTP surface: routing, validation and limits, and nothing else.

    uvicorn frontend.api.main:app --reload

Three endpoints mirroring the command line's three steps -- scan, redact,
verify -- plus a health check. The service is stateless: a client sends the
files it wants worked on with every call, and nothing is retained between them.
That costs an upload on the second call and buys not having a server that
accumulates candidate CVs.
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import ValidationError

from . import service
from .schemas import (
    HealthResponse,
    RedactionPlan,
    ScanResponse,
    VerifyResponse,
)
from .settings import Settings, get_settings

log: logging.Logger = logging.getLogger("frontend.api")

API_PREFIX: str = "/api/v1"


def _read_uploads(files: list[UploadFile], settings: Settings) -> list[tuple[str, bytes]]:
    """Pull uploads into memory, enforcing the count and size limits.

    Reading into memory is deliberate: a CV is a few hundred kilobytes, and it
    keeps the data out of the filesystem for as long as possible.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="no files were uploaded"
        )
    if len(files) > settings.max_files:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"too many files: {len(files)}, limit is {settings.max_files}",
        )

    uploads: list[tuple[str, bytes]] = []
    for upload in files:
        data: bytes = upload.file.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"{upload.filename} is {len(data) // 1024 // 1024} MB, "
                    f"limit is {settings.max_upload_mb} MB"
                ),
            )
        uploads.append((upload.filename or "upload", data))
    return uploads


def _parse_plans(raw: str | None) -> dict[str, RedactionPlan]:
    """Decode the per-file plan that rides alongside the uploads.

    It arrives as a JSON string in a multipart form field, because multipart is
    how the files arrive and mixing a JSON body into that is not worth the
    complication.
    """
    if not raw or not raw.strip():
        return {}
    try:
        parsed: list[RedactionPlan] = [
            RedactionPlan.model_validate(item) for item in json.loads(raw)
        ]
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid redaction plan: {exc.errors()}",
        ) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"redaction plan is not valid JSON: {exc}",
        ) from exc
    return {plan.filename: plan for plan in parsed}


def create_app() -> FastAPI:
    """Build the application. A factory so tests can make an isolated one."""
    settings: Settings = get_settings()
    app = FastAPI(
        title="CV Redactor API",
        version=service.version(),
        summary="Strip personal data from candidate CVs.",
        description=(
            "Stateless. Uploaded files live in a temporary directory for the "
            "duration of a request and are deleted before it returns."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get(f"{API_PREFIX}/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        """Liveness, and whether this deployment can handle scanned PDFs."""
        return HealthResponse(
            status="ok", version=service.version(), ocr_available=settings.enable_ocr
        )

    @app.post(f"{API_PREFIX}/scan", response_model=ScanResponse, tags=["redaction"])
    def scan(files: list[UploadFile] = File(...)) -> ScanResponse:
        """Read each CV's header so a person can say what the surname is.

        This is the step that cannot be automated: nothing in the word "Sharma"
        marks it as a name rather than a place, so the header has to be read.
        """
        uploads = _read_uploads(files, settings)
        return ScanResponse(documents=service.scan_documents(uploads))

    @app.post(f"{API_PREFIX}/redact", tags=["redaction"])
    def redact(
        files: list[UploadFile] = File(...),
        plans: str | None = Form(default=None, description="JSON array of RedactionPlan"),
    ) -> Response:
        """Redact a batch and return a zip of the results.

        The archive also contains `manifest.json`, the same summary the
        response headers carry, so a download is self-describing.
        """
        uploads = _read_uploads(files, settings)
        archive, manifest = service.redact_documents(
            uploads, _parse_plans(plans), enable_ocr=settings.enable_ocr
        )
        return Response(
            content=archive,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="redacted_cvs.zip"',
                "X-Total-Redactions": str(manifest.total_redactions),
                "X-Failed-Count": str(manifest.failed),
            },
        )

    @app.post(f"{API_PREFIX}/verify", response_model=VerifyResponse, tags=["redaction"])
    def verify(
        files: list[UploadFile] = File(...),
        plans: str | None = Form(default=None, description="JSON array of RedactionPlan"),
    ) -> VerifyResponse:
        """Audit already-redacted files for anything that survived."""
        uploads = _read_uploads(files, settings)
        return service.audit_documents(uploads, _parse_plans(plans))

    return app


app: FastAPI = create_app()
