# CV Redactor

Removes personal data from candidate CVs so they can be shared, reviewed or
scored without identifying the person.

Reads a folder of CVs, writes anonymised copies to another folder. Originals are
never modified. Plain Python — regex rules, PyMuPDF, python-docx and a local OCR
model. **No AI service, no API key, no network calls at runtime.**

---

## Running it

### 1. Install (once)

Needs [`uv`](https://docs.astral.sh/uv/) and Python 3.12+. Everything installs
into `resume_scrubber/.venv`; nothing touches system or user site-packages.

```bash
cd cv-redactor
uv sync --project resume_scrubber
```

### 2. Put the CVs in place

```bash
mkdir -p original_cv
cp /wherever/*.pdf /wherever/*.docx original_cv/
```

### 3. Tell it the surnames

Everything else is automatic, but **a surname cannot be guessed** — nothing in
the word "Sharma" says it is a name rather than a place. Print the headers of
any CV that has no entry yet:

```bash
uv run --project resume_scrubber python -m resume_scrubber.scan
```

Add one line each to `resume_scrubber/names.py`:

```python
SURNAMES["Priya_Sharma_CV.pdf"] = ["Sharma"]
OUT_NAME["Priya_Sharma_CV.pdf"] = "Priya_Data_Engineer.pdf"
```

Skipping this is allowed — the pattern rules still run — but the run ends with a
warning naming every file whose surname is probably still in the document. See
[Adding new CVs](#adding-new-cvs) for the details.

### 4. Redact

```bash
uv run --project resume_scrubber python -m resume_scrubber.redact
```

### 5. Verify

```bash
uv run --project resume_scrubber python -m resume_scrubber.verify
```

Exits `0` on a clean audit, `1` if anything leaked. **Then open two or three
output pages and look at them** — see [Verifying](#verifying) for why.

### Web interface

There is also a browser front end -- a FastAPI service and a Streamlit app --
for people who should not have to edit `names.py`:

```bash
uv sync --project resume_scrubber --group frontend
uv run --project resume_scrubber uvicorn frontend.api.main:app    # terminal 1
uv run --project resume_scrubber streamlit run streamlit_app.py   # terminal 2
```

Or `docker compose up --build` for both. See [frontend/README.md](frontend/README.md),
which also covers what can and cannot be hosted on Streamlit Community Cloud.

### All three commands

| Command | What it does |
|---|---|
| `python -m resume_scrubber.scan` | Prints the header of every CV with no `names.py` entry |
| `python -m resume_scrubber.redact` | Writes anonymised copies |
| `python -m resume_scrubber.verify` | Audits the output, exits non-zero on a leak |

Each takes `-i/--input` and `-o/--output`; defaults are `original_cv` and
`redacted_cv`. Run them from the repository root, so `resume_scrubber` is
importable as a package.

```bash
# a different pair of folders
uv run --project resume_scrubber python -m resume_scrubber.redact -i in_dir -o out_dir

# CI: fail the build if a CV was processed without a names.py entry
uv run --project resume_scrubber python -m resume_scrubber.redact --fail-on-unmapped

# see what would be written, without writing it
uv run --project resume_scrubber python -m resume_scrubber.redact --dry-run

# audit, including re-reading any scanned output through OCR (slow)
uv run --project resume_scrubber python -m resume_scrubber.verify --ocr

# audit, writing machine-readable findings for a pipeline to consume
uv run --project resume_scrubber python -m resume_scrubber.verify --json audit.json
```

`uv run --project resume_scrubber python` is just "the interpreter with the
dependencies". Calling it directly is the same thing:

```bash
resume_scrubber/.venv/bin/python -m resume_scrubber.redact
```

### Exit codes

| Code | `redact` | `verify` |
|---|---|---|
| `0` | every file written | no leaks found |
| `1` | at least one file failed, or `--fail-on-unmapped` and an entry is missing | personal data still present |
| `2` | bad arguments (missing input folder, output inside input) | output folder does not exist |

### Re-running

`redact` writes into the output folder rather than clearing it, and each file is
written to a temporary neighbour and renamed on success — an interrupted run
never leaves a half-written file that looks finished. It is always safe to
re-run after editing `names.py`.

**Never point `-i` at a folder of already-redacted output.** The tool is keyed on
source filenames, so a second pass matches nothing in `names.py`, and the
header rules — which are allowed to take a whole line — land on different
content once the contact block has already been cut.

---

## The problem

A CV is a dense block of personal data wrapped around a few paragraphs of
professional information. Sharing one hands over the person's phone number, home
address, date of birth and every social profile they own — none of which is
needed to judge whether they can do the job, all of which invites bias and
creates a data-protection liability.

Doing it by hand across dozens of CVs is slow and unreliable. It is also easy to
do wrong in ways that look fine:

- **Drawing a black box over text does not remove it.** The text is still in the
  PDF and any copy-paste or extraction recovers it. This tool deletes the glyphs
  from the content stream.
- **PDFs keep copies of text where you cannot see it.** One CV here stored the
  candidate's email and GitHub URL in the tagged-structure tree
  (`/ActualText`, `/Alt`) and several kept the full name in bookmark titles. The
  visible page was clean; the file was not.
- **Scanned CVs have no text to delete.** Painting a rectangle over the contact
  block leaves the original pixels underneath, so the page is instead re-rendered
  from a raster that has been blanked.
- **Contact data hides in the file format.** An email split across three runs
  inside a Word hyperlink, a URL hard-wrapped across two lines, a phone number
  whose last four digits sit in their own text element.
- **Removing the data is not the same as removing the trace.** Delete the URL
  behind a link and the word "LinkedIn" is still sitting there, underlined, next
  to a row of `|` separators and an icon. It still says where to find the person.

---

## What gets removed

| Category | Detail |
|---|---|
| Last names | Every occurrence, every page. The first name is kept. |
| Phone numbers | Any 10–15 digit run in any format: `+91 8802627170`, `+254 795 150 677`, `(+91) 86977-35353`, `+971 502458960/+91 9892956080`, bare `9155030932`. |
| Email addresses | Including ones split across runs, kerned into separate text elements, or buried in a hyperlink. |
| Links | LinkedIn, GitHub, LeetCode, GeeksforGeeks, StackOverflow, portfolios, Netlify/Vercel/Render sites — visible URLs, URLs wrapped across two lines, and every PDF link annotation. |
| Contact scaffolding | The residue a stripped contact block leaves: field labels (`Email:`, `Phone number -`), dead link text (`LinkedIn`, `Portfolio`), icon glyphs, orphaned `\|` and `•` separators, and the underline the link was drawn with. |
| Home address | Street lines, PIN codes, uppercase state codes, and the city/state/country on the contact line. |
| Personal details | Date of birth, marital status, gender and age, nationality, passport, father's name. |
| Photographs | Headshots are deleted from the file. The web UI previews every image and lets you tick which to remove; the command line takes image ids from `PHOTOS` in `names.py`. |
| Hidden copies | PDF metadata, XMP, bookmarks, tagged-structure tree, embedded files; DOCX core properties and hyperlink targets. |

## What is deliberately kept

- **Employer and university names, including their locations** — "Infogain India
  Pvt. Ltd", "Savitribai Phule Pune University". A company's city identifies a
  candidate far less than their home address, and stripping it guts the work
  history. A city inside a *contact* line is still removed.
- Job titles, dates, skills, projects, achievements, certifications.
- Company logos and icons — only faces are removed.
- The candidate's first name, in the document and in the output filename
  (`Aman_Chaudhary_Resume.pdf` → `Aman_Backend_Engineer.pdf`).

---

## Layout

```
.
├── README.md
├── original_cv/               the source CVs, never modified
├── redacted_cv/               output
├── frontend/                  web interface (see frontend/README.md)
│   ├── api/                   FastAPI service
│   ├── ui/                    Streamlit app
│   └── tests/
├── streamlit_app.py           UI entry point, and what Community Cloud expects
├── ruff.toml  pytest.ini      repo-wide lint and test configuration
├── Dockerfile                 one image, two entry points
├── docker-compose.yml         API and UI together
└── resume_scrubber/           the tool, fully self-contained
    ├── pyproject.toml         dependencies, ruff and pytest config
    ├── uv.lock                resolved versions
    ├── .venv/                 every dependency lives here
    │
    ├── redact.py              CLI: walk a folder, pick a path per file
    ├── verify.py              CLI: audit the output
    ├── scan.py                CLI: print headers of CVs not yet in names.py
    │
    ├── rules.py               which characters go — pure, no file formats
    ├── patterns.py            the regexes and the city gazetteer
    ├── config.py              every tunable threshold, with its rationale
    ├── names.py               the manual per-CV table
    │
    ├── pdf_redact.py          text PDFs
    ├── docx_redact.py         Word documents
    ├── ocr_redact.py          scanned, image-only PDFs
    └── tests/                 pytest suite for the rules
```

The layering matters: `rules.py` takes a string and returns character offsets,
knowing nothing about any file format. That is what lets the PDF, DOCX and OCR
paths make *identical* decisions, and what makes the logic testable without a
corpus of real CVs.

---

## Adding new CVs

1. Drop the files into `original_cv/`.

2. Print the headers of files that have no entry yet:

   ```bash
   uv run --project resume_scrubber python -m resume_scrubber.scan
   ```

3. Add to `resume_scrubber/names.py`:

   ```python
   SURNAMES["Priya_Sharma_CV.pdf"] = ["Sharma"]
   OUT_NAME["Priya_Sharma_CV.pdf"] = "Priya_Data_Engineer.pdf"
   ```

   List **every** family name, including middle names ("Mithilesh Chandrabhan
   Patil" needs both) and any surname variant that shows up only in an email or
   a profile slug — one candidate's LinkedIn is `prity-rawat`, so `Rawat` is
   listed too. The source filename usually leaks the surname as well, which is
   what `OUT_NAME` is for.

4. Re-run `redact`. Any file with no entry is still processed, but the run ends
   with a warning naming it.

### Optional entries in `names.py`

- `PHOTOS = {"CV.pdf": [6]}` — image xrefs to delete. Find them by listing
  `page.get_images(full=True)` and rendering the candidates; add only real
  faces, not logos.
- `REINSERT = {"CV.pdf": "Rafi"}` — for when the first and last name are a
  single glued word (`RaﬁAhmed`, with an `fi` ligature). The whole word is
  deleted and the first name is drawn back in at the same spot, matching the
  original font size, weight and colour.
- A `SURNAMES` entry starting with `re:` is spliced in as a raw regex, for cases
  like a bare middle initial that must only match after the first name:
  `r"re:(?<=SATHISHKUMAR\s)S(?![A-Za-z])"`.

---

## How it works

### Deciding (`rules.py`)

Every path funnels into `redact_spans(line, ...) -> [(start, end), ...]`, which
runs in two stages.

**Stage one — the patterns.** Email, URL, phone, date of birth, declared
personal fields, postal address, and this CV's surnames.

**Stage two — the residue.** Deleting the email and the phone leaves the
contact block's scaffolding standing. Four steps clear it:

1. **Fragments.** What is left of a name inside a handle is glued to the part
   that went, not separated by a space — `vasu-upadhyay` minus the surname
   leaves `vasu-`, still a profile slug.
2. **Labels.** `LinkedIn` and `Portfolio` name a site and nothing else, so they
   go bare. Generic words (`mobile`, `social`) also occur in prose, so they only
   count punctuated as a field label — this is why "MOBILE AGENT APPLICATION"
   and "Social Exposure" survive in a publication list.
3. **Separators.** A `|` only reads as one while it still sits between two
   words. At the end of a stripped row it is debris.
4. **The remainder.** A contact row down to three words or fewer is a home town
   or a dangling handle — unless one of them is a job-title word, which belongs
   to the summary line rather than the contact block.

Steps 3 and 4 feed each other and repeat until the line stops changing.

The aggressive rules are confined to the contact block, which ends at the first
section heading (`SECTION_HEAD`) rather than at a fixed line count — a CV whose
contact block runs long keeps its rules, and a short CV's education entries do
not get treated as an address. Two widths are used: a narrow one for the loose
rules (a bare city name), a wider one for the precise rules (a six-digit postal
code, a row of dead labels).

### Text PDFs (`pdf_redact.py`)

1. Delete every link annotation, first noting where each was. If the xref is
   damaged and `delete_link` silently fails, the page's `/Annots` array is
   cleared instead.
2. Any link whose visible text was only ever a label — `GitHub`, `View Profile`
   — has that text deleted too, fed back through the rules so the separators
   around it go as well.
3. Group words into lines, join them, match, then delete each **word** whose
   characters overlap a match. Word-level rather than line-level, so
   `AAKASH AGGARWAL` loses only the surname.
4. Second pass over each block with the line breaks closed up, catching emails,
   URLs and phone numbers hard-wrapped across two lines.
5. `apply_redactions` with images and line art protected, so icons, rules and
   coloured header bands survive.
6. Sweep the thin strip below each removed word with `REMOVE_IF_COVERED`, which
   takes a hyperlink's underline but cannot take a full-width section rule.
7. Restore a first name if `REINSERT` applies — **after** the redaction, or the
   same rectangle erases it again.
8. Delete headshots in a separate pass, so image removal cannot catch an icon
   that happens to touch a text redaction.
9. Clear metadata, XMP, outline, structure tree and embedded files, then save
   with `garbage=4` so the orphaned objects are actually dropped.

### DOCX (`docx_redact.py`)

Walks every `w:p` in every part — body, headers, footers, tables, text boxes —
and edits the `w:t` nodes directly. `paragraph.runs` skips runs nested inside
`w:hyperlink`, which is exactly where one email was hiding. Hyperlink targets
are blanked and core properties cleared.

### Scanned PDFs (`ocr_redact.py`)

1. Render each page at 200 DPI.
2. OCR it with RapidOCR — one box and one string per line.
3. Run the same rules over each line.
4. Blank the matched regions **in the pixels**, then rebuild the page from the
   redacted raster. Nothing is painted over recoverable content.

OCR returns a box per line, not per word, so character positions are
proportional estimates. Two guards make that safe: a line matching a contact
keyword is blanked whole — `Linkedin:niraj-kumar-879bb8250` has no `.com`, so
only the surname matched and the slug survived on either side — and every span
gets 6% + 10px of padding with snap-to-edge. Without the padding a one-pixel
sliver of a "K" survived and read back as `Niraj I`.

---

## Verifying

`verify` runs five checks and exits non-zero if the first one fails:

1. **Leaks** — emails, phones, links, surnames, dates of birth, link annotations
   and metadata, in the extracted text *and* in the raw bytes and decompressed
   streams, so text hiding outside the page is caught. Font-licence boilerplate
   (`microsoft.com/pki`, `sil.org`, `vvv@vsu.ru`) is filtered out.
2. **Content loss** — source lines that vanished without carrying any contact
   data. A handful is normal and is listed for review.
3. **Photos** — page images big enough to be a face, excluding full-page scans.
4. **First names** — flags any output where the first name went missing.
5. **Scans** — with `--ocr`, re-renders scanned outputs at 260 DPI, reads them
   back and re-runs the rules.

**Look at two or three rendered pages as well.** Three real defects passed the
text audit and were caught only by eye: a redaction rectangle overlapping the
line above ate half a job title, the first-name restore fired on an email that
happened to start with the same letters, and a stripped contact row left a blue
underline floating under nothing.

---

## Developing

```bash
uv run --project resume_scrubber python -m pytest resume_scrubber/tests   # tests
uv run --project resume_scrubber python -m ruff check resume_scrubber     # lint
uv run --project resume_scrubber python -m ruff format resume_scrubber    # format
```

The test suite covers `rules.py` and `patterns.py` — the parts that decide what
goes. Every case is a line that actually appeared in a CV, and the ones marked
as regressions are lines an earlier version got wrong, so removing a guard fails
a test rather than quietly destroying a corpus.

`config.py` holds every threshold with a comment on which way it fails. Change
behaviour there rather than inline.

---

## Known limits

- **Surnames are a manual entry.** Everything else is automatic.
- The city list is a fixed gazetteer, weighted to India plus the other countries
  in this batch. An unlisted town survives unless it sits next to a PIN code or
  a street word, or the residue sweep takes the whole row — check the contact
  block of any CV from a new region.
- The address rules need a digit on the line and a line of 80 characters or less
  before they will wipe a whole line. This is deliberate: an earlier version
  keyed on generic words like `building`, `road` and `cross` and destroyed
  sentences such as "cross-functional teams" and "wealth-building decisions".
- A surname that is also an address word ("Deepak Nagar") is handled by that
  same digit requirement.
- Names are matched with word boundaries after NFKD normalisation, so ligatures
  like `Raﬁ` match, but a surname glued into a longer token still needs a
  `REINSERT` entry.
- Orphaned fragments — one candidate's phone left a stray `0310` in a separate
  text element — need an explicit `re:` rule. Worth a glance at each new
  contact block.
- The section-heading boundary is text-order based, so a **two-column layout**
  whose sidebar is emitted after the main column's first heading falls outside
  the contact block. Platform names can survive there (no usernames, no URLs).
- Decorative LinkedIn/GitHub **icon images** are left in place; they carry no
  personal data.
