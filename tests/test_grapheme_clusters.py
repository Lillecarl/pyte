"""
A grapheme cluster takes one cell, DEC 2027. Lillecarl/pymux#798.

On by default, as in kitty, Ghostty and tmux; a program turns it off
for itself, and then each code point takes its own width.
"""

from __future__ import annotations

import pytest

from pyte.modes import PrivateMode
from pyte.screen import Screen
from pyte.streams import Stream

FAMILY = "👨‍👩‍👧"
FLAG = "🇸🇪"
THUMB = "👍🏽"
RUNNER = "🏃‍♀️"


def screen_of(columns: int = 20, answers: list[str] | None = None) -> tuple[Screen, Stream]:
    screen = Screen(2, columns, (answers if answers is not None else []).append)
    return screen, Stream(screen)


def drawn(text: str, clusters: bool = True) -> Screen:
    screen, stream = screen_of()
    if not clusters:
        stream.feed("\x1b[?2027l")
    stream.feed(text)
    return screen


def cells(screen: Screen) -> list[str]:
    row = screen.page.data_buffer[0]
    return [row[x].char for x in sorted(row)]


@pytest.mark.parametrize("cluster", [FAMILY, FLAG, THUMB, RUNNER])
def test_a_cluster_is_one_cell_two_columns_wide(cluster):
    screen = drawn(cluster + "x")
    assert cells(screen) == [cluster, "", "x"]
    assert screen.pt_cursor_position.x == 3


@pytest.mark.parametrize("cluster", [FAMILY, FLAG, THUMB])
def test_a_cluster_written_in_pieces_is_one_cell(cluster):
    screen, stream = screen_of()
    for char in cluster:
        stream.feed(char)
    assert cells(screen)[0] == cluster
    assert screen.pt_cursor_position.x == 2


def test_with_the_mode_reset_each_code_point_takes_its_width():
    screen = drawn(FAMILY, clusters=False)
    assert screen.pt_cursor_position.x == 6


def test_text_around_a_cluster_is_its_own():
    screen = drawn("ab" + FLAG + "cd")
    assert cells(screen) == ["a", "b", FLAG, "", "c", "d"]


def test_two_flags_are_two_cells():
    screen = drawn(FLAG + FLAG)
    assert cells(screen) == [FLAG, "", FLAG, ""]


def test_a_flag_at_the_edge_wraps_whole():
    "Its first half is two columns on its own already, so the whole flag goes to the next row."
    screen, stream = screen_of(columns=3)
    stream.feed("ab" + FLAG)
    assert 2 not in screen.page.data_buffer[0]
    assert screen.page.data_buffer[1][0].char == FLAG


def test_the_mode_answers_decrqm_and_survives_a_soft_reset():
    answers: list[str] = []
    screen, stream = screen_of(answers=answers)
    stream.feed("\x1b[!p\x1b[?2027$p")
    assert PrivateMode.GRAPHEME_CLUSTERS.flag in screen.mode
    assert answers == ["\x1b[?2027;1$y"]
