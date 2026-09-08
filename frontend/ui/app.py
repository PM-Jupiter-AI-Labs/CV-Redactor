"""Streamlit front end for the CV redactor.

    streamlit run frontend/ui/app.py

Three steps, matching the command line and the API:

    1. Upload   the CVs
    2. Review   read each header, confirm the surnames to remove
    3. Redact   download the results, and optionally audit them

Step 2 is the one that cannot be skipped or automated. A surname is just a word;
nothing marks "Sharma" as a name rather than a place, so a person has to look at
the header and say. The app puts the header text next to the input for exactly
that reason, and warns before redacting anything with no surname given.

Uploaded bytes are held in the browser session and sent with each call. The API
keeps nothing, so the same files are posted for the scan and for the redaction.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

import streamlit as st

from frontend.ui.client import ApiError, RedactorClient

PAGE_TITLE: str = "CV Redactor"
SUPPORTED: list[str] = ["pdf", "docx"]


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def _init_state() -> None:
    """Give every key a value up front, so no branch has to guess."""
    defaults: dict[str, Any] = {
        "uploads": [],  # list[(filename, bytes)]
        "documents": [],  # scan results
        "bundle": None,  # RedactionBundle
        "audit": None,  # verify results
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_downstream() -> None:
    """A new upload or a fresh scan invalidates whatever came after it."""
    st.session_state["bundle"] = None
    st.session_state["audit"] = None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def _sidebar() -> RedactorClient:
    """Connection settings, and a live check that the API is actually there."""
    st.sidebar.header("Service")
    # Streamlit types text_input as optional; it only returns None when the
    # widget has been cleared, which the default here prevents.
    base_url: str = (
        st.sidebar.text_input(
            "API URL",
            value=st.session_state.get("api_url", RedactorClient().base_url),
            help="Where the FastAPI service is running.",
        )
        or RedactorClient().base_url
    )
    st.session_state["api_url"] = base_url
    client = RedactorClient(base_url)

    try:
        health = client.health()
        st.sidebar.success(f"Connected · v{health.get('version', '?')}")
        if not health.get("ocr_available", False):
            st.sidebar.warning(
                "OCR is disabled here. Scanned PDFs, which have no text layer, "
                "will be reported as errors rather than redacted."
            )
    except ApiError as exc:
        st.sidebar.error(str(exc))
        st.sidebar.caption("Start it with: `uvicorn frontend.api.main:app`")

    st.sidebar.divider()
    st.sidebar.caption(
        "Files are held in this browser session and sent with each request. "
        "The service stores nothing."
    )
    return client


# ---------------------------------------------------------------------------
# Step 1 - upload
# ---------------------------------------------------------------------------


def _step_upload(client: RedactorClient) -> None:
    st.subheader("1 · Upload")
    files = st.file_uploader(
        "CVs to redact",
        type=SUPPORTED,
        accept_multiple_files=True,
        help="PDF or DOCX. Scanned PDFs are handled through OCR.",
    )

    if files:
        uploads = [(f.name, f.getvalue()) for f in files]
        if uploads != st.session_state["uploads"]:
            st.session_state["uploads"] = uploads
            st.session_state["documents"] = []
            _reset_downstream()

    count: int = len(st.session_state["uploads"])
    if not count:
        st.info("Choose one or more CVs to begin.")
        return

    total_kb: int = sum(len(data) for _, data in st.session_state["uploads"]) // 1024
    st.caption(f"{count} file(s), {total_kb} KB")

    if st.button("Read the headers", type="primary"):
        with st.spinner("Reading..."):
            try:
                st.session_state["documents"] = client.scan(st.session_state["uploads"])
                _reset_downstream()
            except ApiError as exc:
                st.error(str(exc))


# ---------------------------------------------------------------------------
# Step 2 - review
# ---------------------------------------------------------------------------


def _plan_for(document: dict) -> dict:
    """Render one document's row and return the plan the user settled on."""
    filename: str = document["filename"]

    with st.expander(filename, expanded=True):
        if document.get("error"):
            st.error(document["error"])
            return {"filename": filename, "surnames": [], "output_name": filename}

        left, right = st.columns([3, 2])

        with left:
            st.caption("Header, as it appears in the document")
            header: str = "\n".join(document.get("header_lines") or [])
            st.code(header or "(no text found)", language=None)
            if not document.get("has_text_layer", True):
                st.warning(
                    "No text layer: this is a scan. It goes through OCR, which is "
                    "slower and reads the page rather than the file."
                )

        with right:
            surnames_raw: str = st.text_input(
                "Surnames to remove",
                value=", ".join(document.get("suggested_surnames") or []),
                key=f"surnames::{filename}",
                help=(
                    "Comma separated. List every family name, including middle "
                    "names and any variant that only shows up inside a profile "
                    "handle. Prefix a token with 're:' for a raw regex."
                ),
            )
            output_name: str = st.text_input(
                "Output filename",
                value=document.get("suggested_output_name") or filename,
                key=f"output::{filename}",
                help="The source filename usually leaks the surname too.",
            )
            photos_raw: str = st.text_input(
                "Photo image ids (optional)",
                value="",
                key=f"photos::{filename}",
                help=(
                    "Comma-separated PDF image xrefs to delete, for a headshot. "
                    "Leave empty unless you know the ids."
                ),
            )

        surnames: list[str] = [s.strip() for s in surnames_raw.split(",") if s.strip()]
        if not surnames:
            st.warning(
                "No surname given. The pattern rules (email, phone, links, "
                "address, date of birth) still run, but the surname will "
                "remain in the document."
            )

        photos: list[int] = []
        for token in photos_raw.split(","):
            token = token.strip()
            if token.isdigit():
                photos.append(int(token))
            elif token:
                st.error(f"'{token}' is not an image id; ids are whole numbers.")

    return {
        "filename": filename,
        "surnames": surnames,
        "output_name": output_name.strip() or filename,
        "photo_xrefs": photos,
    }


