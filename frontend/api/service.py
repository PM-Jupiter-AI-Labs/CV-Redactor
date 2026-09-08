"""The work, kept apart from the HTTP layer.

Every function here takes bytes and returns values. Nothing touches a global,
reads `names.py`, or leaves anything on disk: uploads are written into a
temporary directory that is removed before the function returns, whatever
happens. That is what makes the API safe to run for other people's CVs.

The redactor's own CLI reads its surname table from `names.py`; the API instead
takes it per request, which is why this calls the format modules directly rather
than `resume_scrubber.redact.process`.
"""

from __future__ import annotations

import io
import json
import logging
import re
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from resume_scrubber import Result, __version__
from resume_scrubber import pymupdf_compat as M
from resume_scrubber.docx_redact import redact_docx
from resume_scrubber.pdf_redact import redact_pdf
from resume_scrubber.rules import surname_re
from resume_scrubber.verify import (
    pdf_annotations_and_metadata,
    pii_in,
    pii_in_structure,
    text_of,
)

from .schemas import (
    AuditFinding,
    DocumentSummary,
    FileResult,
    RedactionPlan,
    RedactResponse,
    VerifyResponse,
)

log: logging.Logger = logging.getLogger("frontend.api")

#: What the redactor can open.
SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".pdf", ".docx"})

#: How many lines of the first page a person needs in order to spot the surname.
HEADER_LINES: int = 14


class UnsupportedFile(ValueError):
    """Raised for an upload the redactor has no path for."""


@contextmanager
def _workspace() -> Iterator[Path]:
    """A temporary directory that is always removed, even on error."""
    with tempfile.TemporaryDirectory(prefix="cv-redactor-") as tmp:
        yield Path(tmp)


def _safe_name(filename: str) -> str:
    """Strip any directory component from a client-supplied name.

    An upload is named by whoever is calling, so "../../etc/passwd" has to
    become "passwd" before it is ever joined to a path.
    """
    return Path(filename).name or "upload"


def check_supported(filename: str) -> None:
    suffix: str = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFile(
            f"{filename}: only .pdf and .docx are supported, not {suffix or 'a file with no extension'}"
        )


def _first_name_from(filename: str) -> str:
    """The leading word of a filename, which is usually the candidate's name."""
    stem: str = Path(filename).stem
    parts: list[str] = [p for p in re.split(r"[\s_\-.]+", stem) if p]
    return parts[0] if parts else "Candidate"


def suggest_output_name(filename: str) -> str:
    """A neutral output name built from the first name and the file's type."""
    return f"{_first_name_from(filename)}_Redacted{Path(filename).suffix.lower()}"


def suggest_surnames(filename: str) -> list[str]:
    """Guesses from the filename alone.

    Worth showing because source filenames very often carry the full name, but
    they are only ever a starting point: the header still has to be read. Words
    that are obviously not names -- "resume", "cv", a year, a version marker --
    are dropped.
    """
    noise: set[str] = {
        "resume",
        "cv",
        "curriculum",
        "vitae",
        "final",
        "updated",
        "new",
        "latest",
        "copy",
        "doc",
        "docx",
        "pdf",
        "developer",
        "engineer",
        "python",
        "java",
        "senior",
        "junior",
        "fullstack",
        "full",
        "stack",
        "backend",
        "frontend",
        "years",
        "yrs",
        "naukri",
        "profile",
    }
    stem: str = Path(filename).stem
    words: list[str] = [w for w in re.split(r"[\s_\-.()\[\]]+", stem) if w]
    return [
        w
        for w in words[1:]  # words[0] is the first name, which is kept
        if len(w) > 2 and w.lower() not in noise and not any(c.isdigit() for c in w)
    ]


def scan_document(filename: str, data: bytes) -> DocumentSummary:
    """Read one CV well enough for a person to decide what to redact."""
    name: str = _safe_name(filename)
    summary = DocumentSummary(
        filename=name,
        pages=-1,
        has_text_layer=True,
        suggested_output_name=suggest_output_name(name),
        suggested_surnames=suggest_surnames(name),
    )
    try:
        check_supported(name)
        if Path(name).suffix.lower() == ".docx":
            with _workspace() as workspace:
                path: Path = workspace / name
                path.write_bytes(data)
                text: str = text_of(path)
        else:
            doc: pymupdf.Document = pymupdf.open(stream=data, filetype="pdf")
            try:
                summary.pages = doc.page_count
                text = M.page_text(doc[0]) if doc.page_count else ""
                summary.has_text_layer = any(
                    M.page_text(page).strip() for page in M.pages(doc)
                )
            finally:
                doc.close()

        lines: list[str] = [ln.strip() for ln in text.splitlines() if ln.strip()]
        summary.header_lines = lines[:HEADER_LINES]
    except Exception as exc:  # noqa: BLE001 - one unreadable file must not fail the batch
        log.warning("scan failed for %s: %s", name, exc)
        summary.error = f"{type(exc).__name__}: {exc}"
    return summary


def scan_documents(uploads: Iterable[tuple[str, bytes]]) -> list[DocumentSummary]:
    return [scan_document(name, data) for name, data in uploads]


