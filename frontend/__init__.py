"""Web frontend for the CV redactor.

Two independent pieces, so either can be deployed without the other:

    frontend.api  a FastAPI service that does the work
    frontend.ui   a Streamlit app that talks to it over HTTP

The API holds no state and writes nothing to disk that outlives a request.
Uploaded CVs live in a temporary directory for the duration of one call and are
deleted before it returns; the browser session keeps the bytes between the scan
and the redact step. For a tool whose whole purpose is to stop personal data
spreading, not storing that data server-side is a design constraint, not an
optimisation.
"""

from __future__ import annotations

__all__: list[str] = []
