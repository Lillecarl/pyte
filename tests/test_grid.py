"""
A page carried as frames of rows shows what the screen it came from shows.

`pyte.grid` is what a pymux server sends a peer that mirrors a pane:
the visible page, as the rows that changed since the last frame.
Lillecarl/pymux#759.
"""

from __future__ import annotations

import json
import random

import pytest
from a_screen import a_screen
from test_freeze import AFTER, BEFORE, CSI, OSC, ST, STEPS

from pyte.cells import PLAIN, ErasedCell, Rendition
from pyte.colors import SgrColor
from pyte.grid import GridWriter, put_frame, row_data, row_of
from pyte.page import Row
from pyte.screen import Screen
from pyte.sgr import parameters_of, rendition_of
from pyte.streams import Stream


def _page(screen: Screen) -> dict:
    "What a person sees: each row of the page, the cursor and its shape."
    top = screen.line_offset
    rows = []
    for y in range(screen.lines):
        row = screen.page.data_buffer.get(top + y)
        cells = []
        for column in sorted(row or ()):
            assert row is not None
            cell = row[column]
            if column < screen.columns and cell.char != " " or cell.written:
                cells.append((column, cell.char, cell.appearance, type(cell) is ErasedCell))
        rows.append((bool(row is not None and row.wrapped), cells))
    position = screen.pt_cursor_position
    return {
        "size": (screen.lines, screen.columns),
        "rows": rows,
        "cursor": (position.x, position.y - top, screen.pending_wrap, screen.page.show_cursor),
        "style": screen.cursor_style if screen.cursor_style_asked else None,
        "title": screen.titles.window,
        "pointer": screen.pointer_shapes.shape,
    }


def _same(screen: Screen, copy: Screen) -> None:
    mine, theirs = _page(copy), _page(screen)
    for key in mine:
        assert mine[key] == theirs[key], key


def _carried(frame: dict | None) -> dict | None:
    "A frame as the peer reads it: through JSON, which knows no tuple."
    return None if frame is None else json.loads(json.dumps(frame))


class Peer:
    def __init__(self, screen: Screen) -> None:
        self.writer = GridWriter()
        self.copy = a_screen(screen.columns, screen.lines)
        self.sync(screen)

    def sync(self, screen: Screen) -> dict | None:
        frame = _carried(self.writer.frame(screen))
        if frame is not None:
            put_frame(self.copy, frame)
        return frame


@pytest.mark.parametrize("seed", range(60))
def test_the_copy_shows_the_page_through_anything_a_program_writes(seed):
    choose = random.Random(seed)
    screen = a_screen(40, 12, history=50)
    stream = Stream(screen)
    peer = Peer(screen)
    program = BEFORE + "".join(choose.choice([*STEPS[:-1], AFTER]) for _ in range(40))
    start = 0
    while start < len(program):
        end = start + choose.randint(1, 40)
        stream.feed(program[start:end])
        start = end
        if choose.random() < 0.05:
            screen.resize(choose.randint(5, 30), choose.randint(20, 100))
        # Frames skipped are frames a slow peer never got.
        if choose.random() < 0.5:
            peer.sync(screen)
            _same(screen, peer.copy)
    peer.sync(screen)
    _same(screen, peer.copy)


#: One thing each, so a failure names it.
CORNERS = {
    "colours": CSI + "1;38;5;196;48;2;10;20;30mred" + CSI + "0m plain",
    "curly": CSI + "4:3;58:2::1:2:3mcurly" + CSI + "0m",
    "a link": OSC + "8;id=one;https://example.com" + ST + "link" + OSC + "8;;" + ST,
    "wide": "中文 é",
    "a coloured erase": CSI + "41m" + CSI + "K" + CSI + "0m",
    "an erase": "abc" + CSI + "2D" + CSI + "X",
    "gaps": "a" + CSI + "5Cb" + CSI + "10Cc",
    "a wrapped line": "w" * 100,
    "a pending wrap": CSI + "12;1H" + "x" * 40,
    "a hidden cursor": CSI + "?25l",
    "a cursor shape": CSI + "4 q",
    "a title": OSC + "2;the title" + ST,
    "a pointer": OSC + "22;>wait,text" + ST,
    "the alternate page": "first\r\n" + CSI + "?1049h" + "second" + CSI + "3;3H",
    "history": "".join("line %d\r\n" % number for number in range(60)),
}


@pytest.mark.parametrize("name", CORNERS)
def test_each_corner_shows_the_same(name):
    screen = a_screen(40, 12)
    stream = Stream(screen)
    peer = Peer(screen)
    stream.feed(CORNERS[name])
    peer.sync(screen)
    _same(screen, peer.copy)


def test_a_frame_holds_what_changed():
    screen = a_screen(40, 12)
    stream = Stream(screen)
    stream.feed("one\r\ntwo\r\nthree")
    peer = Peer(screen)
    assert peer.sync(screen) is None
    stream.feed(CSI + "2;1Hzwo")
    frame = peer.sync(screen)
    assert frame is not None
    assert [y for y, _row in frame["rows"]] == [1]
    _same(screen, peer.copy)


def test_a_new_title_alone_sends_a_frame():
    screen = a_screen(40, 12)
    stream = Stream(screen)
    peer = Peer(screen)
    stream.feed(OSC + "2;renamed" + ST)
    frame = peer.sync(screen)
    assert frame is not None
    assert frame["rows"] == []
    assert peer.copy.titles.window == "renamed"


def test_a_row_written_again_the_same_sends_nothing():
    screen = a_screen(40, 12)
    stream = Stream(screen)
    stream.feed("same")
    peer = Peer(screen)
    stream.feed(CSI + "1;1Hsame")
    assert peer.sync(screen) is None


def test_an_old_peer_reads_past_what_it_does_not_know():
    row = Row()
    data = row_data(row, 10)
    data["glow"] = True
    data["runs"] = [{"x": 2, "cells": ["a"], "sgr": "1", "sparkle": 3}]
    copy = row_of(data)
    assert copy[2].char == "a"
    assert copy[2].appearance.rendition.bold


def test_a_character_keeps_the_owners_column():
    "The peer may count a width differently; the owner's column wins."
    copy = row_of({"runs": [{"x": 0, "cells": ["中", "", "x"]}]})
    assert copy[2].char == "x"


@pytest.mark.parametrize(
    "rendition",
    [
        PLAIN,
        Rendition(bold=True, italic=True, strike=True),
        Rendition(color=SgrColor(1), bgcolor=SgrColor(200)),
        Rendition(color=SgrColor(rgb=(1, 2, 3)), reverse=True),
        Rendition(underline=True, underline_style="curly", underline_color=SgrColor(rgb=(4, 5, 6))),
        Rendition(underline=True, underline_style="double", underline_color=SgrColor(33)),
        Rendition(dim=True, hidden=True, blink=True, baseline="superscript"),
    ],
)
def test_sgr_parameters_read_back_as_the_rendition(rendition):
    assert rendition_of(parameters_of(rendition)) == rendition
