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

from pyte import page, png, runs, screen, sixel, streams
from pyte.placeholders import PLACEHOLDER

from . import _native

__all__ = [
    "Row",
    "decode_sixel",
    "draw_on_row",
    "install",
    "installed",
    "rgba_of",
    "runs_of",
    "take_ground",
    "unfilter",
]

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

#: `pyte.streams._take_ground`, in Rust.
take_ground = _native.take_ground

#: `pyte.png._unfilter` and `pyte.png._rgba_of`, in Rust, with the GIL
#: released while they work. Lillecarl/pymux#574.
unfilter = _native.unfilter
rgba_of = _native.rgba_of

_pure_decode_sixel = sixel.decode_sixel


def decode_sixel(payload: str):
    """
    `pyte.sixel.decode_sixel`, in Rust, with the GIL released.

    The kernel answers `False` for a payload it cannot answer exactly:
    one that is not ASCII, or holds a number past 18 digits. Python reads
    Unicode digits, keeps numbers of any size and raises on one too big
    for a float, so it decodes those.
    """
    answer = _native.decode_sixel(payload)
    if answer is False:
        return _pure_decode_sixel(payload)
    return answer


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
        _replaced["pyte.streams._take_ground"] = streams._take_ground
        streams._take_ground = take_ground
        _replaced["pyte.png._unfilter"] = png._unfilter
        png._unfilter = unfilter
        _replaced["pyte.png._rgba_of"] = png._rgba_of
        png._rgba_of = rgba_of
        _replaced["pyte.sixel.decode_sixel"] = sixel.decode_sixel
        sixel.decode_sixel = decode_sixel
    return True


def installed() -> bool:
    return bool(_replaced)
