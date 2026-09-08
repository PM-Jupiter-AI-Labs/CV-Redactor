"""Audit the anonymised CVs: what leaked through, and what was lost.

    python -m resume_scrubber.verify [-i original_cv] [-o redacted_cv] [--ocr]

Five checks, only the first of which fails the run:

1. Leaks      -- emails, phones, links, surnames, dates of birth, link
                 annotations and metadata, in the extracted text *and* in the
                 raw bytes and decompressed streams, so text hiding outside the
                 page is caught too.
2. Loss       -- source lines that vanished without carrying contact data.
3. Photos     -- images big enough to be a face.
4. First name -- every output should still say who it is.
5. Scans      -- with --ocr, scanned outputs are re-read and re-checked.

A clean text audit is necessary and not sufficient: render two or three pages
and look at them. Two real defects passed this and were caught only by eye.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from docx import Document

from . import config as C
from . import patterns as P
from . import pymupdf_compat as M
from .names import OUT_NAME, SURNAMES
from .rules import surname_re

#: Emails and URLs baked into embedded font licences and certificates. These
#: appear in every PDF that embeds a Microsoft or SIL font. `impallari`,
#: `pixelspread` and `rfuenzalida` are the Raleway copyright; `andre-fuchs` and
#: `kerning-pairs` sit inside a sentence about kerning research.
BOILERPLATE: re.Pattern[str] = re.compile(
    r"verisign|microsoft|adobe|sil\.org|monotype|ascender|purl\.org|w3\.org|"
    r"apache|vsu\.ru|typoland|dejavu|gust\.org|ams\.org|color\.org|openxml|"
    r"andre-fuchs|kerning-pairs|pixelspread|impallari|rfuenzalida",
    re.I,
)

#: A source line that disappeared is expected if it carried contact data.
CONTACT_LINE: re.Pattern[str] = re.compile(
    r"@|http|www\.|linkedin|github|leetcode|portfolio|\+\d|\b\d{6,}\b|mobile|"
    r"phone|contact|e-?mail|date of birth|marital",
    re.I,
)

#: An email-shaped run of bytes with no lowercase letter is a run of glyph ids
#: in a decompressed font stream ("F.O@F.OFF"), not an address.
_EMAIL_IN_BYTES: re.Pattern[bytes] = re.compile(
    rb"[A-Za-z0-9._%+-]{3,}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)
_LINK_IN_BYTES: re.Pattern[bytes] = re.compile(
    rb"(?:linkedin|github|leetcode)\.com/[A-Za-z0-9/_.-]+", re.I
)

EXIT_OK: int = 0
EXIT_LEAKS: int = 1
EXIT_USAGE: int = 2


@dataclass
class Audit:
    """Everything the audit found, separated by how much it matters."""

    checked: int = 0
    leaks: dict[str, list[str]] = field(default_factory=dict)
    lost: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    scanned: list[str] = field(default_factory=list)


def text_of(path: Path) -> str:
    """All the text of a document, however it is stored."""
    if path.suffix.lower() == ".docx":
        document = Document(str(path))
        parts: list[str] = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts += [cell.text for cell in row.cells]
        return "\n".join(parts)

    doc: pymupdf.Document = pymupdf.open(path)
    try:
        return "\n".join(M.page_text(page) for page in M.pages(doc))
    finally:
        doc.close()


def lines_of(path: Path) -> list[str]:
    return [line.strip() for line in text_of(path).splitlines() if line.strip()]


def blobs(path: Path) -> Iterator[bytes]:
    """Raw bytes plus anything that inflates, to catch text outside the page."""
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                yield archive.read(name)
        return

    raw: bytes = path.read_bytes()
    yield raw
    for match in re.finditer(rb"stream\r?\n", raw):
        try:
            yield zlib.decompressobj().decompress(
                raw[match.end() : match.end() + C.STREAM_SCAN_BYTES]
            )
        except zlib.error:
            # Not every "stream" keyword introduces a deflate stream.
            continue


def pii_in(text: str, sre: re.Pattern[str] | None) -> list[str]:
    """Personal data still readable in `text`."""
    found: list[str] = []
    found += [f"EMAIL: {m.group(0)}" for m in P.EMAIL.finditer(text)]
    found += [f"URL: {m.group(0)}" for m in P.URL.finditer(text)]
    found += [f"PHONE: {text[a:b]}" for a, b in P.phone_spans(text)]
    # Per line: the date pattern allows whitespace between day and month, so
    # over joined text a trailing digit picks up the next line.
    found += [f"DOB: {m.group(0)}" for line in text.splitlines() for m in P.DOB.finditer(line)]
    if sre is not None:
        found += [f"NAME: {m.group(0)}" for m in sre.finditer(text)]
    return found


def pii_in_structure(path: Path, tokens: list[str]) -> list[str]:
    """Personal data hiding in the file rather than on the page."""
    found: list[str] = []
    plain: list[str] = [t for t in tokens if not t.startswith("re:")]

    for blob in blobs(path):
        for token in plain:
            pattern: bytes = rb"(?<![A-Za-z])" + re.escape(token.encode()) + rb"(?![A-Za-z])"
            if re.search(pattern, blob, re.I):
                found.append(f"NAME IN FILE STRUCTURE: {token}")

        for match in _EMAIL_IN_BYTES.finditer(blob):
            hit: str = match.group(0).decode("latin1")
            if not any(c.islower() for c in hit):
                continue
            if not BOILERPLATE.search(hit):
                found.append(f"EMAIL IN FILE STRUCTURE: {hit}")

        for match in _LINK_IN_BYTES.finditer(blob):
            link: str = match.group(0).decode("latin1")
            if not BOILERPLATE.search(link):
                found.append(f"LINK IN FILE STRUCTURE: {link}")

    return found


def pdf_annotations_and_metadata(path: Path) -> list[str]:
    """Link targets and document properties that should have been cleared."""
    found: list[str] = []
    doc: pymupdf.Document = pymupdf.open(path)
    try:
        for page in M.pages(doc):
            found += [
                f"LINK ANNOTATION: {link['uri']}"
                for link in page.get_links()
                if link.get("uri")
            ]
        metadata = doc.metadata or {}
        found += [
            f"METADATA {key}={value}"
            for key, value in metadata.items()
            if value and key in ("author", "title", "subject", "keywords")
        ]
    finally:
        doc.close()
    return found


def possible_photos(path: Path) -> list[str]:
    """Images with the shape of a headshot, for a human to glance at."""
    notes: list[str] = []
    doc: pymupdf.Document = pymupdf.open(path)
    try:
        for page in M.pages(doc):
            page_area: float = page.rect.get_area() or 1.0
            for image in page.get_images(full=True):
                width, height = image[2], image[3]
                if not (
                    width >= C.PHOTO_MIN_PX
                    and height >= C.PHOTO_MIN_PX
                    and C.PHOTO_MIN_RATIO <= width / height <= C.PHOTO_MAX_RATIO
                ):
                    continue
                rects = page.get_image_rects(image[0])
                # A full-page image is the scan itself, not a headshot.
                if rects and rects[0].get_area() / page_area > C.PHOTO_MAX_PAGE_FRACTION:
                    continue
                notes.append(f"image {width}x{height} - check it is not a photo")
    finally:
        doc.close()
    return notes


def ocr_text(path: Path) -> str:
    """Read a scanned output back through OCR."""
    from .ocr_redact import ocr_lines

    doc: pymupdf.Document = pymupdf.open(path)
    try:
        return "\n".join(line for page in doc for line in ocr_lines(page, C.OCR_VERIFY_DPI))
    finally:
        doc.close()


def audit(source_dir: Path, output_dir: Path, use_ocr: bool = False) -> Audit:
    """Check every anonymised file in `output_dir`."""
    result = Audit()
    reverse: dict[str, str] = {v: k for k, v in OUT_NAME.items()}
    files: list[Path] = sorted(
        p
        for p in output_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".pdf", ".docx")
    )
    result.checked = len(files)

    for path in files:
        tokens: list[str] = SURNAMES.get(reverse.get(path.name, ""), [])
        sre: re.Pattern[str] | None = surname_re(tokens)
        found: list[str] = []

        text: str = text_of(path)
        if not text.strip() and path.suffix.lower() == ".pdf":
            result.scanned.append(path.name)
        found += pii_in(text, sre)

        if path.suffix.lower() == ".pdf":
            found += pdf_annotations_and_metadata(path)
        found += pii_in_structure(path, tokens)

        if path.suffix.lower() == ".pdf":
            result.notes += [f"{path.name}: {note}" for note in possible_photos(path)]

        first: str = path.name.split("_")[0].split(".")[0]
        if first and first.lower() not in text.lower() and path.name not in result.scanned:
            result.notes.append(f"{path.name}: first name '{first}' not found in the text")

        if found:
            result.leaks[path.name] = list(dict.fromkeys(found))

    if use_ocr and result.scanned:
        print("Re-OCR of scanned outputs...")
        for name in result.scanned:
            tokens = SURNAMES.get(reverse.get(name, ""), [])
            found = pii_in(ocr_text(output_dir / name), surname_re(tokens))
            if found:
                result.leaks.setdefault(name, []).extend(f"OCR {x}" for x in found)
    elif result.scanned:
        result.notes.append(
            f"{len(result.scanned)} scanned output(s) have no text layer - "
            "re-run with --ocr to read them back"
        )

    result.lost = content_loss(source_dir, output_dir)
    return result


def content_loss(source_dir: Path, output_dir: Path) -> list[str]:
    """Source lines that vanished without carrying any contact data.

    A handful of these is normal -- a city inside an employer line, a surname
    inside the candidate's own publication list -- so they are reported for
    review rather than treated as failures.
    """
    lost: list[str] = []
    if not source_dir.is_dir():
        return lost

    for source_name, output_name in OUT_NAME.items():
        source: Path = source_dir / source_name
        output: Path = output_dir / output_name
        if not (source.is_file() and output.is_file()):
            continue
        try:
            kept = set(lines_of(output))
            lost += [
                f"{output_name}: {line[:90]}"
                for line in lines_of(source)
                if line not in kept
                and len(line) > C.LOST_LINE_MIN_CHARS
                and not CONTACT_LINE.search(line)
            ]
        except Exception:  # noqa: BLE001 - loss reporting must never fail a run
            continue
    return lost


def report(result: Audit, output_dir: Path) -> None:
    """Print the audit in the order a reader needs it."""
    print(f"\nChecked {result.checked} file(s) in {output_dir}\n")

    if result.leaks:
        print("PERSONAL DATA STILL PRESENT")
        for name, items in result.leaks.items():
            print(f"  {name}")
            for item in items[:8]:
                print(f"      {item}")
        print()
    else:
        print("PASS - no emails, phones, links, names, dates of birth, link")
        print("       annotations or metadata found, in the text or in the file\n")

    if result.lost:
        print("CONTENT REMOVED THAT CARRIED NO CONTACT DATA (usually a city inside")
        print("an employer or university line - review, do not assume it is a bug)")
        for item in result.lost[:15]:
            print(f"  {item}")
        print()

    if result.notes:
        print("WORTH A LOOK")
        for note in dict.fromkeys(result.notes):
            print(f"  {note}")
        print()

    print("Rendering two or three pages and looking at them is still worth doing:")
    print("regex-clean output can still be visually broken.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m resume_scrubber.verify",
        description="Audit anonymised CVs for leftover personal data.",
    )
    parser.add_argument("-i", "--input", default=C.DEFAULT_IN, help="original CVs")
    parser.add_argument("-o", "--output", default=C.DEFAULT_OUT, help="anonymised CVs")
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="also re-OCR scanned outputs (slow, needs rapidocr)",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="also write the findings as JSON, for CI to consume",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_dir: Path = Path(args.input).resolve()
    output_dir: Path = Path(args.output).resolve()

    if not output_dir.is_dir():
        print(
            f"error: output folder not found: {output_dir} (run redact first)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    result: Audit = audit(source_dir, output_dir, use_ocr=args.ocr)
    report(result, output_dir)

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "checked": result.checked,
                    "leaks": result.leaks,
                    "lost": result.lost,
                    "notes": result.notes,
                    "scanned": result.scanned,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return EXIT_LEAKS if result.leaks else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
