# Deploying to Hugging Face Spaces

GitHub Actions builds and tests on every push to `main`, then pushes a
Space-shaped copy of the repository to Hugging Face, which builds the Docker
image and runs it. You set this up once; after that, deploying is `git push`.

```
  git push main
        │
        ▼
  GitHub Actions ── CI: ruff, pytest, pyright ──► red? stop here
        │
        ▼ green
  assemble deploy/huggingface/ + source  ──►  push to huggingface.co/spaces/<you>/<space>
        │
        ▼
  Hugging Face builds the Dockerfile and starts the container
        │
        ▼
  https://<you>-<space>.hf.space
```

---

## Before you start: is this the right place for it?

**A Hugging Face Space is public by default and has no authentication.** Anyone
who finds the URL can upload documents to it, and those documents are processed
on Hugging Face's infrastructure.

This app keeps nothing — uploads live in a temporary directory for one request
and are deleted before it returns — but "not stored" is not the same as "not
disclosed". Sending real candidate CVs to a free public host is the exact thing
the tool exists to prevent.

So:

- **Demo with sample or synthetic CVs** → a public Space is a good fit.
- **Real candidate data** → make the Space private (Settings → change visibility;
  viewers must then be signed in and granted access), or don't use a Space at
  all: `docker compose up` on infrastructure you control does the same job.

The rest of this guide works either way.

---

## Step 1 — Create the Space

1. Sign in at <https://huggingface.co>.
2. Go to <https://huggingface.co/new-space>.
3. Fill in:
   - **Owner** — your username, or an organisation.
   - **Space name** — e.g. `cv-redactor`.
   - **License** — your choice.
   - **Space SDK** — **Docker**, then the **Blank** template.
     This matters: the SDK cannot be changed later without recreating the Space.
   - **Hardware** — *CPU basic* (free) is enough. There is no GPU work here.
   - **Visibility** — see the note above.
4. Create it. You now have an empty Space at
   `https://huggingface.co/spaces/<owner>/<name>`.

Leave it empty. The workflow fills it.

---

## Step 2 — Create a Hugging Face access token

1. <https://huggingface.co/settings/tokens> → **Create new token**.
2. Token type **Write**, or a fine-grained token with **Write access to contents
   of the Space** you just created — the narrower one is better.
3. Name it something you will recognise, e.g. `github-actions-cv-redactor`.
4. Copy it now. Hugging Face shows it once.

---

## Step 3 — Tell GitHub about it

In your GitHub repository → **Settings** → **Secrets and variables** →
**Actions**:

| Tab | Name | Value |
|---|---|---|
| **Secrets** → New repository secret | `HF_TOKEN` | the token from step 2 |
| **Variables** → New repository variable | `HF_SPACE` | `<owner>/<name>`, e.g. `mayank/cv-redactor` |

The token is a **secret** (masked in logs, never readable back). The Space name
is a **variable** (visible, and useful in the job summary). Getting these the
wrong way round is the usual cause of a token leaking into a log.

---

## Step 4 — Deploy

Push anything to `main`:

```bash
git push origin main
```

Then watch it:

1. **GitHub → Actions → Deploy to Hugging Face Space.** CI runs first; the
   deploy job only starts if it is green. The job summary prints both URLs when
   it finishes.
2. **Your Space → Logs tab.** Hugging Face now builds the Dockerfile. The first
   build takes roughly 5–10 minutes, most of it installing onnxruntime; later
   builds reuse cached layers and are much faster.
3. When the status turns **Running**, the app is at
   `https://<owner>-<name>.hf.space` (dots and slashes become dashes, all
   lowercase).

To redeploy without a commit: **Actions → Deploy to Hugging Face Space → Run
workflow**.

---

## How it fits together

A Space is a git repository that must be laid out the way Hugging Face expects:
a `Dockerfile` at its root, and a `README.md` whose YAML front matter *is* the
configuration. This repository is not laid out that way and should not be, so
the workflow assembles a Space tree instead of pushing the repository as-is.

