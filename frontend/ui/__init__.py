"""Streamlit client for the redaction API.

    streamlit run frontend/ui/app.py

Talks to the service over HTTP and never imports the redactor, so the two can
be deployed separately.
"""

from __future__ import annotations

__all__: list[str] = []
