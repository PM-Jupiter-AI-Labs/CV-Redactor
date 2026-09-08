"""Redaction of .docx files.

Word splits a single visible string across as many `w:t` nodes as it likes --
an email address can be three runs because the spell-checker touched it -- and
`paragraph.runs` silently skips any run nested inside a `w:hyperlink`, which is
exactly where one of this corpus's emails was hiding.

So this walks the XML directly: every `w:p` in every part (body, headers,
footers, tables, text boxes), concatenating its `w:t` nodes into one string,
deciding on that, then writing the survivors back node by node.
"""

from __future__ import annotations

import contextlib
import re
import shutil
from typing import Any

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn

from . import Result
from . import config as C
from . import patterns as P
from .rules import Span, redact_spans, surname_re

#: Core properties that carry the author's identity.
_DOC_PROPERTIES: tuple[str, ...] = (
    "author",
    "last_modified_by",
    "title",
    "subject",
    "comments",
    "category",
    "keywords",
)


def _paragraph_text(paragraph: Any) -> str:
    """Everything the paragraph says, however many runs it is split across."""
    return "".join(node.text or "" for node in paragraph.iter(qn("w:t")))


def redact_paragraph(
    paragraph: Any,
    sre: re.Pattern[str] | None,
    header: bool = True,
    first: str | None = None,
) -> int:
    """Redact one `w:p` element in place. Returns the number of spans removed."""
    nodes = list(paragraph.iter(qn("w:t")))
    if not nodes:
        return 0
    text: str = "".join(node.text or "" for node in nodes)
    if not text.strip():
        return 0

    spans: list[Span] = redact_spans(text, sre, header=header, first=first)
    if not spans:
        return 0

    keep: list[bool] = [True] * len(text)
    for start, end in spans:
        for i in range(max(0, start), min(len(text), end)):
            keep[i] = False

    # Write the survivors back, respecting the original run boundaries so the
    # formatting of whatever is left is untouched.
    pos: int = 0
    for node in nodes:
        current: str = node.text or ""
        node.text = "".join(
            char
            for char, alive in zip(current, keep[pos : pos + len(current)], strict=True)
            if alive
        )
        pos += len(current)
    return len(spans)


def redact_docx(src: str, dst: str, tokens: list[str], first: str | None = None) -> Result:
    """Write an anonymised copy of the .docx at `src` to `dst`."""
    shutil.copyfile(src, dst)
    document = Document(dst)
    sre = surname_re(tokens)
    hits: int = 0

    for part in document.part.package.iter_parts():
        element = getattr(part, "element", None)
        if element is None:
            continue

        in_header: bool = True
        for i, paragraph in enumerate(element.iter(qn("w:p"))):
            if P.SECTION_HEAD.match(_paragraph_text(paragraph)):
                in_header = False
            hits += redact_paragraph(
                paragraph,
                sre,
                header=in_header and i < C.DOCX_HEADER_PARAGRAPHS,
                first=first,
            )

        # The visible text of a hyperlink is handled above; this blanks the
        # target it points at, which is not shown anywhere.
        for _rel_id, rel in list(getattr(part, "rels", {}).items()):
            if rel.reltype == RT.HYPERLINK:
                rel._target = ""  # noqa: SLF001 - python-docx exposes no setter

    properties = document.core_properties
    for attribute in _DOC_PROPERTIES:
        # A property may be absent or read-only depending on how Word wrote it.
        with contextlib.suppress(Exception):
            setattr(properties, attribute, "")

    document.save(dst)
    # Page count is meaningless for a .docx: Word decides it at layout time.
    return Result(redactions=hits, pages=-1)
