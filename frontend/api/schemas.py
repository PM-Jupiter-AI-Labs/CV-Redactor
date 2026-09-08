"""Request and response shapes for the API.

These are the contract between the service and any client, so they are written
out explicitly rather than inferred from the redactor's internals.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentSummary(BaseModel):
    """What a scan can tell you about one uploaded CV.

    The header lines are the point: a surname cannot be detected automatically,
    so a person has to read the top of the document and say which word it is.
    """

    filename: str
    pages: int = Field(description="Page count, or -1 for a .docx")
    has_text_layer: bool = Field(description="False for a scan, which has to go through OCR")
    header_lines: list[str] = Field(
        default_factory=list, description="First lines of page one, for reading"
    )
    suggested_surnames: list[str] = Field(
        default_factory=list,
        description="Guesses from the filename only. Always confirm them.",
    )
    suggested_output_name: str = Field(
        description="Filename that keeps the first name and drops the surname"
    )
    error: str | None = Field(default=None, description="Set if the file could not be read")


class ScanResponse(BaseModel):
    documents: list[DocumentSummary]


class RedactionPlan(BaseModel):
    """What to do with one file. Supplied by the client, per document."""

    filename: str = Field(description="Must match the uploaded filename exactly")
    surnames: list[str] = Field(
        default_factory=list,
        description=(
            "Every family name and identifier to remove. A token starting "
            "'re:' is treated as a raw regular expression."
        ),
    )
    output_name: str | None = Field(
        default=None, description="Defaults to the suggested name from the scan"
    )
    photo_xrefs: list[int] = Field(
        default_factory=list, description="PDF image ids to delete (headshots)"
    )
    reinsert_first_name: str | None = Field(
        default=None,
        description="For a glued 'RafiAhmed' token: delete the word, redraw this",
    )


class FileResult(BaseModel):
    """The outcome for one file, mirrored into the download as manifest.json."""

    filename: str
    output_name: str
    redactions: int = 0
    pages: int = 0
    used_ocr: bool = False
    unmapped: bool = Field(
        default=False, description="No surnames given, so one is probably still present"
    )
    error: str | None = None


class RedactResponse(BaseModel):
    """The manifest returned alongside the redacted files."""

    results: list[FileResult]
    total_redactions: int
    failed: int


class AuditFinding(BaseModel):
    filename: str
    findings: list[str]


class VerifyResponse(BaseModel):
    """The audit, in the same shape the command line reports it."""

    checked: int
    leaks: list[AuditFinding] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    scanned: list[str] = Field(default_factory=list)
    passed: bool = Field(description="True when no personal data was found")


class HealthResponse(BaseModel):
    status: str
    version: str
    ocr_available: bool
