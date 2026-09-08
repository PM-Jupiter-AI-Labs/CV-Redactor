"""Which characters of a line of text have to go.

This module is pure: strings in, character offsets out. It knows nothing about
PDFs, Word documents or OCR, which is what lets all three paths share exactly
the same decisions -- and what makes the whole thing testable without a corpus.

The entry point is `redact_spans`. It works in two stages:

1. Match the PII patterns (email, phone, link, date of birth, address, and the
   candidate's surname) and collect their offsets.
2. Sweep up the *residue*: what a contact line still gives away once its
   contents are gone. Deleting the email and the phone number leaves the
   scaffolding standing -- the "Email:" label, the "LinkedIn" that was the text
   of a now-dead link, the icon glyphs and "|" separators between them, and the
   home town the city list has never heard of. Individually harmless, together
   still a contact block pointing at one person.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from . import config as C
from . import patterns as P

#: Half-open character range `[start, end)` of a line, to be deleted.
Span = tuple[int, int]


class Chunk(NamedTuple):
    """A whitespace-delimited run of characters that no span removes."""

    start: int
    end: int
    text: str


def surname_re(tokens: list[str]) -> re.Pattern[str] | None:
    """Build the matcher for one CV's manually listed identifiers.

    A plain token matches case-insensitively on whole-word boundaries, with any
    internal space allowed to be any run of whitespace (a name can wrap across
    a line break). A token prefixed with ``re:`` is spliced in as a raw regex,
    which is how the awkward cases are expressed -- a bare middle initial that
    must only match after the first name, say.

    Returns None for an empty list, which callers treat as "no name to match".
    """
    if not tokens:
        return None
    parts: list[str] = [
        token[3:] if token.startswith("re:") else re.escape(token).replace(r"\ ", r"\s+")
        for token in tokens
    ]
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(parts) + r")(?![A-Za-z])", re.I)


def surviving(line: str, spans: list[Span]) -> list[Chunk]:
    """The chunks of `line` left standing once every span is deleted."""
    keep: list[bool] = [True] * len(line)
    for start, end in spans:
        for i in range(max(0, start), min(len(line), end)):
            keep[i] = False

    out: list[Chunk] = []
    run_start: int | None = None
    for i, char in enumerate(line):
        if keep[i] and not char.isspace():
            if run_start is None:
                run_start = i
        elif run_start is not None:
            out.append(Chunk(run_start, i, line[run_start:i]))
            run_start = None
    if run_start is not None:
        out.append(Chunk(run_start, len(line), line[run_start:]))
    return out


#: The two single-letter words English actually has. Everything else that is one
#: character long inside a contact block is an icon glyph or a stray initial.
_ONE_LETTER_WORDS: frozenset[str] = frozenset({"i", "a"})


def _is_word(token: str) -> bool:
    """True if a token carries meaning rather than being decoration.

    A single character is an icon glyph or a leftover initial, never a word --
    unless it is a digit, which is carrying a figure ("7+ years"), or one of the
    two letters that is a word on its own. Without that last exception the
    leading "I" of "I assure that the above information is correct" is read as
    debris and deleted.
    """
    if sum(c.isalnum() for c in token) > 1 or any(c.isdigit() for c in token):
        return True
    return token.strip(".,:;|()").lower() in _ONE_LETTER_WORDS


def residue_spans(line: str, spans: list[Span], first: str | None, sweep: bool) -> list[Span]:
    """Extra spans that clear up after `spans` on a contact line.

    `first` is the candidate's first name, which is kept deliberately and so is
    never swept. `sweep` enables the last and most aggressive step; callers set
    it only for lines that were a contact row to begin with.
    """
    if sum(len(c.text) + 1 for c in surviving(line, spans)) > C.RESIDUE_MAX_CHARS:
        return []

    extra: list[Span] = []
    keep_first: str = (first or "").lower()

    def kept(token: str) -> bool:
        # A trailing hyphen is not punctuation here, it is the joiner of the
        # profile slug the rest of the name was cut out of ("vasu-upadhyay"),
        # so a token ending in one is a fragment and loses its protection.
        return token.lower().strip(".,:;|") == keep_first

    # 1. Fragments. What is left of a name inside a profile handle is joined to
    #    the part that went, not separated by a space, so a surviving chunk that
    #    starts or ends exactly where a span does belongs to it.
    boundaries: set[int] = {a for a, _ in spans} | {b for _, b in spans}
    for chunk in surviving(line, spans):
        if not kept(chunk.text) and (chunk.start in boundaries or chunk.end in boundaries):
            extra.append((chunk.start, chunk.end))

    # 2. Labels. "LinkedIn" and "Portfolio" name a site and nothing else, so
    #    they go bare. The generic words ("mobile", "social") also occur in
    #    prose, so they only count when punctuated as a field label.
    alive: list[Chunk] = surviving(line, spans + extra)
    for i, chunk in enumerate(alive):
        if kept(chunk.text):
            continue
        following: str = alive[i + 1].text if i + 1 < len(alive) else ""
        labelled: bool = bool(P.CONTACT_LABEL.match(chunk.text)) and (
            not chunk.text[-1].isalnum() or not any(c.isalnum() for c in following)
        )
        if P.CONTACT_PLATFORM.match(chunk.text) or labelled:
            extra.append((chunk.start, chunk.end))

    # 3 and 4 feed each other: taking a word away can orphan the separator
    # beside it, and taking that away can leave the next word alone. Repeat
    # until the line stops changing.
    for _ in range(C.RESIDUE_MAX_PASSES):
        alive = surviving(line, spans + extra)
        word_starts: set[int] = {c.start for c in alive if _is_word(c.text)}
        changed: bool = False

        # 3. Separators. A "|" only reads as one while it still sits between two
        #    words; at the end of a stripped row it is debris.
        seen_word: bool = False
        for i, chunk in enumerate(alive):
            if chunk.start in word_starts:
                seen_word = True
                continue
            word_follows: bool = any(
                alive[j].start in word_starts for j in range(i + 1, len(alive))
            )
            if not (seen_word and word_follows):
                extra.append((chunk.start, chunk.end))
                changed = True

        # 4. The remainder. A contact row down to a couple of words is a home
        #    town or a dangling handle, not content -- unless one of those words
        #    is part of a job title, which belongs to the candidate's summary
        #    line rather than to their contact block.
        left: list[Chunk] = [c for c in surviving(line, spans + extra) if _is_word(c.text)]
        if (
            sweep
            and left
            and len(left) <= C.RESIDUE_MAX_WORDS
            and not any(P.TITLE_WORD.match(c.text.strip(".,:;|()")) for c in left)
        ):
            swept: list[Span] = [(c.start, c.end) for c in left if not kept(c.text)]
            extra += swept
            changed = changed or bool(swept)

        if not changed:
            break

    return extra


def redact_spans(
    line: str,
    sre: re.Pattern[str] | None,
    header: bool,
    first: str | None = None,
    pre: list[Span] | None = None,
    top: bool | None = None,
) -> list[Span]:
    """Character spans of `line` that must be removed.

    Args:
        line: One laid-out line of the document, words joined by single spaces.
        sre: This CV's surname matcher, or None if the CV has no names.py entry.
        header: The line is inside the contact block proper, where a bare city
            name is the candidate's own address.
        first: The first name, kept deliberately and never swept.
        pre: Spans decided outside the text -- the words of a hyperlink whose
            visible label gave it away -- so the residue sweep clears up after
            them too.
        top: The line is in the wider top-of-page-one region, which only the
            rules precise enough to be safe there may use: a postal address,
            and a row of dead labels. Defaults to `header`.

    Returns:
        Possibly overlapping spans. Callers are expected to treat them as a set
        of characters to drop, not as a partition.
    """
    if top is None:
        top = header

    spans: list[Span] = list(pre or [])
    # How many spans came from something that is actually contact data, as
    # opposed to the surname. Only the former justifies sweeping a line bare.
    contact: int = len(spans)

    for pattern in (P.EMAIL, P.URL, P.DOB, P.PERSONAL_LINE, P.GENDER_AGE):
        found: list[Span] = [(m.start(), m.end()) for m in pattern.finditer(line)]
        spans += found
        contact += len(found)

    phones: list[Span] = P.phone_spans(line)
    spans += phones
    contact += len(phones)

    if sre is not None:
        spans += [(m.start(), m.end()) for m in sre.finditer(line)]

    # A contact row whose addresses lived only in the link annotations has
    # nothing for the patterns above to match, and is left standing as a row of
    # bare labels ("LinkedIn | GitHub").
    if top and not spans and P.label_line(line):
        return [(0, len(line))]

    postcode: re.Match[str] | None = P.PIN.search(line)
    address_like: bool = (
        len(line) <= C.ADDRESS_MAX_CHARS
        and any(c.isdigit() for c in line)
        and (
            P.STREET.search(line) is not None
            or (postcode is not None and ("," in line or P.CITY_RE.search(line) is not None))
            or (P.ADDRESS_NUM.match(line) is not None and (top or "," in line))
        )
    )
    if address_like:
        return [*spans, (0, len(line))]

    contact_row: bool = (
        P.CONTACT_HINT.search(line) is not None or P.STREET.search(line) is not None
    )
    # A six-digit postal code is specific enough to trust further down the page.
    if top or contact_row:
        codes: list[Span] = [(m.start(), m.end()) for m in P.PIN.finditer(line)]
        spans += codes
        contact += len(codes)
    # A bare city name is not, since employers and universities have addresses
    # too, and stripping those guts the work history.
    if header or contact_row:
        cities: list[Span] = P.city_spans(line)
        spans += cities
        contact += len(cities)

    if spans:
        # Taking every last word off a line is only safe where the line was a
        # contact row to begin with; in the body it would eat the sentence.
        sweep: bool = bool(contact) and (top or contact_row)
        spans += residue_spans(line, spans, first, sweep)
    return spans