| File | Role |
|---|---|
| `deploy/huggingface/README.md` | Becomes the Space's `README.md`. Its front matter (`sdk: docker`, `app_port: 7860`) is the configuration. |
| `deploy/huggingface/Dockerfile` | Becomes the Space's `Dockerfile`. Runs as UID 1000 and listens on 7860, both of which a Space requires. |
| `deploy/huggingface/entrypoint.sh` | Starts the API on loopback, waits for it to be healthy, then starts the UI on the public port. |
| `.github/workflows/ci.yml` | Lint, format, tests, types. |
| `.github/workflows/deploy-huggingface.yml` | Assembles the tree and pushes it. |

**Only the UI is reachable.** A Space exposes one port; the API listens on
`127.0.0.1` where the UI can reach it and nothing outside the container can.
That is deliberate — the API has no authentication, so exposing it publicly
would be an open document-processing service running on your account.

The workflow deliberately does **not** copy `original_cv/`, `redacted_cv/`,
`issues/`, or the test suites, and it fails the build if any `.pdf` or `.docx`
ends up in the assembled tree. A Space repository is public by default; that
check is the one that actually matters.

---

## If you want a public API as well

You need two Spaces, because one Space exposes one port.

1. Create a second Space, `cv-redactor-api`.
2. Give it a Dockerfile whose `CMD` is the API on 7860:
   `uvicorn frontend.api.main:app --host 0.0.0.0 --port 7860`.
3. In the **UI** Space: Settings → Variables and secrets → add
   `CV_REDACTOR_API_URL = https://<owner>-cv-redactor-api.hf.space`.
4. In the **API** Space: add
   `CV_REDACTOR_CORS_ORIGINS = https://<owner>-cv-redactor.hf.space`.

Do this only if something other than this UI needs to call the API, and **put
authentication in front of it first** — there is none today.

---

## Space settings worth knowing

Set these under **Settings → Variables and secrets** on the Space; they are read
as environment variables.

| Variable | Default | Effect |
|---|---|---|
| `CV_REDACTOR_MAX_UPLOAD_MB` | `25` | Largest single file. Also caps Streamlit's uploader. |
| `CV_REDACTOR_MAX_FILES` | `200` | Largest batch. Lower it on free hardware. |
| `CV_REDACTOR_ENABLE_OCR` | `1` | `0` refuses scanned PDFs instead of OCR-ing them. |

**Sleeping.** Free Spaces pause after ~48 hours idle and cold-start on the next
visit, which takes a minute or so. Paid hardware can be set to stay awake.

**Size.** The image is around 1 GB, most of it onnxruntime for the scanned-PDF
path. If your CVs are never scans, drop `rapidocr-onnxruntime` and `pillow` from
`resume_scrubber/pyproject.toml` and set `CV_REDACTOR_ENABLE_OCR=0` — the build
gets much smaller and much faster, and scanned PDFs fail loudly instead of
passing through unredacted.

---

## Troubleshooting

**The deploy job fails immediately with "secret HF_TOKEN is not set".**
Step 3 was missed, or the secret is on the environment/organisation rather than
the repository. Repository-level is what this workflow reads.

**`git push` to the Space returns 401 or 403.**
The token lacks write access, or `HF_SPACE` does not match the real
`owner/name`. Check the Space URL; the owner may be an organisation rather than
you.

**The Space says "Configuration error: no `app_port`".**
The README front matter did not arrive. Confirm the Space's `README.md` starts
with `---` and contains `sdk: docker`, and that the deploy job's assemble step
ran.

**The build succeeds but the Space is stuck on "Starting".**
Open the Logs tab. `[entrypoint] the API exited during startup` means uvicorn
failed — the traceback is just above it. If the log stops after
`[entrypoint] starting UI`, Streamlit is up but not answering on 7860; check
that `app_port` in the README still says `7860`.

**Uploads fail in the browser with an XSRF or CORS error.**
Streamlit sits behind the Space's proxy. Add
`--server.enableXsrfProtection=false` to the `streamlit run` line in
`entrypoint.sh`. It weakens a real protection, so try everything else first.

**The UI loads but says it cannot reach the API.**
The API died after startup. Logs tab; look for the Python traceback. Out-of-
memory during OCR on free hardware is the usual cause — set
`CV_REDACTOR_ENABLE_OCR=0` or move to larger hardware.
