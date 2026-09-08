"""Runtime configuration for the API, read from the environment.

Deliberately plain: a frozen dataclass built once at import. Every value has a
default that works for local development, so nothing has to be set to run it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _int_env(name: str, default: int) -> int:
    """Read an integer setting, falling back rather than crashing on rubbish."""
    raw: str | None = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the service needs to know about its environment."""

    #: Largest single upload accepted, in megabytes. A CV is a few hundred KB;
    #: this is a guard against someone posting a DVD image, not a real limit.
    max_upload_mb: int = 25
    #: Largest number of files in one request.
    max_files: int = 200
    #: Browser origins allowed to call the API. "*" is fine while the UI is the
    #: only client and the service is not public; narrow it before it is.
    cors_origins: tuple[str, ...] = ("*",)
    #: Whether the OCR path may run. Scanned CVs need ~400 MB of ONNX models, so
    #: a deployment that will never see one can switch this off and stay small.
    enable_ocr: bool = True

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, built once."""
    origins: str = os.environ.get("CV_REDACTOR_CORS_ORIGINS", "*")
    return Settings(
        max_upload_mb=_int_env("CV_REDACTOR_MAX_UPLOAD_MB", 25),
        max_files=_int_env("CV_REDACTOR_MAX_FILES", 200),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        enable_ocr=os.environ.get("CV_REDACTOR_ENABLE_OCR", "1") not in ("0", "false", "no"),
    )
