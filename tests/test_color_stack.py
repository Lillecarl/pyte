"""
The colour stack: xterm's XTPUSHCOLORS, XTPOPCOLORS and XTREPORTCOLORS
("CSI # P", "CSI # Q", "CSI # R"), and kitty's "OSC 30001" and
"OSC 30101" for the first two. The arithmetic is kitty's
(`colorprofile_push_colors` and its neighbours, kitty/colors.c).
Lillecarl/pymux#894.
"""

from __future__ import annotations

import pytest

from pyte.osc import COLOR_STACK_DEPTH
from pyte.screen import Screen
from pyte.streams import Stream

ESC = "\x1b"
PUSH, POP, REPORT = ESC + "[#P", ESC + "[#Q", ESC + "[#R"
KITTY_PUSH, KITTY_POP = ESC + "]30001" + ESC + "\\", ESC + "]30101" + ESC + "\\"


def set_background(spec: str) -> str:
    return ESC + "]11;" + spec + ESC + "\\"


@pytest.fixture
def pane():
    replies = []
    screen = Screen(5, 10, write_process_input=replies.append)
    return screen, Stream(screen), replies


def background(screen) -> str | None:
    color = screen.colors.by_code.get("11")
    return None if color is None else color.hex


@pytest.mark.parametrize(("push", "pop"), [(PUSH, POP), (KITTY_PUSH, KITTY_POP)])
def test_a_pop_brings_back_the_pushed_colours(pane, push, pop):
    screen, stream, _replies = pane
    stream.feed(set_background("#102030") + push + set_background("#ffffff"))
    assert background(screen) == "#ffffff"
    stream.feed(pop)
    assert background(screen) == "#102030"


def test_a_pop_of_nothing_changes_nothing(pane):
    screen, stream, _replies = pane
    stream.feed(set_background("#102030") + POP)
    assert background(screen) == "#102030"


def test_the_report_counts_the_pushes(pane):
    screen, stream, replies = pane
    stream.feed(PUSH + PUSH + REPORT)
    assert replies[-1] == ESC + "[1;2#Q"
    stream.feed(POP + REPORT)
    assert replies[-1] == ESC + "[0;1#Q"


def test_a_full_stack_drops_its_oldest(pane):
    screen, stream, replies = pane
    for value in range(COLOR_STACK_DEPTH + 1):
        stream.feed(set_background("#0000%02x" % value) + PUSH)
    stream.feed(REPORT)
    assert replies[-1] == ESC + "[%d;%d#Q" % (COLOR_STACK_DEPTH - 1, COLOR_STACK_DEPTH)
    for _ in range(COLOR_STACK_DEPTH):
        stream.feed(POP)
    assert background(screen) == "#000001"


def test_a_numbered_pop_keeps_the_entry(pane):
    screen, stream, _replies = pane
    stream.feed(set_background("#102030") + PUSH + set_background("#ffffff"))
    stream.feed(ESC + "[1#Q")
    assert background(screen) == "#102030"
    stream.feed(set_background("#ffffff") + ESC + "[1#Q")
    assert background(screen) == "#102030"
