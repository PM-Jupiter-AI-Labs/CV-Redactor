"""Entry point for the Streamlit UI.

    streamlit run streamlit_app.py

This file exists because of how `streamlit run` sets up imports: it puts the
*script's own directory* on `sys.path`, not the directory you ran it from. Point
it straight at `frontend/ui/app.py` and `frontend/ui/` goes on the path, so
`import frontend.ui.client` fails with "No module named 'frontend'" -- the
package root was never on the path at all.

Living at the repository root fixes that by construction: this directory goes on
the path, so `frontend` is an importable package and the app can use ordinary
absolute imports that also work under pytest and a type checker.

It is also the filename Streamlit Community Cloud looks for by default, so a
deployment there needs no extra configuration.
"""

from __future__ import annotations

from frontend.ui.app import main

main()
