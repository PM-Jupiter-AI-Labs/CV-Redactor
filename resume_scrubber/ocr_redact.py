"""Redaction of scanned, image-only PDFs.

There is no text to delete, so painting a rectangle over the contact block
would leave the original pixels underneath and recover on any extraction. This
path instead rasterises each page, blanks the matched regions *in the pixel
data*, and rebuilds the page from that raster. Nothing recoverable survives
because the recoverable layer no longer exists.

The cost is precision: OCR returns one box and one string per line, so
character offsets are proportional estimates rather than real geometry. Two
guards make that safe -- see `_blank_spans`.
"""

from __future__ import annotations

import io
import re
from typing import Any

import numpy as np
import pymupdf
from PIL import Image

from . import Result
from . import config as C
from . import patterns as P
from . import pymupdf_compat as M
from .rules import Span, redact_spans, surname_re

#: RapidOCR loads ~90 MB of ONNX models, so build it once and only on demand:
#: a corpus with no scans should never pay for it.
_engine: Any = None


def engine() -> Any:
    """The shared RapidOCR instance, constructed on first use."""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def page_image(page: pymupdf.Page, dpi: int = C.OCR_DPI) -> np.ndarray:
    """Render a page to an RGB array, dropping any alpha channel."""
    pixmap: pymupdf.Pixmap = page.get_pixmap(dpi=dpi)
    raw: np.ndarray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )
    # copy=True because the buffer belongs to the pixmap, which is about to go.
    return np.array(raw[:, :, :3], copy=True)


def ocr_lines(page: pymupdf.Page, dpi: int = C.OCR_DPI) -> list[str]:
    """Read a page back as text. Used by the audit, not by the redactor."""
    result, _ = engine()(page_image(page, dpi))
    return [text for _box, text, _score in (result or [])]


def _blank_spans(text: str, spans: list[Span]) -> list[Span]:
    """Widen OCR spans until a sliver of a glyph cannot survive them.

    Two corpus failures drove this. A line reading
    `Linkedin:niraj-kumar-879bb8250` has no ".com", so only the surname matched
    and the slug survived either side of it -- hence: a line that mentions a
    contact keyword at all is blanked whole. And a one-pixel sliver of a "K"
    survived a span that stopped exactly on the character boundary, and read
    back as `Niraj I` -- hence: a span reaching within two characters of either
    end is snapped to it.
    """
    length: int = max(len(text), 1)
    if P.CONTACT_HINT.search(text):
        return [(0, length)]
    return [
        (0 if start <= 2 else start, length if end >= length - 2 else end)
        for start, end in spans
    ]


def redact_scanned(src: str, dst: str, tokens: list[str], first: str | None = None) -> Result:
    """Write an anonymised copy of the scanned PDF at `src` to `dst`."""
    doc: pymupdf.Document = pymupdf.open(src)
    out: pymupdf.Document = pymupdf.open()
    sre: re.Pattern[str] | None = surname_re(tokens)
    hits: int = 0

    for pno, page in enumerate(M.pages(doc)):
        image: np.ndarray = page_image(page)
        height: int = image.shape[0]
        result, _ = engine()(image)

        for box, text, _score in result or []:
            xs: list[float] = [point[0] for point in box]
            ys: list[float] = [point[1] for point in box]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)

            # No laid-out line numbers here, so the contact block is defined
            # geometrically: the top fifth of the first page.
            header: bool = pno == 0 and (y0 + y1) / 2 < height * 0.22
            spans: list[Span] = redact_spans(text, sre, header, first)
            if not spans:
                continue

            length: int = max(len(text), 1)
            pad: float = (x1 - x0) * C.OCR_PAD_FRACTION + C.OCR_PAD_PIXELS
            for start, end in _blank_spans(text, spans):
                left: float = x0 + (max(start, 0) / length) * (x1 - x0) - pad
                right: float = x0 + (min(end, length) / length) * (x1 - x0) + pad
                image[
                    max(int(y0) - 2, 0) : int(y1) + 3,
                    max(int(left), 0) : min(int(right), image.shape[1]),
                ] = 255
                hits += 1

        buffer = io.BytesIO()
        Image.fromarray(image).save(
            buffer, format="JPEG", quality=C.OCR_JPEG_QUALITY, optimize=True
        )
        new_page: pymupdf.Page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=buffer.getvalue())

    out.set_metadata({})
    out.save(dst, garbage=4, deflate=True)
    pages: int = out.page_count
    out.close()
    doc.close()
    return Result(redactions=hits, pages=pages)
