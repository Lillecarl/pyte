"""
A resize reaches the page nobody is looking at. Lillecarl/pymux#203.

A switch to the alternate screen stashes the first page and puts it
back on the way out. A resize laid out `self.page`, which is the one a
person sees, so the other one came back at the width it was stashed at:
a row of 31 cells on a screen 20 columns wide.

It is the ordinary case and not a corner. A person resizes the window
while `vim` is up, and quits it.

Both reference implementations lay out both buffers on every resize:
libvterm's `resize()` calls `resize_buffer` for buffer 0 and buffer 1
whichever is active, and kitty's `rewrap()` hands `main_linebuf` and
`alt_linebuf` to their own resizers together.
"""

import pyte
from a_screen import a_screen
from pyte.modes import PrivateMode
from pyte.sequences import reset_mode, set_mode

WIDE = 32
NARROW = 20
LINES = 8

ALTERNATE = set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
BACK = reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)


def a_screen_and_stream(columns=WIDE, lines=LINES):
    screen = a_screen(columns, lines)
    return screen, pyte.Stream(screen)


def widths(screen):
    "How many cells each row of the page holds."
    return {row: len(screen.page.data_buffer[row]) for row in screen.page.data_buffer}


def rows(screen):
    "Every row of the page, as strings."
    buffer = screen.page.data_buffer
    return [
        "".join(cell.char or " " for cell in buffer[row].values()).rstrip()
        for row in sorted(buffer)
    ]


# ----------------------------------------------------------------------
# The first page, stashed while a full-screen program runs.


def test_the_first_page_comes_back_laid_out_at_the_new_width():
    """
    The reported case. A line that filled a wide screen has to take two
    rows on a narrow one, and it used to come back as one row of 31
    cells that no reader could place.
    """
    screen, stream = a_screen_and_stream()
    screen.draw("A" * (WIDE - 1))

    stream.feed(ALTERNATE)
    screen.resize(columns=NARROW)
    stream.feed(BACK)

    assert max(widths(screen).values()) <= NARROW, widths(screen)
    assert rows(screen)[:2] == ["A" * NARROW, "A" * (WIDE - 1 - NARROW)], rows(screen)


def test_the_first_page_keeps_its_content_across_the_resize():
    "A reflow moves the characters and loses none of them."
    screen, stream = a_screen_and_stream()
    screen.draw("A" * (WIDE - 1))

    stream.feed(ALTERNATE)
    screen.resize(columns=NARROW)
    stream.feed(BACK)

    assert "".join(rows(screen)).rstrip() == "A" * (WIDE - 1)


def test_a_widening_puts_the_line_back_together():
    "The other direction, so the join is exercised too."
    screen, stream = a_screen_and_stream(columns=NARROW)
    screen.draw("A" * (NARROW + 5))

    stream.feed(ALTERNATE)
    screen.resize(columns=WIDE)
    stream.feed(BACK)

    assert rows(screen)[0] == "A" * (NARROW + 5), rows(screen)


# ----------------------------------------------------------------------
# The alternate page, stashed after the program that drew it stops.
#
# "?47" and "?1047" find what the last visit left, so that page has to
# be the right size as well. It is cut down rather than laid out again,
# the way the alternate screen always is. Lillecarl/pymux#192.


def test_the_alternate_page_is_cut_down_while_it_is_stashed():
    screen, stream = a_screen_and_stream()

    stream.feed(ALTERNATE)
    screen.draw("B" * (WIDE - 1))
    stream.feed(BACK)

    screen.resize(columns=NARROW)

    stream.feed(set_mode(PrivateMode.ALTERNATE_SCREEN_AGAIN))
    assert rows(screen)[0] == "B" * NARROW, rows(screen)


# ----------------------------------------------------------------------
# What the stash may not lose.


def test_the_page_that_is_showing_is_not_disturbed():
    """
    Laying out the stashed page stands on it, so the fields of the page
    that is showing have to be exactly as they were afterwards.
    """
    screen, stream = a_screen_and_stream()
    screen.draw("A" * (WIDE - 1))

    stream.feed(ALTERNATE)
    screen.draw("B" * (WIDE - 1))
    screen.resize(columns=NARROW)

    # The alternate screen is cut down, so its one row is cut to 20.
    assert rows(screen)[0] == "B" * NARROW, rows(screen)
    assert screen.page is not screen._original_screen


def test_a_resize_before_the_alternate_screen_still_works():
    "There is nothing stashed yet, and nothing to lay out."
    screen, _ = a_screen_and_stream()
    screen.draw("A" * (WIDE - 1))

    screen.resize(columns=NARROW)

    assert rows(screen)[:2] == ["A" * NARROW, "A" * (WIDE - 1 - NARROW)], rows(screen)
