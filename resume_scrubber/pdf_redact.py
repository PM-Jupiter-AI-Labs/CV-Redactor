"""Redaction of PDFs that have a real text layer.

The important property is that text is *deleted*, not covered. Drawing a black
box leaves the glyphs in the content stream, where any copy-paste or extraction
recovers them; `apply_redactions` with PDF_REDACT_TEXT_REMOVE takes them out.

A PDF also keeps copies of its text where nobody looks -- the tagged-structure
tree, bookmark titles, XMP metadata, embedded files -- so the visible page being
clean is not the same as the file being clean. `strip_hidden_copies` handles
that, and `verify` checks it by scanning the raw bytes.
"""

from __future__ import annotations

import contextlib
import unicodedata
from typing import NamedTuple

import pymupdf

from . import Result
from . import config as C
from . import patterns as P
from . import pymupdf_compat as M
from .rules import Span, redact_spans, surname_re


class Word(NamedTuple):
    """One word as PyMuPDF reports it, named so the indices stop being cryptic."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int
    line: int
    word_no: int

    @property
    def rect(self) -> pymupdf.Rect:
        return pymupdf.Rect(self.x0, self.y0, self.x1, self.y1)


#: (block, line) identifies one laid-out line of the page.
LineKey = tuple[int, int]


def _page_words(page: pymupdf.Page) -> list[Word]:
    return [Word(*w) for w in M.page_words(page)]


def _lines(words: list[Word]) -> list[tuple[LineKey, list[Word]]]:
    """Group words into laid-out lines, ordered top-to-bottom then left-to-right."""
    grouped: dict[LineKey, list[Word]] = {}
    for word in words:
        grouped.setdefault((word.block, word.line), []).append(word)
    ordered: list[LineKey] = sorted(
        grouped,
        key=lambda k: (min(w.y0 for w in grouped[k]), min(w.x0 for w in grouped[k])),
    )
    return [(key, sorted(grouped[key], key=lambda w: w.x0)) for key in ordered]


def _join(words: list[Word]) -> tuple[str, list[tuple[int, int, Word]]]:
    """Join words with single spaces, keeping each word's character offsets."""
    text: str = ""
    offsets: list[tuple[int, int, Word]] = []
    for word in words:
        start: int = len(text)
        text += word.text
        offsets.append((start, len(text), word))
        text += " "
    return text, offsets


def _strip_links(
    doc: pymupdf.Document, page: pymupdf.Page
) -> tuple[list[pymupdf.Rect], list[pymupdf.Rect]]:
    """Delete every link annotation, reporting where they were.

    Returns the rectangles of all links, and of those whose visible text was
    only ever a label for the URL ("LinkedIn", "View Profile"). The first set is
    used to find orphaned underlines, the second to delete the label itself --
    left alone it still names the profile it used to point at.
    """
    link_rects: list[pymupdf.Rect] = []
    label_rects: list[pymupdf.Rect] = []
    for link in page.get_links():
        if link.get("uri"):
            rect: pymupdf.Rect = pymupdf.Rect(link["from"])
            link_rects.append(rect)
            if P.link_label_only(page.get_textbox(rect).strip()):
                label_rects.append(rect)
        page.delete_link(link)
    if page.get_links():
        # A damaged xref can make delete_link silently do nothing. Drop the
        # whole annotation array instead.
        doc.xref_set_key(page.xref, "Annots", "[]")
    return link_rects, label_rects


def _mark(page: pymupdf.Page, rect: pymupdf.Rect) -> None:
    """Queue a word's rectangle for deletion, inset so it misses its neighbours."""
    box: pymupdf.Rect = pymupdf.Rect(rect)
    inset: float = box.height * C.REDACT_INSET
    box.y0 += inset
    box.y1 -= inset
    page.add_redact_annot(box)


