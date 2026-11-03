"""
DECCARA ("CSI Pt ; Pl ; Pb ; Pr ; Ps... $ r") applies an SGR to an area,
and DECRARA ("... $ t") turns attributes over there. DECSACE ("CSI Ps *
x") picks a stream or a rectangle. DECCARA takes every SGR, as kitty
does; DECRARA follows xterm, since kitty has none. Lillecarl/pymux#895.
"""

from __future__ import annotations

import pytest

from pyte.cells import ErasedCell, Protection, protection_of
from pyte.screen import Screen
from pyte.streams import Stream

ESC = "\x1b"
RECTANGLE = ESC + "[2*x"


@pytest.fixture
def pane():
    screen = Screen(4, 10, write_process_input=lambda data: None)
    stream = Stream(screen)
    for row in range(4):
        stream.feed(ESC + "[%dH" % (row + 1) + "abcdefghij")
    return screen, stream


def cell(screen, row, column):
    return screen.data_buffer[row + screen.line_offset].get(column)


def display(screen):
    rows = (screen.data_buffer[row + screen.line_offset] for row in range(screen.lines))
    return ["".join(line[column].char for column in range(screen.columns)) for line in rows]


def rendition(screen, row, column):
    return cell(screen, row, column).appearance.rendition


def bold_cells(screen):
    return {(row, column) for row in range(4) for column in range(10) if rendition(screen, row, column).bold}


def test_a_stream_runs_from_corner_to_corner(pane):
    screen, stream = pane
    stream.feed(ESC + "[2;8;3;3;1$r")
    expected = {(1, column) for column in range(7, 10)} | {(2, column) for column in range(3)}
    assert bold_cells(screen) == expected


def test_a_rectangle_takes_the_same_columns_on_every_row(pane):
    screen, stream = pane
    stream.feed(RECTANGLE + ESC + "[2;3;3;5;1$r")
    assert bold_cells(screen) == {(row, column) for row in (1, 2) for column in range(2, 5)}


def test_the_characters_stay(pane):
    screen, stream = pane
    stream.feed(ESC + "[1;1;4;10;1;31$r")
    assert display(screen) == ["abcdefghij"] * 4


def test_every_sgr_applies_colours_included(pane):
    screen, stream = pane
    sgr = "38;2;1;2;3;48;5;200;4:3;58;2;9;8;7;3"
    stream.feed(RECTANGLE + ESC + "[1;1;1;1;" + sgr + "$r")
    stream.feed(ESC + "[4H" + ESC + "[" + sgr + "mz")
    assert rendition(screen, 0, 0) == rendition(screen, 3, 0)


def test_no_sgr_is_sgr_zero(pane):
    screen, stream = pane
    stream.feed(ESC + "[1;1H" + ESC + "[1;41mab" + ESC + "[m")
    stream.feed(ESC + "[1;1;1;1$r")
    assert not rendition(screen, 0, 0).bold
    assert rendition(screen, 0, 1).bold


def test_an_empty_cell_takes_the_background():
    screen = Screen(2, 5, write_process_input=lambda data: None)
    stream = Stream(screen)
    stream.feed(RECTANGLE + ESC + "[1;1;2;5;44$r")
    painted = cell(screen, 1, 4)
    assert isinstance(painted, ErasedCell)
    assert painted.appearance.rendition.bgcolor is not None
    assert display(screen) == [" " * 5] * 2


def test_origin_mode_counts_from_the_margins(pane):
    screen, stream = pane
    stream.feed(ESC + "[2;4r" + ESC + "[?6h" + RECTANGLE + ESC + "[1;1;1;2;1$r")
    assert bold_cells(screen) == {(1, 0), (1, 1)}


def test_the_mark_of_decsca_stays(pane):
    screen, stream = pane
    stream.feed(ESC + "[1;1H" + ESC + '[1"qx' + ESC + '[0"q')
    stream.feed(ESC + "[1;1;1;1;1$r")
    assert protection_of(cell(screen, 0, 0)) & Protection.DEC
    assert rendition(screen, 0, 0).bold


def test_a_hyperlink_stays(pane):
    screen, stream = pane
    stream.feed(ESC + "[1;1H" + ESC + "]8;;https://example.org" + ESC + "\\x" + ESC + "]8;;" + ESC + "\\")
    stream.feed(ESC + "[1;1;1;1;1$r")
    assert cell(screen, 0, 0).appearance.hyperlink == "https://example.org"


def test_decrara_turns_attributes_over(pane):
    screen, stream = pane
    stream.feed(ESC + "[1;1H" + ESC + "[1ma" + ESC + "[m")
    stream.feed(ESC + "[1;1;1;2;1;7$t")
    first, second = rendition(screen, 0, 0), rendition(screen, 0, 1)
    assert (first.bold, first.reverse) == (False, True)
    assert (second.bold, second.reverse) == (True, True)


def test_decrara_zero_leaves_hidden_alone(pane):
    screen, stream = pane
    stream.feed(ESC + "[1;1;1;1;0$t")
    changed = rendition(screen, 0, 0)
    assert (changed.bold, changed.underline, changed.blink, changed.reverse) == (True,) * 4
    assert not changed.hidden


def test_decrara_ignores_a_colour(pane):
    screen, stream = pane
    before = cell(screen, 0, 0)
    stream.feed(ESC + "[1;1;1;1;31$t")
    assert cell(screen, 0, 0) is before
