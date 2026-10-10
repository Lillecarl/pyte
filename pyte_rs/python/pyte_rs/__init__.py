"""
Rust kernels for pyte's per-cell loops.

`install()` puts each kernel in place of the Python function it
replaces. Nothing changes until it is called, and the Python stays the
reference: every kernel gives the same answer, and the parity tests
hold it to that. An embedder calls `install()` once, early.
Lillecarl/pymux#566.
"""

from __future__ import annotations

import os

from pyte import page, runs, screen
from pyte.placeholders import PLACEHOLDER

from . import _native

__all__ = ["Row", "draw_on_row", "install", "installed", "runs_of"]

#: One row of a page, stored by column in Rust. Lillecarl/pymux#570.
Row = _native.Row

#: Set to anything but "" or "0", and `install()` installs nothing.
PURE = "PYTERM_PURE"

#: The functions `install()` replaced, by where they live.
_replaced: dict[str, object] = {}

_pure_runs_of = runs.runs_of
_new_run = tuple.__new__


def runs_of(row):
    "`pyte.runs.runs_of`, in Rust."
    try:
        return _native.runs_of(row, runs.Run, PLACEHOLDER, _new_run)
    except UnicodeEncodeError:
        # A lone surrogate, which a program can write and Rust cannot
        # hold as text. The Python handles it.
        return _pure_runs_of(row)


#: `pyte.screen._draw_on_row`, in Rust.
draw_on_row = _native.draw_on_row


def install() -> bool:
    "Put every kernel in place, unless `PYTERM_PURE` says not to."
    if os.environ.get(PURE, "") not in ("", "0"):
        return False
    if not _replaced:
        _replaced["pyte.runs.runs_of"] = runs.runs_of
        runs.runs_of = runs_of
        _replaced["pyte.screen._draw_on_row"] = screen._draw_on_row
        screen._draw_on_row = draw_on_row
        _replaced["pyte.page.Row"] = page.Row
        page.Row = Row
    return True


def installed() -> bool:
    return bool(_replaced)
