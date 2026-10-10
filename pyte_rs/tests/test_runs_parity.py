"""
`pyte_rs.runs_of` gives the answer `pyte.runs.runs_of` gives.

The Python is the reference. Each test builds rows, asks both, and
compares the runs field by field, the appearance by identity, because
a front end looks a style up by the object. Lillecarl/pymux#566.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import pyte_rs
from pyte.cells import _CHAR_CACHE, ErasedCell
from pyte.page import Row
from pyte.placeholders import PLACEHOLDER
from pyte.runs import runs_of
from pyte.screen import Screen
from pyte.streams import Stream

PIECES = [
    "text",
    "  ",
    " gap ",
    "\x1b[1;31m",
    "\x1b[0m",
    "\x1b[7m",
    "\x1b[38;5;99m",
    "\x1b[K",
    "\x1b[1K",
    "\x1b[2;3H",
    "\x1b[5G",
    "\x1b[3X",
    "\r\n",
    "漢字",
    "é",
    "é",
    "⡑",
    PLACEHOLDER + "̅",
    "~",
    "\x1b[41m  \x1b[0m",
    "trailing   ",
]


def same(left, right) -> bool:
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if a.appearance is not b.appearance:
            return False
        if (a.start, a.end, a.text, a.written, a.plain, a.blank) != (
            b.start,
            b.end,
            b.text,
            b.written,
            b.plain,
            b.blank,
        ):
            return False
        if type(a) is not type(b):
            return False
    return True


def check_screen(screen: Screen) -> None:
    for number, row in list(screen.page.data_buffer.items()):
        expected = runs_of(row)
        got = pyte_rs.runs_of(row)
        assert same(expected, got), "row %d: %r != %r" % (number, expected, got)


@given(st.lists(st.sampled_from(PIECES), min_size=1, max_size=60))
@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_a_screen_a_program_wrote(pieces):
    screen = Screen(6, 20, write_process_input=lambda _: None)
    Stream(screen).feed("".join(pieces))
    check_screen(screen)


#: Characters no parser leaves in a cell, which a row may still hold:
#: a control, the delete character, a lone surrogate, and nothing.
ODD = ["\x01", "\x7f", "\udcff", "", " ", "a", "~", "é", "漢", PLACEHOLDER, "é"]


@given(
    st.lists(
        st.tuples(
            st.integers(0, 30),
            st.sampled_from(ODD),
            st.booleans(),
            st.integers(0, 2),
        ),
        max_size=30,
    )
)
@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_a_row_put_together_by_hand(cells):
    "Any order of columns, any character, written and erased cells mixed."
    screen = Screen(2, 10, write_process_input=lambda _: None)
    stream = Stream(screen)
    appearances = [screen._appearance]
    stream.feed("\x1b[1m")
    appearances.append(screen._appearance)
    stream.feed("\x1b[0;7m")
    appearances.append(screen._appearance)
    row = Row()
    for column, char, written, kind in cells:
        appearance = appearances[kind]
        row[column] = _CHAR_CACHE[char, appearance] if written else ErasedCell(char, appearance)
    assert same(runs_of(row), pyte_rs.runs_of(row))


def a_fresh_install(monkeypatch):
    "Undo whatever `install()` does once the test is over."
    import pyte.runs
    import pyte.screen

    monkeypatch.setattr(pyte.runs, "runs_of", pyte.runs.runs_of)
    monkeypatch.setattr(pyte.screen, "_draw_on_row", pyte.screen._draw_on_row)
    monkeypatch.setattr(pyte_rs, "_replaced", {})
    return pyte.runs, pyte.screen


def test_install_puts_the_kernels_in_place(monkeypatch):
    runs_module, screen_module = a_fresh_install(monkeypatch)
    monkeypatch.delenv(pyte_rs.PURE, raising=False)
    assert pyte_rs.install() is True
    assert runs_module.runs_of is pyte_rs.runs_of
    assert screen_module._draw_on_row is pyte_rs.draw_on_row


def test_pure_says_not_to(monkeypatch):
    runs_module, screen_module = a_fresh_install(monkeypatch)
    monkeypatch.setenv(pyte_rs.PURE, "1")
    assert pyte_rs.install() is False
    assert runs_module.runs_of is runs_of
    assert screen_module._draw_on_row is not pyte_rs.draw_on_row
