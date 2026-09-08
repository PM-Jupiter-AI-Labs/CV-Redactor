"""FastAPI service: the redactor behind an HTTP interface.

    uvicorn frontend.api.main:app

Layered so the work is testable without HTTP: `main` is routing and limits,
`service` does the redacting, `schemas` is the contract, `settings` is the
environment.
"""

from __future__ import annotations

__all__: list[str] = []
