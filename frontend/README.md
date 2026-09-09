# Web frontend

A FastAPI service and a Streamlit app for the CV redactor. Either can run
without the other: the API is usable on its own, and the UI is a pure HTTP
client that never imports the redactor.

```
frontend/
├── api/                  FastAPI service
│   ├── main.py           routing, limits, CORS — the HTTP surface only
│   ├── service.py        the work: bytes in, bytes out, nothing kept
│   ├── schemas.py        request and response contract
│   └── settings.py       environment-driven configuration
├── ui/                   Streamlit app
│   ├── app.py            the three steps: upload, review, redact
│   └── client.py         HTTP client for the API
└── tests/                end-to-end tests against generated CVs
```

---

## Running it locally

> **Keep `--project resume_scrubber` on every `uv` command.** The dependencies
> live in that project; `uv run` from the repository root resolves against a
> different environment.
>
> Either UI entry point works -- `streamlit run streamlit_app.py` or
> `streamlit run frontend/ui/app.py`. They are not equivalent by accident:
> `streamlit run` puts the *script's own directory* on `sys.path` rather than
> the directory you ran it from, so `app.py` adds the repository root itself.
> The root launcher is still the one to deploy, because it is the filename
> Streamlit Community Cloud looks for.

Install the frontend dependencies (they are a separate group, so the command
line stays lean):

```bash
uv sync --project resume_scrubber --group frontend
```

Then two terminals:

```bash
# 1. the API
uv run --project resume_scrubber uvicorn frontend.api.main:app --reload

# 2. the UI
uv run --project resume_scrubber streamlit run streamlit_app.py
```

UI at <http://localhost:8501>, interactive API docs at
<http://localhost:8000/docs>.

Or both in containers:

```bash
docker compose up --build
```

---

## The workflow

The UI has three steps, and the middle one is the point.

1. **Upload** — PDF or DOCX, one or many.
2. **Review** — the app shows each CV's header next to a box for the surnames.
   **This cannot be automated.** Nothing in the word "Sharma" marks it as a name
   rather than a place, so a person has to read the header and say. Suggestions
   come from the filename only and are a starting point, never an answer.
3. **Redact** — download a zip of the results. It contains `manifest.json`
   describing what happened to each file, so the download is self-describing.

There is an optional fourth step: **audit** the output, which re-reads it
looking for anything that survived, including text hiding outside the page.

A file with no surname listed is still processed — the pattern rules for email,
phone, links, address and date of birth all run — but the UI warns first and the
manifest marks it `unmapped`, because the surname will still be in the document.

---

## API

Four endpoints, all under `/api/v1`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness, version, whether OCR is available |
| `POST` | `/scan` | Read each CV's header so a human can pick the surname |
| `POST` | `/redact` | Redact a batch, returns a zip |
| `POST` | `/verify` | Audit already-redacted files |

`/redact` and `/verify` take the files as multipart plus a `plans` form field —
a JSON array of per-file instructions:

```json
[
  {
    "filename": "Priya_Sharma_CV.pdf",
    "surnames": ["Sharma", "re:(?<=PRIYA\\s)S(?![A-Za-z])"],
    "output_name": "Priya_Backend_Engineer.pdf",
    "photo_xrefs": [12],
    "reinsert_first_name": null
  }
]
```

```bash
curl -X POST http://localhost:8000/api/v1/redact \
  -F "files=@Priya_Sharma_CV.pdf" \
  -F 'plans=[{"filename":"Priya_Sharma_CV.pdf","surnames":["Sharma"]}]' \
  -o redacted.zip
```

### It keeps nothing

The service is stateless. Uploads are written into a temporary directory for the
duration of one request and deleted before it returns; the browser session holds
the bytes between the scan and the redact call, which is why the same files are
posted twice. For a tool whose purpose is to stop personal data spreading, a
server that accumulates candidate CVs would be the wrong shape.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CV_REDACTOR_MAX_UPLOAD_MB` | `25` | Largest single file |
| `CV_REDACTOR_MAX_FILES` | `200` | Largest batch |
| `CV_REDACTOR_CORS_ORIGINS` | `*` | Comma-separated browser origins |
| `CV_REDACTOR_ENABLE_OCR` | `1` | `0` refuses scanned PDFs and skips the models |
| `CV_REDACTOR_API_URL` | `http://127.0.0.1:8000` | Where the **UI** looks for the API |

---

## Hosting: do you need Docker?

**It depends on whether you want the API.** The short version:

| What you want | Docker? | Where |
|---|---|---|
| Streamlit UI only, no API | **No** | Streamlit Community Cloud, directly |
| API + UI, one host | **Yes** | `docker compose up` on Fly.io, Render, Cloud Run, a VM |
| API + UI, split | **Only for the API** | API on Render/Fly, UI on Community Cloud pointing at it |

### Why the API cannot go on Streamlit Community Cloud

Community Cloud runs **one process and exposes one port**, and that port is
Streamlit's. You can start uvicorn in the background inside the same container
and reach it on localhost, but nothing outside can, so you have a UI with a
private API — which is the same as having no API, with extra moving parts.

So: if the API only exists to serve this UI, drop it and let the Streamlit app
call `resume_scrubber` directly. If the API is a deliverable in its own right —
something an ATS or another service will call — it needs a host that runs
long-lived processes, and Docker is the straightforward way to get one.

### The other constraint: size

`rapidocr-onnxruntime` pulls in onnxruntime, which is most of a **474 MB**
environment. That is fine on a container host and uncomfortable on a free tier.
If your CVs are never scans, drop `rapidocr-onnxruntime` and `pillow` from
`resume_scrubber/pyproject.toml` and set `CV_REDACTOR_ENABLE_OCR=0`; nothing
else imports them, and the deployment gets a great deal smaller. Scanned PDFs
are then reported as errors instead of being silently passed through
unredacted, which is the right failure.

### Before you put candidate CVs on a public host

This is worth saying plainly, because it is the same concern the tool exists to
address. Uploading real CVs to a free, public, shared-tenancy host means sending
identifiable personal data to a third party — the thing you are redacting them
to avoid. The API keeps nothing on disk, but it still processes the data in
someone else's memory, in whatever jurisdiction they run in.

For real candidate data, prefer: running it locally, or a container on
infrastructure you control, or a host you already have a data-processing
agreement with. Put authentication in front of it — none of these endpoints
have any. Community Cloud is a good fit for a demo with synthetic CVs, and a
poor one for the real thing.

---

## Tests

```bash
uv run --project resume_scrubber python -m pytest frontend/tests
```

The fixtures build their own PDFs rather than committing samples, so no
candidate data lives in the repository and each test can assert on exactly the
email or phone number it planted. They cover the redaction round trip, the audit
catching an unredacted file, per-file failure isolation, the upload limits, and
that a client-supplied output name cannot escape the working directory.
