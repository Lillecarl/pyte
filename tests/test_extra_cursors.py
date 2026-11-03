"""
kitty's multiple cursors protocol: what a screen holds and answers.
`test_multi_cursors` in kitty_tests/screen.py is the source of the
first tests here. Lillecarl/pymux#891.
"""

from __future__ import annotations

import json

import pytest

from pyte.colors import Color, SgrColor
from pyte.extra_cursors import ColorSpace, CursorColor, ExtraShape
from pyte.freeze import Frozen, freeze, thaw
from pyte.screen import Screen
from pyte.sequences.reports import ExtraCursorColorsReport, ExtraCursorsReport, ExtraCursorsSupport
from pyte.streams import Stream


class Pane:
    def __init__(self, lines: int = 10, columns: int = 20) -> None:
        self.replies: list[str] = []
        self.screen = Screen(lines, columns, write_process_input=self.replies.append)
        self.stream = Stream(self.screen)

    def feed(self, payload: str) -> None:
        self.stream.feed("\x1b[>%s q" % payload)

    def answer(self, payload: str) -> str:
        self.replies.clear()
        self.feed(payload)
        assert len(self.replies) == 1, self.replies
        return self.replies[0]

    def current(self) -> dict[int, set[tuple[int, int]]]:
        "kitty's `current()`: the shapes, each with its columns and rows."
        report = ExtraCursorsReport.parse(self.answer("100"))
        assert report is not None
        found: dict[int, set[tuple[int, int]]] = {}
        for row, column, shape in report.cursors:
            found.setdefault(int(shape), set()).add((column, row))
        return found


def test_a_screen_says_what_it_reads():
    pane = Pane()
    assert pane.answer("") == "\x1b[>1;2;3;29;30;40;100;101 q"
    assert ExtraCursorsSupport.parse(pane.replies[0]) == ExtraCursorsSupport((1, 2, 3, 29, 30, 40, 100, 101))


def test_kittys_own_sequence_of_shapes():
    pane = Pane()
    screen = pane.screen
    assert pane.answer("100") == "\x1b[>100 q"
    pane.feed("1;4")
    assert pane.current() == {1: {(x, y) for x in range(screen.columns) for y in range(screen.lines)}}
    pane.feed("0;4")
    assert pane.current() == {}
    pane.feed("29;4:3:2:4:3")
    assert pane.current() == {29: {(1, 2), (2, 2), (1, 3), (2, 3)}}
    pane.feed("2;2:3:2;2:4:2")
    assert pane.current() == {29: {(2, 3), (2, 2)}, 2: {(1, 2), (1, 3)}}
    pane.feed("0;2:3:2;2:4:3")
    assert pane.current() == {29: {(2, 2)}, 2: {(1, 3)}}
    pane.feed("0;4")
    pane.stream.feed("\x1b[3;2H")
    pane.feed("3;0")
    assert pane.current() == {3: {(1, 2)}}
    pane.feed("3;2:3")
    assert pane.current() == {3: {(1, 2)}}, "an odd coordinate is left over and counts for nothing"
    pane.feed("0;4:3:1:4")
    assert pane.current() == {}, "fewer than four numbers is the whole screen"


def test_the_report_lists_points_counted_from_one():
    pane = Pane()
    pane.feed("2;2:1:5;2:2:3")
    assert pane.answer("100") == "\x1b[>100;2:2:1:5;2:2:2:3 q"
    assert ExtraCursorsReport.parse(pane.replies[0]) == ExtraCursorsReport(
        ((0, 4, ExtraShape.BEAM), (1, 2, ExtraShape.BEAM))
    )


def test_cells_off_the_screen_are_ignored():
    pane = Pane(lines=5, columns=8)
    pane.feed("1;2:6:1;2:1:9;2:0:1")
    assert pane.current() == {}
    pane.feed("1;4:4:7:9:20")
    assert pane.current() == {1: {(6, 3), (7, 3), (6, 4), (7, 4)}}, "a rectangle is cut to the screen"


def test_a_rectangle_clears_only_its_cells():
    pane = Pane()
    pane.feed("1;4:1:1:2:2")
    pane.feed("0;4:1:1:1:2")
    assert pane.current() == {1: {(0, 1), (1, 1)}}