def _redact_one(
    source: Path, destination: Path, plan: RedactionPlan, enable_ocr: bool
) -> tuple[Result, bool]:
    """Redact one file on disk, choosing the path that suits it."""
    first: str = _first_name_from(destination.name)

    if source.suffix.lower() == ".docx":
        return redact_docx(str(source), str(destination), plan.surnames, first), False

    doc: pymupdf.Document = pymupdf.open(source)
    try:
        has_text: bool = any(M.page_text(page).strip() for page in M.pages(doc))
    finally:
        doc.close()

    if has_text:
        return (
            redact_pdf(
                str(source),
                str(destination),
                plan.surnames,
                plan.reinsert_first_name,
                plan.photo_xrefs,
                first,
            ),
            False,
        )

    if not enable_ocr:
        raise RuntimeError(
            "this PDF is a scan with no text layer, and OCR is disabled on this deployment"
        )
    # Imported here so a deployment that never sees a scan never loads the models.
    from resume_scrubber.ocr_redact import redact_scanned

    return redact_scanned(str(source), str(destination), plan.surnames, first), True


def redact_documents(
    uploads: Iterable[tuple[str, bytes]],
    plans: dict[str, RedactionPlan],
    enable_ocr: bool = True,
) -> tuple[bytes, RedactResponse]:
    """Redact a batch, returning a zip archive and a manifest describing it.

    One file failing is reported against that file and does not stop the rest:
    a batch of fifty CVs should not be lost to one corrupt PDF.
    """
    results: list[FileResult] = []
    archive = io.BytesIO()

    with (
        _workspace() as workspace,
        zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle,
    ):
        for filename, data in uploads:
            name: str = _safe_name(filename)
            plan: RedactionPlan = plans.get(name) or RedactionPlan(filename=name)
            output_name: str = _safe_name(plan.output_name or suggest_output_name(name))
            record = FileResult(
                filename=name,
                output_name=output_name,
                unmapped=not plan.surnames,
            )
            try:
                check_supported(name)
                source: Path = workspace / f"in-{name}"
                destination: Path = workspace / f"out-{output_name}"
                source.write_bytes(data)

                result, used_ocr = _redact_one(source, destination, plan, enable_ocr)
                record.redactions = result.redactions
                record.pages = result.pages
                record.used_ocr = used_ocr
                bundle.write(destination, arcname=output_name)

                # Remove the original as soon as it is no longer needed, rather
                # than waiting for the workspace to go.
                source.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001 - report per file, keep going
                log.warning("redaction failed for %s: %s", name, exc)
                record.error = f"{type(exc).__name__}: {exc}"
            results.append(record)

        manifest = RedactResponse(
            results=results,
            total_redactions=sum(r.redactions for r in results),
            failed=sum(1 for r in results if r.error),
        )
        bundle.writestr("manifest.json", manifest.model_dump_json(indent=2))

    return archive.getvalue(), manifest


def audit_documents(
    uploads: Iterable[tuple[str, bytes]], plans: dict[str, RedactionPlan]
) -> VerifyResponse:
    """Re-check already-redacted files for anything that survived.

    This is the text and file-structure half of `resume_scrubber.verify`. The
    content-loss half needs both the original and the output, which the API does
    not keep, so it is left to the command line.
    """
    leaks: list[AuditFinding] = []
    notes: list[str] = []
    scanned: list[str] = []
    checked: int = 0

    with _workspace() as workspace:
        for filename, data in uploads:
            name: str = _safe_name(filename)
            try:
                check_supported(name)
            except UnsupportedFile as exc:
                notes.append(str(exc))
                continue

            checked += 1
            path: Path = workspace / name
            path.write_bytes(data)
            try:
                plan: RedactionPlan = plans.get(name) or RedactionPlan(filename=name)
                sre: re.Pattern[str] | None = surname_re(plan.surnames)

                text: str = text_of(path)
                if not text.strip() and path.suffix.lower() == ".pdf":
                    scanned.append(name)

                found: list[str] = pii_in(text, sre)
                if path.suffix.lower() == ".pdf":
                    found += pdf_annotations_and_metadata(path)
                found += pii_in_structure(path, plan.surnames)

                if found:
                    leaks.append(
                        AuditFinding(filename=name, findings=list(dict.fromkeys(found)))
                    )
            except Exception as exc:  # noqa: BLE001 - audit one file at a time
                notes.append(f"{name}: could not be audited: {type(exc).__name__}: {exc}")
            finally:
                path.unlink(missing_ok=True)

    if scanned:
        notes.append(
            f"{len(scanned)} file(s) have no text layer; a text audit cannot read them. "
            "Use the command line with --ocr to check those."
        )

    return VerifyResponse(
        checked=checked, leaks=leaks, notes=notes, scanned=scanned, passed=not leaks
    )


def manifest_from_zip(archive: bytes) -> RedactResponse | None:
    """Read the manifest back out of a redaction bundle."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            return RedactResponse.model_validate(json.loads(bundle.read("manifest.json")))
    except (KeyError, ValueError, zipfile.BadZipFile):
        return None


def version() -> str:
    return __version__
