"""Streamlit front end for the CV redactor.

Either of these works:

    streamlit run streamlit_app.py        # the repository-root launcher
    streamlit run frontend/ui/app.py      # this file, directly

The launcher is what Streamlit Community Cloud looks for by default; the
sys.path note below is what makes the second form work too.

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
import sys
import zipfile
from pathlib import Path
from typing import Any

import streamlit as st

# `streamlit run` puts the *script's own directory* on sys.path, not the
# directory it was run from. Launched as `streamlit run frontend/ui/app.py`
# that is frontend/ui/, so the `frontend` package itself would not be
# importable and the next line would fail with "No module named 'frontend'".
# Putting the repository root on the path here makes every entry point work:
# this file by path, streamlit_app.py at the root, and an ordinary import.
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from frontend.ui.client import ApiError, Client, make_client  # noqa: E402

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


def _sidebar() -> Client:
    """Where the work happens, and whether it is actually reachable.

    With no API configured the redactor runs in this process and there is
    nothing to connect to, so the URL box would only be a way to break it. It
    appears when an API is configured, and not otherwise.
    """
    st.sidebar.header("Service")
    client: Client = make_client(st.session_state.get("api_url"))
    remote: bool = client.base_url != "in-process"

    if remote:
        # Streamlit types text_input as optional; it only returns None when the
        # widget has been cleared, which the default here prevents.
        url: str = (
            st.sidebar.text_input(
                "API URL",
                value=client.base_url,
                help="Where the FastAPI service is running.",
            )
            or client.base_url
        )
        if url != client.base_url:
            st.session_state["api_url"] = url
            client = make_client(url)

    try:
        health = client.health()
        version: str = health.get("version", "?")
        if remote:
            st.sidebar.success(f"Connected · v{version}")
        else:
            st.sidebar.success(f"Running in-process · v{version}")
        if not health.get("ocr_available", False):
            st.sidebar.warning(
                "OCR is off here. Scanned PDFs, which have no text layer, are "
                "reported as errors rather than redacted."
            )
    except ApiError as exc:
        st.sidebar.error(str(exc))
        if remote:
            st.sidebar.caption("Start it with: `uvicorn frontend.api.main:app`")

    st.sidebar.divider()
    st.sidebar.caption(
        "Files are held in this browser session for as long as you are using "
        "it. Nothing is written to disk and nothing is kept afterwards."
        if not remote
        else "Files are held in this browser session and sent with each "
        "request. The service stores nothing."
    )
    return client


# ---------------------------------------------------------------------------
# Step 1 - upload
# ---------------------------------------------------------------------------


def _step_upload(client: Client) -> None:
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


def _photo_choices(document: dict) -> list[int]:
    """Show every image in the document and return the ones to delete.

    Nothing in a PDF marks an image as a face, so this cannot be automatic. The
    preview is the whole point: a headshot and a company logo are both just
    pixels to the tool, and obvious to a person. Anything the size and shape of
    a photograph starts ticked, because leaving a face in is the worse mistake;
    untick a logo and it stays.
    """
    images: list[dict] = document.get("images") or []
    filename: str = document["filename"]
    if not images:
        return []

    likely: int = sum(1 for i in images if i["looks_like_a_photo"])
    st.caption(
        f"{len(images)} image(s) found"
        + (f", {likely} the shape of a photograph" if likely else ", none photo-shaped")
    )

    chosen: list[int] = []
    for row_start in range(0, len(images), 4):
        for column, image in zip(
            st.columns(4), images[row_start : row_start + 4], strict=False
        ):
            with column:
                if image.get("preview"):
                    st.image(image["preview"], width=110)
                else:
                    st.caption("(no preview)")
                if st.checkbox(
                    f"{image['width']}x{image['height']}",
                    value=image["looks_like_a_photo"],
                    key=f"photo::{filename}::{image['xref']}",
                    help=f"Delete this image (page {image['page']}, id {image['xref']})",
                ):
                    chosen.append(image["xref"])
    return chosen


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
        surnames: list[str] = [s.strip() for s in surnames_raw.split(",") if s.strip()]
        if not surnames:
            st.warning(
                "No surname given. The pattern rules (email, phone, links, "
                "address, date of birth) still run, but the surname will "
                "remain in the document."
            )

        photos: list[int] = _photo_choices(document)

    return {
        "filename": filename,
        "surnames": surnames,
        "output_name": output_name.strip() or filename,
        "photo_xrefs": photos,
    }


def _step_review(client: Client) -> list[dict]:
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


def _step_results(client: Client, plans: list[dict]) -> None:
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
