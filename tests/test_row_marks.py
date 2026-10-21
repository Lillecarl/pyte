"""
A shell's prompt marks live on the row, so they move with it.

`Screen.mark_row` is what a front end calls for "OSC 133 ; A" and "C".
The marks were a list of row numbers beside the buffer, and a number
says where the cursor stood, not where that row is after a scroll or a
resize. Lillecarl/pymux#500.
"""

from __future__ import annotations

import json

from a_screen import a_screen

from pyte.freeze import Frozen, freeze, thaw
from pyte.page import RowMark
from pyte.streams import Stream


def _marked(screen, mark: RowMark = RowMark.PROMPT) -> list[str]:
    "The text of each row that holds `mark`, in order."
    rows = screen.page.data_buffer
    return [
        "".join(rows[number][column].char for column in range(max(rows[number], default=-1) + 1))
        for number in sorted(rows)
        if rows[number].marks & mark
    ]


def _prompted(columns: int = 10, lines: int = 5):
    "A shell that marks two prompts and the output of one command."
    screen = a_screen(columns, lines)
    stream = Stream(screen)
    for prompt, output in (("$ one", "first output"), ("$ two", "")):
        screen.mark_row(RowMark.PROMPT)
        stream.feed(prompt + "\r\n")
        screen.mark_row(RowMark.OUTPUT)
        stream.feed(output + "\r\n")
    return screen, stream


def test_a_mark_is_on_the_row_the_cursor_stands_on():
    screen, _ = _prompted()
    assert _marked(screen) == ["$ one", "$ two"]
    assert _marked(screen, RowMark.OUTPUT) == ["first outp", ""]


def test_a_mark_scrolls_with_its_row():
    screen, stream = _prompted()
    stream.feed("\r\n" * 10)
    assert _marked(screen) == ["$ one", "$ two"]


def test_a_reflow_keeps_the_mark_on_the_first_row_of_its_line():
    # Tall enough that nothing is in the history, which a reflow leaves
    # at the width it was written at.
    screen, _ = _prompted(lines=12)
    screen.resize(12, 4)
    assert _marked(screen) == ["$ on", "$ tw"]
    assert _marked(screen, RowMark.OUTPUT) == ["firs", ""]
    screen.resize(12, 20)
    assert _marked(screen) == ["$ one", "$ two"]
    assert _marked(screen, RowMark.OUTPUT) == ["first output", ""]


def test_an_erased_row_loses_its_mark():
    "tmux's `grid_empty_line` clears a line's flags with its cells."
    screen, stream = _prompted()
    stream.feed("\x1b[2J")
    assert _marked(screen) == ["$ one"]


def test_a_thawed_screen_keeps_its_marks():
    screen, _ = _prompted()
    thawed = a_screen(10, 5)
    # Through JSON, the way a snapshot carries it.
    thaw(Frozen(*json.loads(json.dumps(freeze(screen)))), thawed)
    assert _marked(thawed) == ["$ one", "$ two"]
    assert _marked(thawed, RowMark.OUTPUT) == ["first outp", ""]
    assert {type(row.marks) for row in thawed.page.data_buffer.values()} == {RowMark}
