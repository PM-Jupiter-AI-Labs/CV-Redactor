"""Tests for the decision layer.

Every case here is a line that actually appeared in a CV. The ones marked as
regressions are lines a previous version of the rules got wrong; they are the
reason the guard they exercise exists, so removing the guard must fail a test.
"""

from __future__ import annotations

import pytest

from resume_scrubber import patterns as P
from resume_scrubber.rules import redact_spans, residue_spans, surname_re, surviving


def redacted(line: str, **kwargs) -> str:
    """What is left of `line` after redaction, for readable assertions."""
    spans = redact_spans(line, kwargs.pop("sre", None), kwargs.pop("header", False), **kwargs)
    return " ".join(chunk.text for chunk in surviving(line, spans))


# ---------------------------------------------------------------------------
# Direct identifiers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "nisham55@gmail.com",
        "Email: work.rutulpatel@gmail.com",
        "nisham55 @ gmail.com",  # kerned apart into separate text elements
    ],
)
def test_emails_are_removed(line: str) -> None:
    assert "@" not in redacted(line, header=True)


@pytest.mark.parametrize(
    "line",
    [
        "+91 8802627170",
        "+254 795 150 677",
        "(+91) 86977-35353",
        "9155030932",
        "+971 502458960/+91 9892956080",
    ],
)
def test_phone_numbers_are_removed(line: str) -> None:
    assert not any(c.isdigit() for c in redacted(line, header=True))


@pytest.mark.parametrize(
    "line",
    [
        "2018 - 2022",
        "Jan 2020 - Dec 2023 2024",
    ],
)
def test_date_ranges_are_not_phone_numbers(line: str) -> None:
    """Regression: a run of years has the digit count of a phone number."""
    assert P.phone_spans(line) == []


@pytest.mark.parametrize(
    "line",
    [
        "https://github.com/someone",
        "linkedin.com/in/someone-12345",
        "portfolio.vercel.app",
    ],
)
def test_links_are_removed(line: str) -> None:
    assert redacted(line, header=True).strip() == ""


@pytest.mark.parametrize("line", ["Node.js", "ASP.NET", "React.js and Vue.js"])
def test_technology_names_are_not_links(line: str) -> None:
    """Regression: a bare-domain URL rule ate the skills section."""
    assert P.URL.search(line) is None


def test_date_of_birth_is_removed() -> None:
    assert "1990" not in redacted("Date of Birth: 01/02/1990", header=True)


# ---------------------------------------------------------------------------
# Declared fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Date of Birth: 01/02/1990",
        "Marital Status - Single",
        "Nationality: Indian | Gender: Male",
        "DOB - 01/02/1990",
    ],
)
def test_personal_fields_are_removed(line: str) -> None:
    assert P.PERSONAL_LINE.search(line) is not None


@pytest.mark.parametrize(
    "line",
    [
        "Improved gender diversity in tech by prioritizing outreach",
        "Integrated Aadhaar/UIDAI, SSO), implemented payment gateways",
    ],
)
def test_field_keywords_in_prose_are_left_alone(line: str) -> None:
    """Regression: the trailing `.*` used to swallow the rest of the sentence."""
    assert P.PERSONAL_LINE.search(line) is None


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_surname_goes_and_first_name_stays() -> None:
    sre = surname_re(["Aggarwal"])
    assert redacted("AAKASH AGGARWAL", sre=sre, header=True) == "AAKASH"


def test_regex_token_matches_only_in_context() -> None:
    """A bare initial must only match after the first name, not everywhere."""
    sre = surname_re([r"re:(?<=SATHISHKUMAR\s)A(?![A-Za-z])"])
    assert redacted("SATHISHKUMAR A", sre=sre) == "SATHISHKUMAR"
    assert redacted("Grade A in Mathematics", sre=sre) == "Grade A in Mathematics"


def test_surname_matches_across_a_line_break() -> None:
    sre = surname_re(["Emoe Kabu"])
    assert sre is not None
    assert sre.search("Benedict Emoe\nKabu") is not None


def test_no_tokens_means_no_matcher() -> None:
    assert surname_re([]) is None


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


def test_home_city_goes_in_the_contact_block() -> None:
    assert "Pune" not in redacted("Pune, Maharashtra", header=True)


def test_employer_city_survives_in_the_body() -> None:
    """An employer's location is not the candidate's address."""
    line = "Infogain India Pvt. Ltd, Pune"
    assert "Pune" in redacted(line, header=False)


def test_organisation_suffix_protects_its_city() -> None:
    assert P.city_spans("Bangalore Institute of Technology") == []


def test_state_code_needs_a_comma() -> None:
    """Regression: "MP" and "AS" are far too easy to hit inside ordinary text."""
    assert P.city_spans("Managed MP AS part of the rollout") == []
    assert P.city_spans("Bhopal, MP") != []


