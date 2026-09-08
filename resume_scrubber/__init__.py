"""Strip personally identifying data from candidate CVs.

Run the tools as modules from the repository root:

    python -m resume_scrubber.redact      # write anonymised copies
    python -m resume_scrubber.verify      # audit the result
    python -m resume_scrubber.scan        # print headers of unmapped CVs

The package is deliberately dependency-light and offline: regex rules, PyMuPDF,
python-docx and a local OCR model. Nothing is sent anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

__version__ = "1.0.0"


@dataclass(frozen=True, slots=True)
class Result:
    """What redacting one file did.

    Lives here rather than in one of the format modules because all three of
    them return it, and none of them should have to import another.
    """

    #: How many separate pieces of text or image were removed.
    redactions: int
    #: Pages written, or -1 for a .docx (Word decides that at layout time).
    pages: int


__all__ = ["Result", "__version__"]
