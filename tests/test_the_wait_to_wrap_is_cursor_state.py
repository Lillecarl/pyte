"""
The wait to wrap belongs to the cursor, and travels with it.

A character in the last column leaves the cursor **waiting to wrap**:
the next character starts the row below. The wait is where the cursor
is -- one column past the last it wrote -- and not a thing beside it.

pyte dropped it in three places, and three issues were open as three
questions. They are one flag, which is Lillecarl/pymux#107's point:

- a tab stop move, `CSI Z` (Lillecarl/pymux#106)
- a save and a restore, `ESC 7` and `ESC 8` (Lillecarl/pymux#88)
- giving the alternate screen back, `?47l` (Lillecarl/pymux#35)

xterm keeps it through all three, and so do Alacritty and Ghostty. The
panel splits four to three on the first two and is unanimous on the
third; `ptterm/tests/test_wait_to_wrap_panel.py` holds that tally, and
Carl decided the flag should be carried everywhere.

Every test here fills a row first, so the cursor is waiting, then does
the thing, then writes one character. Where that character lands is the
whole answer: the row below means the wait came through.
"""

import pytest

from pyte import escape
from pyte.modes import PrivateMode
from pyte.screen import Screen
from pyte.sequences import Csi, csi, esc, reset_mode, set_mode
from pyte.streams import Stream

#: Eight columns, so one run of "a" fills a row and leaves the wait.
COLUMNS = 8
FULL_ROW = "a" * COLUMNS


def _waiting(lines: int = 4, columns: int = COLUMNS):
    "A screen whose cursor has just filled a row, so it waits to wrap."
    screen = Screen(lines, columns, write_process_input=lambda data: None)
    stream = Stream(screen)
    stream.feed(FULL_ROW)
    assert screen.pending_wrap, "the row did not leave the cursor waiting"
    return screen, stream


def _where(screen, char: str):
    "The row and the column that this character was drawn in."
    for row, line in sorted(screen.page.data_buffer.items()):
        for column, cell in sorted(line.items()):
            if cell.char == char:
                return row, column
    raise AssertionError("%r was not drawn at all" % (char,))


# ----------------------------------------------------------------------
# A tab stop move. Lillecarl/pymux#106.


@pytest.mark.parametrize("count", [None, 1, 2, 5])
def test_a_tab_stop_back_leaves_a_waiting_cursor_alone(count):
    """
    `CSI Z` moves back over tab stops, and a cursor that waits to wrap
    does not move at all: the next character wraps instead. However
    many stops are asked for.
    """
    screen, stream = _waiting()
    stream.feed(csi(Csi.CBT, *([] if count is None else [count])) + "z")

    assert _where(screen, "z") == (1, 0)


def test_a_tab_stop_back_still_works_without_a_wait():
    "The rule is about the wait, and touches nothing else."
    screen = Screen(4, 24, write_process_input=lambda data: None)
    stream = Stream(screen)
    stream.feed(csi(Csi.CHT) + csi(Csi.CHT) + csi(Csi.CBT) + "z")

    assert _where(screen, "z") == (0, 8)


# ----------------------------------------------------------------------
# A save and a restore. Lillecarl/pymux#88.


PAIRS = [
    (esc(escape.DECSC), esc(escape.DECRC)),
    (csi(Csi.DECSLRM), csi(Csi.KITTY_KEYBOARD)),
    (set_mode(PrivateMode.SAVE_CURSOR), reset_mode(PrivateMode.SAVE_CURSOR)),
]


@pytest.mark.parametrize("save, restore", PAIRS)
def test_a_save_and_a_restore_bring_the_wait_back(save, restore):
    """
    The cursor moves away between the two, so the restore has to put
    both the column and the wait back.
    """
    screen, stream = _waiting()
    stream.feed(save + csi(escape.CUP, 1, 1) + restore + "b")

    assert _where(screen, "b") == (1, 0)


@pytest.mark.parametrize("save, restore", PAIRS)
def test_a_save_and_a_restore_with_no_move_change_nothing(save, restore):
    """
    The case that is hard to argue about: with nothing in between, a
    save and a restore are a no-op in Alacritty, Ghostty, libvterm and
    WezTerm, and used to move the cursor here.
    """
    screen, stream = _waiting()
    stream.feed(save + restore + "b")

    assert _where(screen, "b") == (1, 0)


def test_a_restore_with_nothing_saved_leaves_no_wait():
    "It brings back the state a terminal starts with, which has none."
    screen, stream = _waiting()
    stream.feed(esc(escape.DECRC))

    assert not screen.pending_wrap


# ----------------------------------------------------------------------
# Giving the alternate screen back. Lillecarl/pymux#35.


@pytest.mark.parametrize(
    "mode", [PrivateMode.ALTERNATE_SCREEN, PrivateMode.ALTERNATE_SCREEN_AGAIN]
)
def test_the_older_modes_give_the_screen_back_with_the_wait(mode):
    """
    "?47" and "?1047" save no cursor, so the cursor stays where the
    program on the alternate screen left it -- and a cursor that waits
    to wrap keeps waiting. Every judge of the panel agrees, and so does
    xterm.
    """
    screen = Screen(4, COLUMNS, write_process_input=lambda data: None)
    stream = Stream(screen)
    stream.feed(set_mode(mode) + FULL_ROW)
    assert screen.pending_wrap

    stream.feed(reset_mode(mode) + "z")

    assert _where(screen, "z") == (1, 0)


def test_the_cursor_mode_gives_the_screen_back_with_the_wait():
    """
    "?1049" restores the cursor it saved on the way in, so the wait it
    brings back is the one the first screen had -- which is the wait
    the savepoint now carries.
    """
    screen, stream = _waiting()
    stream.feed(set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR))
    stream.feed(
        "z" + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) + "b"
    )

    assert _where(screen, "b") == (1, 0)
