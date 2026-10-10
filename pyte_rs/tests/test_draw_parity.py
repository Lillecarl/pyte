"""
`pyte_rs.draw_on_row` draws what `pyte.screen._draw_on_row` draws.

Two screens take the same bytes, one drawing through the Python and
one through Rust, and every cell, the cursor and the write counts
have to agree. A cell is compared by what it is and not by identity:
an erase makes a cell of its own on each screen. The write counts
are what say whether a row kept its objects, so they hold that.
Lillecarl/pymux#566.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import pyte.screen
import pyte_rs
from pyte.screen import Screen
from pyte.streams import Stream

PIECES = [
    "text",
    "a long line that runs past the edge of a narrow screen",
    "  ",
    "\x1b[1;31m",
    "\x1b[0m",
    "\x1b[7m",
    "\x1b[K",
    "\x1b[2;3H",
    "\x1b[18G",
    "\x1b[4h",
    "\x1b[4l",
    "\x1b[?7l",
    "\x1b[?7h",
    "\x1b[?69h\x1b[3;12s",
    "\x1b[?69l",
    '\x1b[2"q',
    '\x1b[0"q',
    "\x1b(0",
    "\x1b(B",
    "\x1bN",
    "\r\n",
    "\x1b[5b",
    "漢字",
    "e\u0301",
    "\u00e9",
    "\udcff",
]


#: The reference, taken before any test could have installed the kernel.
PURE_DRAW = pyte.screen._draw_on_row


def screens_after(text: str):
    made = []
    for draw in (PURE_DRAW, pyte_rs.draw_on_row):
        saved = pyte.screen._draw_on_row
        pyte.screen._draw_on_row = draw
        try:
            screen = Screen(5, 20, write_process_input=lambda _: None)
            Stream(screen).feed(text)
        finally:
            pyte.screen._draw_on_row = saved
        made.append(screen)
    return made


def cells_of(screen: Screen):
    return {
        (y, x): (type(cell), cell.char, cell.appearance, getattr(cell, "protection", 0))
        for y, row in screen.page.data_buffer.items()
        for x, cell in row.items()
    }


@given(st.lists(st.sampled_from(PIECES), min_size=1, max_size=40))
@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_a_screen_draws_the_same_cells(pieces):
    pure, fast = screens_after("".join(pieces))
    assert cells_of(pure) == cells_of(fast)
    assert (pure.pt_cursor_position.x, pure.pt_cursor_position.y) == (
        fast.pt_cursor_position.x,
        fast.pt_cursor_position.y,
    )
    assert pure.pending_wrap == fast.pending_wrap
    assert pure.written_at == fast.written_at
    assert pure.writes == fast.writes
