# Image for a Hugging Face Docker Space.
#
# Separate from the repository-root Dockerfile because a Space has constraints
# that a general-purpose image should not inherit:
#
#   * one exposed port, which must be 7860 unless app_port says otherwise
#   * the container runs as UID 1000, and $HOME must be writable
#   * both processes live in this one container (see entrypoint.sh)
#
# The Space's README.md front matter is what points Hugging Face at this file.

FROM python:3.12-slim

# uv installs exactly the locked dependency set the developers use.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Hugging Face runs Spaces as UID 1000. Create that user first so everything
# below is owned by it: a Space whose $HOME is not writable fails at runtime in
# ways that look like application bugs.
RUN useradd --create-home --uid 1000 user

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/home/user \
    # Streamlit writes its config and metrics under $HOME.
    STREAMLIT_HOME=/home/user/.streamlit \
    # RapidOCR unpacks its ONNX models on first use; give it a writable home.
    XDG_CACHE_HOME=/home/user/.cache

WORKDIR /app

# Dependencies first, in their own layer, so editing the source does not
# reinstall onnxruntime on every build.
COPY resume_scrubber/pyproject.toml resume_scrubber/uv.lock ./resume_scrubber/
RUN uv sync --project resume_scrubber --group frontend --no-dev

COPY resume_scrubber/ ./resume_scrubber/
COPY frontend/ ./frontend/
COPY streamlit_app.py ./
COPY deploy/huggingface/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p "${STREAMLIT_HOME}" "${XDG_CACHE_HOME}" \
    && chown -R user:user /app /opt/venv /home/user

USER user

# The port Hugging Face publishes. Must match app_port in the Space README.
ENV PORT=7860
EXPOSE 7860

# Probes the UI, since that is the process that must stay up for the Space to
# be usable; the entrypoint already refuses to start it without a healthy API.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:7860/_stcore/health', timeout=3).status_code == 200 else 1)"

CMD ["/usr/local/bin/entrypoint.sh"]
