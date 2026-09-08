"""Print the header of each CV, so surnames can be added to names.py.

    python -m resume_scrubber.scan [folder] [--all]

Only files with no names.py entry are shown, unless --all is given. This is the
first step when adding CVs: the pattern rules find emails, phones, links and
addresses on their own, but a surname is just a word, and only a human reading
the header can say which word it is.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf
from docx import Document

from . import config as C
from . import pymupdf_compat as M
from .names import SURNAMES

#: How many non-blank lines of the first page to show.
HEAD_LINES: int = 14

EXIT_OK: int = 0
EXIT_USAGE: int = 2


def head(path: Path) -> tuple[str, int]:
    """First-page text and page count. Page count is -1 for a .docx."""
    if path.suffix.lower() == ".docx":
        document = Document(str(path))
        parts: list[str] = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts += [cell.text for cell in row.cells]
        return "\n".join(parts), -1

    doc: pymupdf.Document = pymupdf.open(path)
    try:
        return M.page_text(doc[0]), doc.page_count
    finally:
        doc.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m resume_scrubber.scan",
        description="Print CV headers so surnames can be added to names.py.",
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=C.DEFAULT_IN,
        help=f"folder to scan (default: {C.DEFAULT_IN})",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="include CVs that already have a names.py entry",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder: Path = Path(args.folder).resolve()
    if not folder.is_dir():
        print(f"error: folder not found: {folder}")
        return EXIT_USAGE

    shown: int = 0
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in (".pdf", ".docx"):
            continue
        if not args.all and path.name in SURNAMES:
            continue

        try:
            text, pages = head(path)
        except Exception as exc:  # noqa: BLE001 - report and keep scanning
            print(f"=== {path.name} :: ERROR {type(exc).__name__}: {exc}\n")
            continue

        lines: list[str] = [line.strip() for line in text.splitlines() if line.strip()]
        note: str = "" if lines else "  (no text layer - scanned, OCR will read it)"
        print(f"=== {path.name} (pages={pages}, chars={len(text)}){note}")
        print("\n".join(lines[:HEAD_LINES]))
        print()
        shown += 1

    if not shown:
        print("Every CV in this folder already has an entry in names.py.")
        print("Pass --all to print them anyway.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
