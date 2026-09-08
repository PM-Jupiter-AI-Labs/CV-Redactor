"""The patterns that recognise personal data, and the predicates over them.

Everything here is deliberately conservative. Each pattern was tightened until
it stopped destroying real content on a 150-CV corpus, and the comment above it
records what it used to break -- those are regression notes, not decoration.

Organised as:
    1. Direct identifiers  -- email, URL, phone, date of birth
    2. Declared fields     -- "Date of Birth:", "Gender | Male"
    3. Location            -- street words, postal codes, the city gazetteer
    4. Contact scaffolding -- the labels and separators left behind
    5. Document structure  -- section headings, job-title words
    6. Predicates          -- the functions the rules layer calls
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 1. Direct identifiers
# ---------------------------------------------------------------------------

#: An optional space either side of the "@" catches addresses that a PDF has
#: kerned into separate text elements.
EMAIL: re.Pattern[str] = re.compile(
    r"[A-Za-z0-9._%+\-]+\s?@\s?[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", re.I
)

#: Three alternatives: anything with a scheme or "www.", a bare profile host on
#: a known platform, and a bare project host on a known static-site provider.
#: Deliberately not "any domain" -- that would match "Node.js" and "ASP.NET".
URL: re.Pattern[str] = re.compile(
    r"(?:https?://|www\.)\S+"
    r"|\b(?:linkedin|github|gitlab|bitbucket|leetcode|hackerrank|geeksforgeeks|codechef|"
    r"codeforces|kaggle|medium|behance|dribbble|stackoverflow|stackexchange|naukri|"
    r"upwork|fiverr|topmate|peerlist|hashnode|dev)\.(?:com|io|org|to|in)\S*"
    r"|\b[A-Za-z0-9\-]+\.(?:netlify\.app|vercel\.app|github\.io|onrender\.com|web\.app|"
    r"herokuapp\.com|pages\.dev|streamlit\.app)\S*",
    re.I,
)

#: Candidate digit runs allowing +, spaces, dashes, parens and dots. The digit
#: count and the year check in `phone_spans` do the real filtering.
PHONE_CANDIDATE: re.Pattern[str] = re.compile(r"\(?\+?\d[\d\s\-().]{7,}\d")

#: Numeric ("01/02/1990") or spelled ("2nd Feb 1990"). Run this per line: the
#: `\s+` spans newlines, so over joined text a trailing digit picks up the next
#: line and "SDE-1" + "March 2025" reads as a date of birth.
DOB: re.Pattern[str] = re.compile(
    r"\b\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*(?:19|20)\d{2}\b"
    r"|\b(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(?:19|20)\d{2}\b",
    re.I,
)

# ---------------------------------------------------------------------------
# 2. Declared personal fields
# ---------------------------------------------------------------------------

#: A keyword only counts as a field label when a separator follows it, or when
#: it ends the line. Without that guard "gender diversity in tech by
#: prioritizing outreach..." and "Aadhaar/UIDAI, SSO), implemented payment
#: gateways..." had the rest of their sentence swallowed by the trailing `.*`.
PERSONAL_LINE: re.Pattern[str] = re.compile(
    r"(?:date\s*of\s*birth|d\.?o\.?b\.?|birth\s*date|marital\s*status|"
    r"gender|nationality|passport(?:\s*(?:no|number))?|father'?s?\s*name|"
    r"mother'?s?\s*name|religion|caste|aadhaar|aadhar|pan\s*(?:no|card)|"
    r"blood\s*group|permanent\s*address|current\s*address|residential\s*address|"
    r"present\s*address|correspondence\s*address)\b"
    r"\s*(?:[:\-–—|]\s*.*|$)",
    re.I,
)

#: "Male | 28", "Female, 31" -- an age next to a gender.
GENDER_AGE: re.Pattern[str] = re.compile(r"\b(?:Male|Female)\b\s*[|,\-]?\s*\d{1,2}\b", re.I)

# ---------------------------------------------------------------------------
# 3. Location
# ---------------------------------------------------------------------------

#: Words that only appear in a postal address. Note what is absent: "building",
#: "road" and "cross" were here once and destroyed "cross-functional teams" and
#: "wealth-building decisions".
STREET: re.Pattern[str] = re.compile(
    r"\b(?:flat\s*no|flat|plot\s*no|plot|house\s*no|h\.?\s?no|room\s*no|"
    r"apartment|apt\.|society|colony|nagar|vihar|puram|chawl|wadi|galli|marg|"
    r"sector\s*\d|phase\s*\d|p\.?o\.?\s*box|pin\s*code|postal\s*code)\b",
    re.I,
)

#: Six-digit Indian PIN code.
PIN: re.Pattern[str] = re.compile(r"\b\d{6}\b")

#: A house or plot number opening a postal address, e.g. "8/1361 Bhansali Pole".
ADDRESS_NUM: re.Pattern[str] = re.compile(
    r"^\s*\d{1,5}\s*[/\-]\s*\d{1,5}\b|^\s*\d{1,5}\s+[A-Z][a-z]+"
)

#: Places that identify where a candidate lives. A fixed gazetteer weighted to
#: India plus the other countries seen in this corpus; an unlisted town survives
#: unless it sits next to a postal code or a street word, so check the contact
#: block of a CV from a new region.
CITIES: list[str] = [
    "india",
    "pakistan",
    "kenya",
    "australia",
    "bangladesh",
    "uae",
    "u.a.e",
    "dubai",
    "nairobi",
    "melbourne",
    "dhaka",
    "sonargaon",
    "hyderabad",
    "telangana",
    "bengaluru",
    "bangalore",
    "pune",
    "mumbai",
    "navi mumbai",
    "thane",
    "maharashtra",
    "nagpur",
    "nashik",
    "surat",
    "ahmedabad",
    "rajkot",
    "vadodara",
    "gujarat",
    "indore",
    "bhopal",
    "jabalpur",
    "gwalior",
    "madhya pradesh",
    "m.p.",
    "ludhiana",
    "punjab",
    "chandigarh",
    "delhi",
    "new delhi",
    "noida",
    "gurgaon",
    "gurugram",
    "ghaziabad",
    "faridabad",
    "lucknow",
    "kanpur",
    "varanasi",
    "mathura",
    "agra",
    "uttar pradesh",
    "u.p.",
    "jaipur",
    "udaipur",
    "jodhpur",
    "rajasthan",
    "chennai",
    "coimbatore",
    "madurai",
    "tamil nadu",
    "kochi",
    "cochin",
    "trivandrum",
    "thiruvananthapuram",
    "kerala",
    "kolkata",
    "howrah",
    "west bengal",
    "bhubaneswar",
    "rourkela",
    "cuttack",
    "odisha",
    "patna",
    "bihar",
    "ranchi",
    "jharkhand",
    "raipur",
    "chhattisgarh",
    "guwahati",
    "assam",
    "dehradun",
    "uttarakhand",
    "shimla",
    "himachal",
    "srinagar",
    "jammu",
    "goa",
    "mysore",
    "mangalore",
    "hubli",
    "karnataka",
    "vijayawada",
    "visakhapatnam",
    "vizag",
    "guntur",
    "tirupati",
    "andhra pradesh",
    # additional district towns seen in this corpus and their neighbours
    "junagadh",
    "gondal",
    "mehsana",
    "anand",
    "bhavnagar",
    "jamnagar",
    "bhuj",
    "gandhinagar",
    "vapi",
    "bharuch",
    "amreli",
    "porbandar",
    "morbi",
    "navsari",
    "valsad",
    "palanpur",
    "godhra",
    "surendranagar",
    "nadiad",
    "meerut",
    "aligarh",
    "bareilly",
    "moradabad",
    "gorakhpur",
    "prayagraj",
    "allahabad",
    "jhansi",
    "ujjain",
    "sagar",
    "rewa",
    "satna",
    "amravati",
    "aurangabad",
    "solapur",
    "kolhapur",
    "sangli",
    "latur",
    "jalgaon",
    "akola",
    "nanded",
    "ahmednagar",
    "vellore",
    "salem",
    "erode",
    "trichy",
    "tiruchirappalli",
    "tirunelveli",
    "warangal",
    "nizamabad",
    "karimnagar",
    "khammam",
    "nellore",
    "kurnool",
    "anantapur",
    "rajahmundry",
    "kakinada",
    "belgaum",
    "davangere",
    "shimoga",
    "tumkur",
    "gulbarga",
    "bidar",
    "siliguri",
    "durgapur",
    "asansol",
    "kharagpur",
    "dhanbad",
    "jamshedpur",
    "bokaro",
    "gaya",
    "muzaffarpur",
    "bhagalpur",
    "darbhanga",
    "ambala",
    "panipat",
    "karnal",
    "hisar",
    "rohtak",
    "sonipat",
    "jalandhar",
    "amritsar",
    "patiala",
    "bathinda",
    "mohali",
    "ajmer",
    "kota",
    "bikaner",
    "alwar",
    "bhilwara",
    "sikar",
    "thrissur",
    "kozhikode",
    "kollam",
    "kannur",
    "alappuzha",
    "palakkad",
    "malappuram",
    "kottayam",
    "lahore",
    "karachi",
    "islamabad",
    "rawalpindi",
    "faisalabad",
    "multan",
    "peshawar",
    "quetta",
    "chittagong",
    "sylhet",
    "khulna",
    "rajshahi",
    "mombasa",
    "kisumu",
    "nakuru",
    "sydney",
    "brisbane",
    "perth",
    "adelaide",
    "canberra",
    "abu dhabi",
    "sharjah",
    "ajman",
    "singapore",
]

#: Longest first, so "navi mumbai" wins over "mumbai".
CITY_RE: re.Pattern[str] = re.compile(
    r"\b(?:" + "|".join(re.escape(c) for c in sorted(CITIES, key=len, reverse=True)) + r")\b",
    re.I,
)

#: Two-letter Indian state codes, uppercase only, e.g. "Bhopal, MP, India".
#: Uppercase-only because "Ka" and "Up" are ordinary words.
STATE_ABBR: re.Pattern[str] = re.compile(
    r"(?<![A-Za-z])(?:MP|UP|AP|TS|HP|MH|KA|TN|WB|GJ|RJ|PB|HR|JK|UK|CG|JH|BR|KL|AS|NCR)"
    r"(?![A-Za-z])"
)

#: A location word that is part of an organisation's name is not the
#: candidate's address, so "Bangalore Institute of Technology" keeps its city.
ORG_SUFFIX: re.Pattern[str] = re.compile(
    r"^\s*[,.]?\s*(?:pvt|private|ltd|limited|inc|llp|llc|corp|technolog|institute|"
    r"university|school|college|board|academy|solutions|systems|services|labs|"
    r"software|consult|infotech|industries|group|bank)",
    re.I,
)

# ---------------------------------------------------------------------------
# 4. Contact scaffolding
# ---------------------------------------------------------------------------

#: Anything suggesting the line is part of a contact block, which lets the
#: address rules run on it even outside the header region.
CONTACT_HINT: re.Pattern[str] = re.compile(
    r"@|\bphone\b|\bmobile\b|\bcontact\b|\btel\b|\bemail\b|\be-?mail\b|\baddress\b|"
    r"linkedin|github|portfolio|leetcode|\+\d|\bcell\b",
    re.I,
)

#: The name of a site, left behind as the visible text of a hyperlink whose URL
#: has been stripped. Nothing else is called this, so it needs no separator.
CONTACT_PLATFORM: re.Pattern[str] = re.compile(
    r"^\W*(?:linked\s?in|git\s?hub|gitlab|bitbucket|portfolio|leetcode|hackerrank|"
    r"hackerearth|geeks\s?for\s?geeks|codechef|codeforces?|kaggle|dagshub|behance|"
    r"dribbble|stack\s?overflow|hashnode|peerlist|topmate|naukri|credly|twitter)"
    r"\W*$",
    re.I,
)

#: The field label a stripped contact line leaves standing ("Email:", "Phone
#: number -", "City:"). These words also occur in ordinary prose -- "MOBILE
#: AGENT APPLICATION", "Social Exposure" -- so callers only accept them with
#: their separator attached.
CONTACT_LABEL: re.Pattern[str] = re.compile(
    r"^\W*(?:e-?\s?mail|g-?\s?mail|mail|phone|mobile|tel|telephone|cell|contact|"
    r"whatsapp|telegram|skype|primary|secondary|"
    r"address|location|city|home|website|site|web|blog|resume|cv|profile|link|links|"
    r"social|medium|id|no|number|details|handle|account)\W*$",
    re.I,
)

#: The heading of a contact block ("PHONE", "E-MAIL"). Unlike the rest of
#: CONTACT_LABEL these are never body prose, so they count on their own -- and
#: unlike "Profile" or "Summary" they are not section headings either.
CONTACT_HEAD: re.Pattern[str] = re.compile(
    r"^\W*(?:e-?\s?mail|g-?\s?mail|phone|mobile|tel|telephone|cell|contact|"
    r"whatsapp|telegram|skype|primary|secondary)\W*$",
    re.I,
)

#: Words a link label may be padded with ("Visit My Website", "View Profile").
#: Too generic to act on alone; safe inside the bounds of a single hyperlink.
LINK_FILLER: re.Pattern[str] = re.compile(
    r"^(?:view|visit|click|check|here|my|me|the|it|out|page|repo|repository|"
    # A lone character inside a link is an icon glyph or a split-off letter.
    r"projects?|profiles?|[A-Za-z0-9])$",
    re.I,
)

# ---------------------------------------------------------------------------
# 5. Document structure
# ---------------------------------------------------------------------------

#: A job title is not personal data, so a line still holding one is content and
#: is never swept bare.
TITLE_WORD: re.Pattern[str] = re.compile(
    r"^(?:sr|jr|senior|junior|lead|principal|staff|chief|head|full[\s-]?stack|"
    r"fullstack|back-?end|front-?end|software|web|mobile|cloud|data|ai|ml|devops|"
    r"qa|sde|engineer|engineering|developer|programmer|analyst|scientist|"
    r"architect|consultant|manager|designer|administrator|specialist|intern|"
    r"graduate|student|years?|yrs?|experience|open|to|remote|immediate|joiner)$",
    re.I,
)

#: The first section heading ends the contact block. Without this the header
#: rules, which are allowed to take a whole line, reach into the education
#: entries of a short CV -- or of one whose contact block has already been cut.
SECTION_HEAD: re.Pattern[str] = re.compile(
    r"^\W*(?:career\s+)?(?:summary|profile|objective|about(?:\s+me)?|education|"
    r"academics?|qualifications?|experience|work\s+experience|professional\s+"
    r"(?:summary|experience)|employment|skills?|technical\s+skills?|core\s+"
    r"(?:skills?|competenc\w+|impact)|projects?|certifications?|achievements?|"
    r"awards?|publications?|languages|interests|hobbies|declaration)\W*$",
    re.I,
)

# ---------------------------------------------------------------------------
# 6. Predicates
# ---------------------------------------------------------------------------


def phone_spans(text: str) -> list[tuple[int, int]]:
    """Digit runs that look like a phone number, not a year range.

    A phone number is 10 to 15 digits. Anything in that range made only of
    digits, spaces, dashes and dots that contains two or more four-digit years
    is a date range ("2018 - 2022 2023"), not a number.
    """
    out: list[tuple[int, int]] = []
    for match in PHONE_CANDIDATE.finditer(text):
        candidate: str = match.group(0)
        digits: int = sum(ch.isdigit() for ch in candidate)
        if not 10 <= digits <= 15:
            continue
        if (
            re.fullmatch(r"[\d\s\-.]+", candidate)
            and re.search(r"\b(19|20)\d{2}\b", candidate)
            and digits <= 12
            and len(re.findall(r"\b(19|20)\d{2}\b", candidate)) >= 2
        ):
            continue
        out.append((match.start(), match.end()))
    return out


def city_spans(line: str) -> list[tuple[int, int]]:
    """Places in `line` that are the candidate's own, not an employer's.

    State codes are only considered on a line with a comma, since "MP" and "AS"
    are otherwise far too easy to hit inside ordinary text.
    """
    out: list[tuple[int, int]] = []
    for match in CITY_RE.finditer(line):
        if ORG_SUFFIX.match(line[match.end() : match.end() + 16]):
            continue
        out.append((match.start(), match.end()))
    if "," in line:
        out += [(m.start(), m.end()) for m in STATE_ABBR.finditer(line)]
    return out


def link_label_only(anchor: str) -> bool:
    """True if the visible text of a hyperlink is nothing but a label.

    "GitHub", "View Profile", "Visit My Website" -- text that only exists to
    point at the now-dead URL. "View Certificate" or a project name is content
    and is left alone.
    """
    words: list[str] = [w for w in re.split(r"[^A-Za-z0-9]+", anchor) if w]
    return bool(words) and all(
        CONTACT_PLATFORM.match(w) or CONTACT_LABEL.match(w) or LINK_FILLER.match(w)
        for w in words
    )


def label_line(line: str) -> bool:
    """True if a line is nothing but contact labels, glyphs and separators.

    "LinkedIn |", "| GitHub:", or a row left holding only icon glyphs: a
    contact block whose addresses were only ever in the link annotations, so
    stripping the text left the labels with nothing to redact against.

    A bare generic label is not enough -- "Profile" and "CONTACT" are also
    section headings -- but a platform name or a contact-block heading is.
    """
    tokens: list[str] = line.split()
    if not tokens:
        return False

    named: bool = False
    for token in tokens:
        # A lone character is an icon glyph, not a word, unless it is a digit.
        if sum(c.isalnum() for c in token) < 2 and not any(c.isdigit() for c in token):
            continue
        # "E-mail" and "G-Mail" are spelled as labels rather than as prose, so
        # they count without a trailing separator.
        if (
            CONTACT_PLATFORM.match(token)
            or CONTACT_HEAD.match(token)
            or (CONTACT_LABEL.match(token) and not (token[-1].isalnum() and token.isalnum()))
        ):
            named = True
            continue
        return False

    # Nothing but glyphs: debris, unless there are enough of them to be a
    # letter-spaced title ("S E N I O R  E N G I N E E R").
    return named or len(tokens) <= 3
