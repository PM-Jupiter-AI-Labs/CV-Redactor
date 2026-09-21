# Deploying to Streamlit Community Cloud

Free, no card, no Docker. Community Cloud watches your GitHub repository and
redeploys when you push.

```
  git push main
        │
        ├──► GitHub Actions: ruff, pytest, pyright, requirements check
        │
        └──► Streamlit Community Cloud: pip install, restart
                    │
                    ▼
        https://<something>.streamlit.app
```

The two are independent — Community Cloud does **not** wait for CI. CI is there
to tell you the push was broken, not to gate the deploy.

---

## Before you start

**A Community Cloud app is public.** Anyone with the URL can upload documents,
and they are processed on Streamlit's infrastructure.

The app stores nothing — uploads live in memory and in a temporary directory for
one request, then go — but "not stored" is not "not disclosed". Sending real
candidate CVs to a free public host is the thing this tool exists to prevent.

Use it with sample or synthetic CVs. For real candidate data, run it locally or
on infrastructure you control: `docker compose up` does the same job, offline.

Community Cloud offers no password protection on the free tier. If you need the
app private, that is a reason to use a different host, not a reason to hope
nobody finds the URL.

---

## Step 1 — Push the repository to GitHub

It is already there. Community Cloud needs read access to it, which it asks for
when you sign in.

## Step 2 — Create the app

1. Go to <https://share.streamlit.io> and sign in **with GitHub**.
2. Authorise Streamlit to read your repositories. For a private repository you
   have to grant access to that repository specifically.
3. **Create app** → **Deploy a public app from GitHub**.
4. Fill in:
   - **Repository** — `PM-Jupiter-AI-Labs/CV-Redactor`
   - **Branch** — `main`
   - **Main file path** — `streamlit_app.py`
   - **App URL** — whatever subdomain you want.
5. **Deploy.**

The build takes a couple of minutes — 52 packages, no compiled monsters. Watch
the log pane on the right; it streams pip's output and any failure shows there.

## Step 3 — Settings (optional)

**Advanced settings** during creation, or **⋮ → Settings** afterwards:

- **Python version** — 3.12. The code uses 3.12 syntax and will not run on 3.9.
- **Secrets** — TOML, and also set as environment variables, which is how this
  app reads them:

  ```toml
  CV_REDACTOR_ENABLE_OCR = "0"
  CV_REDACTOR_MAX_FILES = "25"
  CV_REDACTOR_MAX_UPLOAD_MB = "10"
  ```

  `CV_REDACTOR_ENABLE_OCR = "0"` is worth setting: this deployment has no OCR
  (see below), and with it set the app says so in the sidebar rather than
  letting someone upload a scan and hit an error. Lower the other two on free
  hardware — a fifty-CV batch will run out of memory.

---

## How it runs there

Community Cloud gives you **one process**, so there is no FastAPI service — the
UI calls the redactor directly, in the same process.

That is a configuration choice, not a separate build. `frontend/ui/client.py`
picks an implementation:

| `CV_REDACTOR_API_URL` | What happens |
|---|---|
| unset | `LocalClient` — the redactor runs in this process |
| set | `RedactorClient` — HTTP to a FastAPI service |

Community Cloud sets nothing, so it gets the local path. `docker compose` sets
it, so it keeps the HTTP path. The UI is written against whichever it is handed
and has no branch for it.

The FastAPI service is still in the repository, still tested, still what
`docker compose up` runs. It simply is not deployed here, because there is
nowhere to put it.

| File | Why it exists |
|---|---|
| `streamlit_app.py` | Entry point. Community Cloud looks for this name. |
| `requirements.txt` | What Community Cloud installs. Generated from `uv.lock`; CI fails if they drift. |
| `.streamlit/config.toml` | Upload cap, matching the app's own limit. |

---

## No OCR here, on purpose

`requirements.txt` is generated with `--no-default-groups`, which leaves out the
`ocr` dependency group. That drops `rapidocr-onnxruntime`, and with it
`onnxruntime` and `opencv-python` — 176 packages become 52, and the build goes
from many minutes to a couple.

It also removes a whole class of failure. `opencv-python` links against libGL,
which is not in Community Cloud's image, so it needs an apt package to work at
all. No opencv, no `packages.txt`, nothing to get wrong.

The cost is that a scanned PDF cannot be read here. It fails with a message
saying so, rather than being passed through unredacted — which is the right way
round: silently returning an unredacted scan is the worst thing this tool could
do.

The command line and the Docker image still have the full OCR path; `ocr` is a
default group, so only a deployment that explicitly opts out goes without it.

To put OCR back on Community Cloud you would need `rapidocr-onnxruntime` in
`requirements.txt` and a `packages.txt` containing `libgl1` — and
**`packages.txt` must contain package names only, one per line, with no
comments.** Streamlit pipes the whole file to `apt-get install`, so a `#`
comment becomes a package name and the build fails.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'frontend'`**
The main file path is wrong. It must be `streamlit_app.py` at the repository
root, not `frontend/ui/app.py`. `streamlit run` puts the script's own directory
on `sys.path`, so only the root launcher makes the package importable.

**`E: Unable to locate package <some word from a comment>`**
A `packages.txt` with comments in it. Streamlit passes every line to
`apt-get install`, so comments become package names. Package names only, one
per line. This deployment needs no `packages.txt` at all.

**The build hangs or is killed while installing.**
Resource limits. Check nothing has re-added the OCR dependencies.

**`SyntaxError` on `X | None` or similar.**
The app is on an old Python. Set Python 3.12 in the app's settings; it cannot
be changed after creation on some plans, in which case delete and recreate.

**The app loads, then dies when you click Redact.**
Out of memory. Lower `CV_REDACTOR_MAX_FILES` and `CV_REDACTOR_MAX_UPLOAD_MB` in
the secrets, and redact in smaller batches.

**It says "cannot reach the API".**
`CV_REDACTOR_API_URL` is set in the secrets and points at something that is not
there. Remove it: with it unset the app runs the redactor itself.

**Changes are not appearing.**
Community Cloud redeploys on push to the tracked branch. Check you pushed to
`main`, then **⋮ → Reboot app**.

---

## If you later want the API too

Community Cloud cannot host it — one process, one port. Options, in order of
effort:

1. **Hugging Face PRO** — `deploy/huggingface/` is complete and tested; the
   workflow is there, set to manual-run. Subscribe, add `HF_TOKEN` and
   `HF_SPACE`, run the workflow.
2. **Cloud Run, Render, Fly** — Docker-native, the root `Dockerfile` works
   as-is, free tiers exist. The UI then points at it via `CV_REDACTOR_API_URL`.

In either case, put authentication in front of the API first. It has none.