def _wrapped_matches(page: pymupdf.Page, words: list[Word]) -> int:
    """Catch emails, URLs and phone numbers hard-wrapped across two lines.

    Within a block the words are re-joined with the line breaks closed up, so a
    split address matches as one string. Words that were already side by side
    keep their space: joining those lets the email pattern's local part run
    backwards into the name ("Nisham" + "...@gmail.com").
    """
    marked: int = 0
    blocks: dict[int, list[Word]] = {}
    for word in words:
        blocks.setdefault(word.block, []).append(word)

    for block_words in blocks.values():
        ordered: list[Word] = sorted(block_words, key=lambda w: (w.line, w.word_no))
        text: str = ""
        offsets: list[tuple[int, int, Word]] = []
        prev_line: int | None = None
        prev_end: str = ""
        for word in ordered:
            # A wrapped link never breaks straight after a closing bracket or a
            # comma, so leave that break open: closing it up lets the URL's
            # greedy \S+ eat the first word of the next line.
            if prev_line is not None and (word.line == prev_line or prev_end in ")],;:!?\"'"):
                text += " "
            prev_line, prev_end = word.line, word.text[-1:]
            start: int = len(text)
            text += word.text
            offsets.append((start, len(text), word))

        spans: list[Span] = [
            (m.start(), m.end()) for rx in (P.EMAIL, P.URL) for m in rx.finditer(text)
        ]
        spans += P.phone_spans(text)
        if not spans:
            continue

        for start, end, word in offsets:
            # A bullet or rule swept up by a greedy \S+ is not contact data.
            if not any(c.isalnum() for c in word.text):
                continue
            if any(start < e and s < end for s, e in spans):
                _mark(page, word.rect)
                marked += 1
    return marked


def _sweep_underlines(
    page: pymupdf.Page,
    link_rects: list[pymupdf.Rect],
    struck: dict[LineKey, list[pymupdf.Rect]],
) -> None:
    """Remove the line art left floating where redacted text used to be.

    A hyperlink's underline is drawn art, not text, so deleting the address
    leaves a rule hanging in the contact block. Sweep the thin strip just below
    the words that went: REMOVE_IF_COVERED only drops art that fits entirely
    inside a redaction box, and a full-width section rule never does.
    """
    bands: list[pymupdf.Rect] = [
        rect for rect in link_rects if not any(c.isalnum() for c in page.get_textbox(rect))
    ]
    for rects in struck.values():
        bands.append(
            pymupdf.Rect(
                min(r.x0 for r in rects) - 1,
                min(r.y1 for r in rects) - 1,
                max(r.x1 for r in rects) + 1,
                max(r.y1 for r in rects) + C.UNDERLINE_BAND_PT,
            )
        )
    if not bands:
        return
    # Rect + Rect adds componentwise in PyMuPDF: this grows the band slightly
    # so art that starts a hair outside it is still covered.
    for band in bands:
        page.add_redact_annot(band + pymupdf.Rect(-1, -1, 1, 2))
    page.apply_redactions(
        images=M.REDACT_IMAGE_NONE,
        graphics=M.REDACT_LINE_ART_REMOVE_IF_COVERED,
        text=M.REDACT_TEXT_NONE,
    )


def _reinsert(
    page: pymupdf.Page, restorations: list[tuple[pymupdf.Rect, dict]], first: str
) -> None:
    """Draw a kept first name back in, matching the font it was cut out of.

    Only needed where the first and last name are a single glued token
    ("RafiAhmed"): the whole word has to go, so the part worth keeping is
    written back afterwards. Doing it before the redaction would erase it again.
    """
    for rect, span in restorations:
        colour: int = span.get("color", 0)
        page.insert_text(
            (rect.x0, span.get("origin", (rect.x0, rect.y1))[1]),
            first,
            fontsize=span.get("size", rect.height * 0.8),
            fontname="hebo" if span.get("flags", 0) & 2**4 else "helv",
            color=(
                ((colour >> 16) & 255) / 255,
                ((colour >> 8) & 255) / 255,
                (colour & 255) / 255,
            ),
        )


def _remove_photos(doc: pymupdf.Document, xrefs: list[int]) -> int:
    """Delete headshots, in a pass of their own.

    Separate from the text pass so that image removal can never catch an icon
    that happens to sit against a redacted word.
    """
    removed: int = 0
    for xref in xrefs:
        for page in M.pages(doc):
            rects: list[pymupdf.Rect] = page.get_image_rects(xref)
            if not rects:
                continue
            for rect in rects:
                page.add_redact_annot(rect)
            page.apply_redactions(
                images=M.REDACT_IMAGE_REMOVE,
                graphics=M.REDACT_LINE_ART_NONE,
                text=M.REDACT_TEXT_NONE,
            )
            removed += len(rects)
    return removed


