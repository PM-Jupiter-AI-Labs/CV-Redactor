"""Narrow the parts of PyMuPDF whose type information is looser than the API.

Nothing here changes behaviour; it exists so the rest of the package can be
type-checked without every call site defending against a value it can never
receive.

Two gaps are papered over:

`Page.get_text` is one function whose return type is chosen by its first
argument -- "text" gives a `str`, "words" a list of tuples -- which the stubs
can only express as a union of every possibility. Calling `.strip()` on the
result of `get_text("text")` is therefore an error to a checker and obviously
fine to a reader. The wrappers below state the option and the type together, so
the assumption is written down once instead of assumed everywhere.

The `PDF_REDACT_*` constants and `Document.__iter__` exist at runtime but are
missing from the published stubs.
"""

from __future__ import annotations

from collections.abc import Iterator

import pymupdf

#: One word as `get_text("words")` returns it:
#: (x0, y0, x1, y1, text, block number, line number, word number).
WordTuple = tuple[float, float, float, float, str, int, int, int]


def page_text(page: pymupdf.Page) -> str:
    """The page's text. `get_text("text")` always returns a string."""
    return page.get_text("text")  # type: ignore[return-value]


def page_words(page: pymupdf.Page) -> list[WordTuple]:
    """The page's words with their boxes. `get_text("words")` returns tuples."""
    return page.get_text("words")  # type: ignore[return-value]


def page_spans(page: pymupdf.Page) -> list[dict]:
    """Every text span on the page, flattened out of the block/line nesting.

    Carries the font details (size, colour, flags, origin) needed to redraw a
    name that had to be deleted along with the surname it was glued to.
    """
    blocks: list[dict] = page.get_text("dict")["blocks"]  # type: ignore[index]
    return [
        span
        for block in blocks
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    ]


def pages(doc: pymupdf.Document) -> Iterator[pymupdf.Page]:
    """Iterate a document's pages. `Document` is iterable, but not in the stubs."""
    for number in range(doc.page_count):
        yield doc[number]


# Redaction options. These are real module attributes; only the stubs omit them.
REDACT_IMAGE_NONE: int = pymupdf.PDF_REDACT_IMAGE_NONE  # type: ignore[attr-defined]
REDACT_IMAGE_REMOVE: int = pymupdf.PDF_REDACT_IMAGE_REMOVE  # type: ignore[attr-defined]
REDACT_LINE_ART_NONE: int = pymupdf.PDF_REDACT_LINE_ART_NONE  # type: ignore[attr-defined]
REDACT_LINE_ART_REMOVE_IF_COVERED: int = (
    pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED  # type: ignore[attr-defined]
)
REDACT_TEXT_NONE: int = pymupdf.PDF_REDACT_TEXT_NONE  # type: ignore[attr-defined]
REDACT_TEXT_REMOVE: int = pymupdf.PDF_REDACT_TEXT_REMOVE  # type: ignore[attr-defined]
