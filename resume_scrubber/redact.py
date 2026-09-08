"""Command line entry point: read a folder of CVs, write anonymised copies.

    python -m resume_scrubber.redact [-i original_cv] [-o redacted_cv]

Originals are never modified. The output folder is written into, not cleared,
so re-running after editing names.py refreshes only what changed.

Exit status is 0 when every file was written, 1 when any file failed, and 2 for
a usage error. With --fail-on-unmapped, a CV with no names.py entry also fails
the run, which is what you want in CI: the pattern rules will have run, but the
surname will still be in the document.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from . import Result
from . import config as C
from . import pymupdf_compat as M
from .docx_redact import redact_docx
from .names import OUT_NAME, PHOTOS, REINSERT, SURNAMES
from .pdf_redact import redact_pdf

log: logging.Logger = logging.getLogger("resume_scrubber")

#: What this tool knows how to open.
SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".pdf", ".docx"})

#: Exit codes, so a caller can tell a failure from a typo.
EXIT_OK: int = 0
EXIT_FAILED: int = 1
EXIT_USAGE: int = 2


@dataclass
class RunReport:
    """Totals for one invocation, printed as the closing summary."""

    written: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    scanned: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)


def has_text_layer(path: Path) -> bool:
    """True if the PDF carries extractable text, false if it is a scan."""
    doc: pymupdf.Document = pymupdf.open(path)
    try:
        return any(M.page_text(page).strip() for page in M.pages(doc))
    finally:
        doc.close()


def first_name_of(output_name: str) -> str:
    """The first name the output is filed under, which must survive redaction."""
    return output_name.split("_")[0].split(".")[0]


def redact_file(source: Path, destination: Path, report: RunReport) -> Result:
    """Redact one CV, choosing the path that suits the file.

    Writes to a temporary neighbour and renames on success, so an interrupted
    run can never leave a half-written file that looks like a finished one.
    """
    name: str = source.name
    tokens: list[str] = SURNAMES.get(name, [])
    first: str = first_name_of(destination.name)
    partial: Path = destination.with_name(destination.name + ".partial")

    try:
        if source.suffix.lower() == ".docx":
            result = redact_docx(str(source), str(partial), tokens, first)
        elif has_text_layer(source):
            result = redact_pdf(
                str(source),
                str(partial),
                tokens,
                REINSERT.get(name),
                PHOTOS.get(name),
                first,
            )
        else:
            # Imported here so a corpus with no scans never loads the OCR models.
            from .ocr_redact import redact_scanned

            result = redact_scanned(str(source), str(partial), tokens, first)
            report.scanned.append(destination.name)
        os.replace(partial, destination)
        return result
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def process(source_dir: Path, output_dir: Path, dry_run: bool = False) -> RunReport:
    """Redact every supported file in `source_dir` into `output_dir`."""
    report = RunReport()

    for source in sorted(source_dir.iterdir()):
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue

        destination: Path = output_dir / OUT_NAME.get(source.name, source.name)
        if source.name not in SURNAMES:
            report.unmapped.append(source.name)

        if dry_run:
            log.info("%s -> %s (dry run)", source.name, destination.name)
            report.written.append(destination.name)
            continue

        try:
            result: Result = redact_file(source, destination, report)
        except Exception as exc:  # noqa: BLE001 - one bad CV must not stop the run
            log.error("FAILED %s: %s: %s", source.name, type(exc).__name__, exc)
            report.failed.append((source.name, f"{type(exc).__name__}: {exc}"))
            continue

        log.info("%s -> %s  redactions=%d", source.name, destination.name, result.redactions)
        report.written.append(destination.name)

    return report


def summarise(report: RunReport, output_dir: Path) -> None:
    """Print the closing summary, including anything that needs a human."""
    print(f"\n{len(report.written)} file(s) written to {output_dir}")

    if report.failed:
        print(f"\n{len(report.failed)} FAILED:")
        for name, error in report.failed:
            print(f"  {name}: {error}")

    if report.scanned:
        print("\nOCR-redacted (scanned image PDFs, no text layer):")
        for name in report.scanned:
            print(f"  {name}")

    if report.unmapped:
        print(
            "\nWARNING - no entry in names.py, so only the pattern rules\n"
            "(email/phone/link/address/DOB) ran on these files. Their surname is\n"
            "probably still in the document. Add it and re-run:"
        )
        for name in report.unmapped:
            print(f"  {name}")

    print("\nNext: python -m resume_scrubber.verify")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m resume_scrubber.redact",
        description="Strip personal data from CVs and write anonymised copies.",
    )
    parser.add_argument(
        "-i",
        "--input",
        default=C.DEFAULT_IN,
        help=f"folder holding the original CVs (default: {C.DEFAULT_IN})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=C.DEFAULT_OUT,
        help=f"folder to write anonymised copies to (default: {C.DEFAULT_OUT})",
    )
    parser.add_argument(
        "--fail-on-unmapped",
        action="store_true",
        help="exit non-zero if any CV has no names.py entry (use this in CI)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be written without redacting anything",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="only report problems")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s"
    )

    source_dir: Path = Path(args.input).resolve()
    output_dir: Path = Path(args.output).resolve()

    if not source_dir.is_dir():
        print(f"error: input folder not found: {source_dir}", file=sys.stderr)
        return EXIT_USAGE
    if output_dir == source_dir:
        print("error: --output must differ from --input", file=sys.stderr)
        return EXIT_USAGE
    # Writing inside the input folder would feed this run's output back into the
    # next one, redacting already-redacted files against the wrong names.
    if source_dir in output_dir.parents:
        print(
            f"error: --output ({output_dir}) is inside --input ({source_dir})",
            file=sys.stderr,
        )
        return EXIT_USAGE

    output_dir.mkdir(parents=True, exist_ok=True)
    report: RunReport = process(source_dir, output_dir, dry_run=args.dry_run)
    summarise(report, output_dir)

    if report.failed:
        return EXIT_FAILED
    if args.fail_on_unmapped and report.unmapped:
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