def strip_hidden_copies(doc: pymupdf.Document) -> None:
    """Drop every copy of the text that is not on the page.

    Bookmarks, the tagged-structure tree (/ActualText, /Alt, /T, /E), XMP and
    embedded files all carry duplicates of what the page says. One CV in this
    corpus kept the candidate's email and GitHub URL in the structure tree with
    a perfectly clean visible page.

    Each step is guarded: these keys are optional, and a malformed PDF that
    cannot express one is not a reason to abandon a file that is otherwise fine.
    """
    doc.set_metadata({})
    for step in (doc.del_xml_metadata, lambda: doc.set_toc([])):
        # These structures are optional; a PDF that has none is already clean.
        with contextlib.suppress(Exception):
            step()

    catalog: int = doc.pdf_catalog()
    for key in ("StructTreeRoot", "MarkInfo", "Outlines", "Names", "AcroForm", "PageMode"):
        with contextlib.suppress(Exception):
            doc.xref_set_key(catalog, key, "null")

    with contextlib.suppress(Exception):
        for i in range(doc.embfile_count() - 1, -1, -1):
            doc.embfile_del(i)


def redact_pdf(
    src: str,
    dst: str,
    tokens: list[str],
    keep: str | None = None,
    photos: list[int] | None = None,
    first: str | None = None,
) -> Result:
    """Write an anonymised copy of the text PDF at `src` to `dst`.

    Args:
        src: The original CV. Never modified.
        dst: Where to write. Overwritten if it exists.
        tokens: This CV's surname entries from names.py.
        keep: First name to draw back in, for a glued "RafiAhmed" token.
        photos: Image xrefs to delete, from names.py PHOTOS.
        first: First name that must survive the residue sweep.
    """
    doc: pymupdf.Document = pymupdf.open(src)
    sre = surname_re(tokens)
    hits: int = 0

    for pno, page in enumerate(M.pages(doc)):
        link_rects, label_rects = _strip_links(doc, page)

        # Font details of the original spans, needed only if a name is restored.
        span_info: list[dict] = M.page_spans(page)
        words: list[Word] = _page_words(page)
        restorations: list[tuple[pymupdf.Rect, dict]] = []
        struck: dict[LineKey, list[pymupdf.Rect]] = {}

        in_header: bool = pno == 0
        for idx, (key, line_words) in enumerate(_lines(words)):
            text, offsets = _join(line_words)
            if P.SECTION_HEAD.match(text):
                in_header = False
            header: bool = in_header and idx < C.HEADER_LINES
            top: bool = in_header and idx < C.TOP_LINES

            # Words that are the visible label of a stripped link go whatever
            # the text says; passing them in as spans means the residue sweep
            # also clears the separators left around them.
            pre: list[Span] = [
                (start, end)
                for start, end, word in offsets
                if any((word.rect.tl + word.rect.br) / 2 in rect for rect in label_rects)
            ]

            spans: list[Span] = redact_spans(text, sre, header, first, pre, top)
            if not spans:
                continue

            for start, end, word in offsets:
                if not any(start < e and s < end for s, e in spans):
                    continue
                _mark(page, word.rect)
                struck.setdefault(key, []).append(word.rect)
                hits += 1

                # Glued first+last name: note it now, write it back after the
                # redaction has been applied.
                normalised: str = unicodedata.normalize("NFKD", word.text).lower()
                is_contact: bool = bool(
                    P.EMAIL.search(word.text) or P.URL.search(word.text) or "@" in word.text
                )
                if (
                    keep
                    and not is_contact
                    and normalised.startswith(keep.lower())
                    and normalised != keep.lower()
                ):
                    source_span: dict = next(
                        (
                            span
                            for span in span_info
                            if pymupdf.Rect(span["bbox"]).intersects(word.rect)
                        ),
                        {},
                    )
                    restorations.append((word.rect, source_span))

        hits += _wrapped_matches(page, words)

        # Images and line art are protected here so that icons, rules and
        # coloured header bands survive; the underline sweep that follows is
        # the one place line art is allowed to go.
        page.apply_redactions(
            images=M.REDACT_IMAGE_NONE,
            graphics=M.REDACT_LINE_ART_NONE,
            text=M.REDACT_TEXT_REMOVE,
        )
        _sweep_underlines(page, link_rects, struck)
        if keep:
            _reinsert(page, restorations, keep)

    hits += _remove_photos(doc, photos or [])
    strip_hidden_copies(doc)

    # garbage=4 is what actually drops the objects the steps above orphaned.
    doc.save(dst, garbage=4, deflate=True, clean=True)
    pages: int = doc.page_count
    doc.close()
    return Result(redactions=hits, pages=pages)