@pytest.mark.parametrize("which", [30, 40])
@pytest.mark.parametrize(
    ("payload", "color"),
    [
        ("0", CursorColor()),
        ("1", CursorColor(ColorSpace.SPECIAL)),
        ("2:1:2:3", CursorColor(ColorSpace.RGB, SgrColor(rgb=Color(1, 2, 3)))),
        ("5:13", CursorColor(ColorSpace.INDEXED, SgrColor(index=13))),
    ],
)
def test_kittys_colours(which, payload, color):
    pane = Pane()
    pane.feed("%d;%s" % (which, payload))
    report = ExtraCursorColorsReport.parse(pane.answer("101"))
    assert report is not None
    assert (report.text if which == 30 else report.cursor) == color


def test_the_colour_report_names_both():
    pane = Pane()
    assert pane.answer("101") == "\x1b[>101;30:0;40:0 q"
    pane.feed("40;2:255:0:10")
    pane.feed("30;1")
    assert pane.answer("101") == "\x1b[>101;30:1;40:2:255:0:10 q"


def test_a_colour_with_too_few_numbers_changes_nothing():
    pane = Pane()
    pane.feed("40;5:3")
    pane.feed("40;2:1:2")
    assert pane.answer("101") == "\x1b[>101;30:0;40:5:3 q"


@pytest.mark.parametrize("erase", ["\x1b[2J", "\x1b[3J", "\x1b[22J"])
def test_clearing_the_screen_takes_the_cursors(erase):
    pane = Pane()
    pane.feed("1;2:1:1")
    pane.stream.feed(erase)
    assert pane.current() == {}


def test_erasing_part_of_the_screen_keeps_them():
    pane = Pane()
    pane.feed("1;2:1:1")
    pane.stream.feed("\x1b[J\x1b[1J")
    assert pane.current() == {1: {(0, 0)}}


@pytest.mark.parametrize("mode", ["1049", "1047", "47"])
def test_either_switch_of_screen_takes_the_cursors(mode):
    pane = Pane()
    pane.feed("1;2:1:1")
    pane.stream.feed("\x1b[?%sh" % mode)
    assert pane.current() == {}
    pane.feed("1;2:2:2")
    pane.stream.feed("\x1b[?%sl" % mode)
    assert pane.current() == {}


@pytest.mark.parametrize("reset", ["\x1bc", "\x1b[!p"])
def test_a_reset_takes_the_cursors_and_the_colours(reset):
    pane = Pane()
    pane.feed("1;2:1:1")
    pane.feed("40;5:3")
    pane.stream.feed(reset)
    assert pane.current() == {}
    assert pane.answer("101") == "\x1b[>101;30:0;40:0 q"


def test_a_scroll_moves_no_cursor():
    pane = Pane(lines=3)
    pane.feed("1;2:3:1")
    pane.stream.feed("\x1b[3;1H\n\n\x1bM")
    assert pane.current() == {1: {(0, 2)}}


def test_a_smaller_screen_drops_what_it_no_longer_holds():
    pane = Pane()
    pane.feed("1;2:1:1;2:10:20")
    changes = pane.screen.extra_cursors.changes
    pane.screen.resize(5, 10)
    assert pane.current() == {1: {(0, 0)}}
    assert pane.screen.extra_cursors.changes > changes


def test_every_change_moves_the_count():
    pane = Pane()
    extra = pane.screen.extra_cursors
    before = extra.changes
    pane.feed("1;2:1:1")
    assert extra.changes > before


def test_an_upgrade_keeps_the_cursors_and_the_colours():
    pane = Pane()
    pane.feed("1;2:1:1;2:3:4")
    pane.feed("40;2:1:2:3")
    frozen = json.loads(json.dumps(freeze(pane.screen)))
    thawed = Pane()
    thaw(Frozen(*frozen), thawed.screen)
    assert thawed.current() == pane.current()
    assert thawed.answer("101") == pane.answer("101")


def test_decscusr_still_sets_the_main_cursor():
    pane = Pane()
    pane.stream.feed("\x1b[5 q")
    assert pane.screen.cursor_style == 5
    assert pane.screen.extra_cursors.cells == {}
