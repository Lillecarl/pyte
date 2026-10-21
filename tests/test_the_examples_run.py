"""
Every example that needs nothing but pyte runs, and says what it says.

The lint reads `examples/` and nothing ran it, so six of seven broke
against a new `Screen` with no red check. `webterm.py` and
`terminal_emulator.py` need a web server and Textual, which pyte does
not depend on, so only the lint holds those. Lillecarl/pymux#672.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXAMPLES = Path(__file__).parent.parent / "examples"

#: A program for the two examples that start one, with no PATH to find.
HELLO = [sys.executable, "-c", "print('hello from the pty')"]


def run(name: str, *argv: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    done = subprocess.run(
        [sys.executable, str(EXAMPLES / name), *argv],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done


def test_helloworld_draws_the_greeting_on_the_first_row():
    assert run("helloworld.py").stdout.splitlines()[0] == " 1 Hello World! ¶"


def test_history_keeps_the_pages_above_the_one_shown():
    said = run("history.py", stdin="\n").stdout
    assert "36 rows held, the page shows rows 25..36." in said
    assert "The two pages above this one are still in the buffer!" in said


def test_debug_names_each_event_of_the_blob_on_stderr():
    said = run("debug.py").stderr
    assert "mountains." in said


def test_nanoterm_shows_what_the_program_wrote():
    assert run("nanoterm.py", *HELLO).stdout.splitlines()[0] == "hello from the pty"


def test_capture_writes_what_the_program_wrote(tmp_path):
    captured = tmp_path / "captured"
    run("capture.py", str(captured), *HELLO)
    assert b"hello from the pty" in captured.read_bytes()