# ---------------------------------------------------------------------------
# Contact scaffolding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "LinkedIn |",
        "| GitHub:",
        "|",
        "PHONE",
        "E-MAIL",
        "LinkedIn | E-mail | GitHub | DagsHub",
    ],
)
def test_label_rows_are_recognised(line: str) -> None:
    assert P.label_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        "Profile",
        "Summary",
        "Data Analyst",
        "S E N I O R  E N G I N E E R",  # a letter-spaced title, not debris
    ],
)
def test_section_headings_are_not_label_rows(line: str) -> None:
    assert P.label_line(line) is False


@pytest.mark.parametrize(
    "anchor,expected",
    [
        ("GitHub", True),
        ("View Profile", True),
        ("Visit My Website", True),
        ("View Certificate", False),
        ("MotorHarbor", False),
    ],
)
def test_link_labels_versus_content(anchor: str, expected: bool) -> None:
    assert P.link_label_only(anchor) is expected


def test_separators_go_once_nothing_is_between_them() -> None:
    """The whole contact row goes, not just the email and phone inside it."""
    line = "Hoshiarpur, Punjab | +91 8847444813 | someone@gmail.com | LinkedIn | Portfolio"
    assert redacted(line, header=True).strip() == ""


def test_separator_between_two_words_stays() -> None:
    """Regression: the "&" in a surviving sentence is not debris."""
    line = "Bengaluru • Open to Remote & Contract Opportunities Worldwide"
    assert "&" in redacted(line, header=True)


def test_first_name_survives_the_sweep() -> None:
    line = "LinkedIn: Oluwatobi | +234 9058499534"
    assert redacted(line, header=True, first="Oluwatobi").strip() == "Oluwatobi"


def test_link_label_spans_reach_the_sweep() -> None:
    """A label deleted because of its link takes the separators with it.

    `pre` is how the PDF layer reports "this word was a hyperlink label": the
    text itself gives no reason to remove "LinkedIn", so without `pre` the row
    would keep its separators.
    """
    line = "LinkedIn | GitHub"
    assert redacted(line, header=True, pre=[(0, 8), (11, 17)]).strip() == ""


def test_job_title_survives_the_sweep() -> None:
    """A title on the header line is not personal data."""
    line = "Mohamed | Software Engineer | +91 9876543210"
    assert "Software Engineer" in redacted(line, header=True, first="Mohamed")


def test_profile_slug_fragment_goes_with_its_surname() -> None:
    """ "vasu-upadhyay" minus the surname leaves "vasu-", which is still a handle."""
    sre = surname_re(["Upadhyay"])
    assert redacted("vasu-upadhyay", sre=sre, header=True, first="Vasu").strip() == ""


def test_single_letter_words_are_not_debris() -> None:
    """Regression: the leading "I" of a declaration line read as an icon glyph.

    "I assure that the above-mentioned information is correct..." lost its "I"
    because a one-character token is normally a leftover initial or an icon.
    """
    sre = surname_re(["Mhaske"])
    line = (
        "I assure that the above-mentioned information is correct to the "
        "best of my knowledge. Date: PRIYANKA MHASKE"
    )
    assert redacted(line, sre=sre, first="Priyanka").startswith("I assure that")


def test_icon_glyphs_are_still_debris() -> None:
    """The exception above must not save the actual icon glyphs."""
    sre = surname_re(["Khot"])
    assert (
        redacted("§ SUHAS KHOT | +91 8668431256", sre=sre, header=True, first="Suhas")
        == "SUHAS"
    )


def test_prose_is_not_swept() -> None:
    """Regression: "Social" and "MOBILE" are label words that also occur in titles."""
    sre = surname_re(["Oloritun"])
    line = 'Oloritun, Rahman O., et al. "Change in BMI Predicted by Social Exposure"'
    assert "Social Exposure" in redacted(line, sre=sre, header=False)


def test_long_lines_are_left_to_the_patterns() -> None:
    """The residue sweep must not touch a wrapped paragraph."""
    line = (
        "Full-stack software engineer and IIT graduate with 3+ years of professional "
        "experience shipping React, Next.js and TypeScript products across domains"
    )
    assert residue_spans(line, [(0, 4)], None, True) == []


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line", ["Education", "PROFESSIONAL SUMMARY", "Work Experience", "TECHNICAL SKILLS"]
)
def test_section_headings_are_detected(line: str) -> None:
    assert P.SECTION_HEAD.match(line) is not None


@pytest.mark.parametrize("line", ["Software Engineer at Acme", "Summary of findings"])
def test_body_lines_are_not_section_headings(line: str) -> None:
    assert P.SECTION_HEAD.match(line) is None


# ---------------------------------------------------------------------------
# Span mechanics
# ---------------------------------------------------------------------------


def test_surviving_reports_offsets_and_text() -> None:
    chunks = surviving("abc def ghi", [(4, 7)])
    assert [(c.start, c.end, c.text) for c in chunks] == [(0, 3, "abc"), (8, 11, "ghi")]


def test_overlapping_spans_are_tolerated() -> None:
    assert surviving("abcdef", [(0, 3), (2, 5)]) == [(5, 6, "f")]


def test_empty_line_is_a_no_op() -> None:
    assert redact_spans("", None, True) == []
