"""Every tunable number the redactor uses, in one place.

These are thresholds, not preferences: each one was set by looking at what it
did to a real corpus, and the comment says which way it fails. Changing one is
a deliberate act, so change it here rather than inline.
"""

from __future__ import annotations

from typing import Final

# --- default folders -------------------------------------------------------

DEFAULT_IN: Final[str] = "original_cv"
DEFAULT_OUT: Final[str] = "redacted_cv"

# --- how far the "contact block" reaches -----------------------------------
# The contact block is where the aggressive rules are allowed to run: a bare
# city name there is the candidate's home, further down it is an employer's
# office. The first section heading normally ends the block; these caps only
# backstop a CV whose sections carry no recognisable heading at all.

#: Lines from the top of page one that the loose rules (bare city names) trust.
HEADER_LINES: Final[int] = 10
#: Lines that the precise rules (postal codes, rows of dead labels) trust.
#: Wider because those rules cannot fire on ordinary prose.
TOP_LINES: Final[int] = 25
#: The same idea for DOCX, counted in paragraphs rather than laid-out lines.
DOCX_HEADER_PARAGRAPHS: Final[int] = 8

# --- residue sweep ---------------------------------------------------------
# What a contact line still gives away once its email and phone are gone.

#: Measured on the surviving text, not the source line: a contact row is long
#: while it still holds the URL. Past this it is prose, and a wrapped paragraph
#: that happens to mention a city must be left alone.
RESIDUE_MAX_CHARS: Final[int] = 100
#: More surviving words than this and the line is a sentence, not a stripped row.
RESIDUE_MAX_WORDS: Final[int] = 3
#: Removing a word can orphan the separator beside it, which can orphan the next.
#: Four passes is well past the point where the corpus stops changing.
RESIDUE_MAX_PASSES: Final[int] = 4

# --- address rules ---------------------------------------------------------

#: A whole line is only wiped as an address if it is at most this long. Longer
#: than this and a sentence mentioning a street word would be destroyed.
ADDRESS_MAX_CHARS: Final[int] = 80

# --- PDF geometry ----------------------------------------------------------

#: Shrink each redaction box by this fraction of the line height, top and
#: bottom. Without it the box overlaps the line above and eats its descenders.
REDACT_INSET: Final[float] = 0.2
#: Height of the strip swept below removed words to catch a link's underline.
#: Small enough that a full-width section rule is never fully covered.
UNDERLINE_BAND_PT: Final[float] = 4.0

# --- OCR (scanned, image-only PDFs) ----------------------------------------

#: Render resolution for the OCR path. Below ~150 the recogniser starts missing
#: phone digits; above ~300 it is much slower for no measurable gain.
OCR_DPI: Final[int] = 200
#: Higher for the audit, so verify reads back at least as well as redact wrote.
OCR_VERIFY_DPI: Final[int] = 260
#: OCR returns one box per line, so character offsets are proportional guesses.
#: Pad every blanked span by this much or slivers of a glyph survive and read
#: back as text.
OCR_PAD_FRACTION: Final[float] = 0.06
OCR_PAD_PIXELS: Final[float] = 10.0
#: JPEG quality for the rebuilt raster page.
OCR_JPEG_QUALITY: Final[int] = 88

# --- verification ----------------------------------------------------------

#: Smallest image, in pixels per side, worth flagging as a possible face.
PHOTO_MIN_PX: Final[int] = 150
#: Plausible aspect ratios for a headshot.
PHOTO_MIN_RATIO: Final[float] = 0.5
PHOTO_MAX_RATIO: Final[float] = 2.0
#: An image covering more of the page than this is the scan itself, not a photo.
PHOTO_MAX_PAGE_FRACTION: Final[float] = 0.8
#: Only report a vanished source line if it was at least this long; shorter ones
#: are separators and labels, which are meant to vanish.
LOST_LINE_MIN_CHARS: Final[int] = 45
#: Cap on how much of each decompressed stream is scanned for hidden text.
STREAM_SCAN_BYTES: Final[int] = 200_000
