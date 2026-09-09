# One image, two entry points. Which one runs is chosen by the command, so the
# same build serves as the API, as the UI, or as both (see docker-compose.yml).
#
#   docker build -t cv-redactor .
#   docker run -p 8000:8000 cv-redactor
#   docker run -p 8501:8501 -e CV_REDACTOR_API_URL=http://host:8000 cv-redactor \
#       streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
FROM python:3.12-slim

# uv installs exactly the locked dependency set the developers use.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies first, in their own layer, so editing the source does not
# reinstall onnxruntime every build.
COPY resume_scrubber/pyproject.toml resume_scrubber/uv.lock ./resume_scrubber/
RUN uv sync --project resume_scrubber --group frontend --no-dev

COPY resume_scrubber/ ./resume_scrubber/
COPY frontend/ ./frontend/
COPY streamlit_app.py README.md ./

# Run as a non-root user: this process opens files handed to it by strangers.
RUN useradd --create-home --uid 10001 redactor && chown -R redactor:redactor /app
USER redactor

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/api/v1/health', timeout=3).status_code == 200 else 1)"

CMD ["uvicorn", "frontend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
