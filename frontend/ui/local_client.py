"""In-process client: the same four calls, without an API to host.

The UI normally talks to the FastAPI service over HTTP, which is what lets the
two run on separate machines. Some hosts will not run two processes, though --
Streamlit Community Cloud gives you exactly one -- and there the HTTP hop has
nothing on the other end.

So this implements the same four methods against `frontend.api.service`
directly. That is possible only because the service layer was written as plain
functions over bytes, with no FastAPI machinery in it: the request handling
lives in `main.py` and the work lives in `service.py`, and only the second is
needed here.

The responses are converted to the same JSON-shaped dicts the HTTP client
returns, so `app.py` cannot tell the difference and needs no branch.
"""

from __future__ import annotations

from frontend.api import service
from frontend.api.schemas import RedactionPlan
from frontend.api.settings import Settings, get_settings
from frontend.ui.client import ApiError, RedactionBundle, Upload


class LocalClient:
    """Runs the redactor in this process. Interchangeable with RedactorClient."""

    #: Shown in the sidebar in place of an API URL.
    base_url: str = "in-process"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings: Settings = settings or get_settings()

    @staticmethod
    def _plans(plans: list[dict]) -> dict[str, RedactionPlan]:
        """Validate the UI's plain dicts through the same schema the API uses."""
        try:
            parsed = [RedactionPlan.model_validate(plan) for plan in plans]
        except ValueError as exc:
            raise ApiError(f"invalid redaction plan: {exc}") from exc
        return {plan.filename: plan for plan in parsed}

    def _check_batch(self, uploads: list[Upload]) -> None:
        """Apply the limits the HTTP layer would have applied."""
        if len(uploads) > self.settings.max_files:
            raise ApiError(
                f"too many files: {len(uploads)}, limit is {self.settings.max_files}"
            )
        for name, data in uploads:
            if len(data) > self.settings.max_upload_bytes:
                raise ApiError(
                    f"{name} is {len(data) // 1024 // 1024} MB, "
                    f"limit is {self.settings.max_upload_mb} MB"
                )

    # -- the same four calls ----------------------------------------------

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": service.version(),
            "ocr_available": self.settings.enable_ocr,
        }

    def scan(self, uploads: list[Upload]) -> list[dict]:
        self._check_batch(uploads)
        return [document.model_dump() for document in service.scan_documents(uploads)]

    def redact(self, uploads: list[Upload], plans: list[dict]) -> RedactionBundle:
        self._check_batch(uploads)
        archive, manifest = service.redact_documents(
            uploads, self._plans(plans), enable_ocr=self.settings.enable_ocr
        )
        return RedactionBundle(archive=archive, manifest=manifest.model_dump())

    def verify(self, uploads: list[Upload], plans: list[dict]) -> dict:
        self._check_batch(uploads)
        return service.audit_documents(uploads, self._plans(plans)).model_dump()