def _step_review(client: RedactorClient) -> list[dict]:
    documents: list[dict] = st.session_state["documents"]
    if not documents:
        return []

    st.subheader("2 · Review")
    st.caption(
        "A surname cannot be detected automatically. Read each header and "
        "confirm what to remove; the suggestions come from the filename only."
    )
    plans: list[dict] = [_plan_for(document) for document in documents]

    missing: int = sum(1 for p in plans if not p["surnames"])
    st.subheader("3 · Redact")
    if missing:
        st.warning(f"{missing} of {len(plans)} file(s) have no surname listed.")

    if st.button("Redact", type="primary"):
        with st.spinner("Redacting... scanned PDFs take a while."):
            try:
                st.session_state["bundle"] = client.redact(st.session_state["uploads"], plans)
                st.session_state["audit"] = None
            except ApiError as exc:
                st.error(str(exc))
    return plans


# ---------------------------------------------------------------------------
# Step 3 - results
# ---------------------------------------------------------------------------


def _step_results(client: RedactorClient, plans: list[dict]) -> None:
    bundle = st.session_state["bundle"]
    if bundle is None:
        return

    manifest: dict = bundle.manifest or {}
    results: list[dict] = manifest.get("results", [])
    failed: int = manifest.get("failed", 0)

    st.divider()
    if failed:
        st.error(f"{failed} file(s) failed. The rest were written.")
    else:
        st.success(f"{len(results)} file(s) redacted.")

    st.dataframe(
        [
            {
                "Source": r["filename"],
                "Output": r["output_name"],
                "Redactions": r["redactions"],
                "OCR": "yes" if r.get("used_ocr") else "",
                "No surname": "yes" if r.get("unmapped") else "",
                "Error": r.get("error") or "",
            }
            for r in results
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "Download all (zip)",
        data=bundle.archive,
        file_name="redacted_cvs.zip",
        mime="application/zip",
        type="primary",
    )

    with (
        st.expander("Individual files"),
        zipfile.ZipFile(io.BytesIO(bundle.archive)) as archive,
    ):
        for name in archive.namelist():
            if name == "manifest.json":
                continue
            st.download_button(
                name,
                data=archive.read(name),
                file_name=name,
                mime="application/octet-stream",
                key=f"dl::{name}",
            )

    st.divider()
    st.subheader("4 · Audit (optional)")
    st.caption(
        "Re-reads the output looking for anything that survived, including text "
        "hiding outside the page. A clean audit is necessary, not sufficient: "
        "open a page or two and look at it."
    )
    if st.button("Audit the output"):
        with st.spinner("Auditing..."), zipfile.ZipFile(io.BytesIO(bundle.archive)) as archive:
            try:
                redacted = [
                    (name, archive.read(name))
                    for name in archive.namelist()
                    if name != "manifest.json"
                ]
                # The audit sees the output filenames, so the surnames have to
                # be re-keyed from the source name onto the name they were
                # written under.
                by_source = {p["filename"]: p for p in plans}
                audit_plans = [
                    {
                        "filename": r["output_name"],
                        "surnames": by_source.get(r["filename"], {}).get("surnames", []),
                    }
                    for r in results
                ]
                st.session_state["audit"] = client.verify(redacted, audit_plans)
            except ApiError as exc:
                st.error(str(exc))

    audit = st.session_state["audit"]
    if audit:
        if audit["passed"]:
            st.success(f"PASS · {audit['checked']} file(s), nothing found.")
        else:
            st.error("Personal data still present:")
            for finding in audit["leaks"]:
                st.write(f"**{finding['filename']}**")
                for item in finding["findings"][:8]:
                    st.write(f"- {item}")
        for note in audit.get("notes", []):
            st.info(note)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon="🗂", layout="wide")
    _init_state()

    st.title(PAGE_TITLE)
    st.caption(
        "Removes names, contact details, addresses and photographs from "
        "candidate CVs, so they can be reviewed without identifying the person."
    )

    client = _sidebar()
    _step_upload(client)
    plans = _step_review(client)
    _step_results(client, plans)


if __name__ == "__main__":
    main()
