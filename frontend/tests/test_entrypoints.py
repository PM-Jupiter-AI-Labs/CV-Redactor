"""The UI has to start, whichever way someone launches it.

This exists because it did not. `streamlit run frontend/ui/app.py` -- the
obvious command, and the one the docs used at the time -- died with
`ModuleNotFoundError: No module named 'frontend'`, and nothing caught it: the
API tests never import the UI, and a plain `GET /` against a running Streamlit
returns 200 because the shell HTML is served before the script is ever executed.

So these tests reproduce what `streamlit run` actually does. Its runner puts the
*script's own directory* on `sys.path` -- not the working directory -- and then
executes the file. Each test does exactly that in a subprocess, which keeps the
manipulated path out of the test session.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[2]

ENTRY_POINTS: list[tuple[str, Path]] = [
    ("root launcher", REPO_ROOT / "streamlit_app.py"),
    ("module path", REPO_ROOT / "frontend" / "ui" / "app.py"),
]


def run_as_streamlit_would(script: Path) -> subprocess.CompletedProcess[str]:
    """Execute `script` with the sys.path `streamlit run` would give it.

    Run from a directory unrelated to the project, so a lucky working directory
    cannot make a broken import look fine -- which is precisely how the original
    bug survived a manual test.
    """
    harness: str = textwrap.dedent(f"""
        import runpy, sys
        # What streamlit's script runner does: the script's own directory.
        sys.path.insert(0, {str(script.parent)!r})
        runpy.run_path({str(script)!r}, run_name="__main__")
        print("ENTRYPOINT_OK")
    """)
    return subprocess.run(
        [sys.executable, "-c", harness],
        capture_output=True,
        text=True,
        cwd=script.parent.parent if script.parent != REPO_ROOT else "/",
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("label,script", ENTRY_POINTS, ids=[e[0] for e in ENTRY_POINTS])
def test_entry_point_imports_cleanly(label: str, script: Path) -> None:
    """Every documented way of starting the UI must get past its imports."""
    result = run_as_streamlit_would(script)
    combined: str = result.stdout + result.stderr
    assert "ModuleNotFoundError" not in combined, (
        f"{label} ({script.name}) cannot resolve its imports:\n{combined}"
    )
    # Streamlit calls outside a real session warn but do not raise, so reaching
    # the end of the script is the signal that the module body executed.
    assert "ENTRYPOINT_OK" in result.stdout, (
        f"{label} ({script.name}) did not finish executing:\n{combined}"
    )


def test_app_module_is_importable_as_a_package() -> None:
    """The launcher does `from frontend.ui.app import main`, so this must hold.

    A flat `from client import ...` inside app.py would start under
    `streamlit run` and break here, which is the trade-off that made the
    sys.path bootstrap the better fix.
    """
    result = subprocess.run(
        [sys.executable, "-c", "from frontend.ui.app import main; print('IMPORT_OK')"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
        check=False,
    )
    assert "IMPORT_OK" in result.stdout, result.stdout + result.stderr
