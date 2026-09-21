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

The first build takes 5–15 minutes: `requirements.txt` has 176 packages and
onnxruntime is a large one. Watch the log pane on the right — it streams pip's
output, and any failure shows up there.

## Step 3 — Settings (optional)

**Advanced settings** during creation, or **⋮ → Settings** afterwards:

- **Python version** — 3.12. The code uses 3.12 syntax and will not run on 3.9.
- **Secrets** — TOML, and also set as environment variables, which is how this
  app reads them:

  ```toml
  CV_REDACTOR_MAX_FILES = "25"
  CV_REDACTOR_MAX_UPLOAD_MB = "10"
  ```

  Worth lowering both on free hardware. A fifty-CV batch will run out of memory.

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
| `packages.txt` | apt packages. `opencv-python` (via the OCR path) needs libGL, which is not in the base image. |
| `.streamlit/config.toml` | Upload cap, matching the app's own limit. |

---

## Making the build smaller

Most of the install is the scanned-PDF path: `rapidocr-onnxruntime` pulls in
`onnxruntime` and `opencv-python`, several hundred megabytes between them. If
your CVs are never scans:

1. Delete `rapidocr-onnxruntime`, `onnxruntime`, `opencv-python` and `pillow`
   from `requirements.txt`.
2. Delete `packages.txt` — it only exists for opencv.
3. Add `CV_REDACTOR_ENABLE_OCR = "0"` to the app's secrets.

The build gets much faster, and a scanned PDF then fails with a clear message
instead of being passed through unredacted. That is the right failure: silently
returning an unredacted scan is the worst thing this tool could do.

Note that CI's requirements check will then fail, because the file no longer
matches the lockfile. Either drop that step, or move the OCR dependencies into
their own group in `resume_scrubber/pyproject.toml` so the export omits them.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'frontend'`**
The main file path is wrong. It must be `streamlit_app.py` at the repository
root, not `frontend/ui/app.py`. `streamlit run` puts the script's own directory
on `sys.path`, so only the root launcher makes the package importable.

**`ImportError: libGL.so.1: cannot open shared object file`**
`packages.txt` is missing or was not picked up. It must be at the repository
root. Reboot the app from its menu after adding it.

**The build hangs or is killed while installing.**
Resource limits. Trim the OCR dependencies as above.

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
