"""
A resize lays the buffer out again and changes nothing that was in it.

This is the oracle for Lillecarl/pymux#135. That issue wants the
history to stop being laid out on every column change, and the whole
risk of it is that a deferred reflow quietly loses something. So the
property has to exist and pass on the eager reflow we have now, before
anything defers: a test that only arrives with the change it judges
proves nothing about the change.

**The invariant is width-independent, which is the point.** A reflow
unwraps every run of wrapped rows back into the line a program wrote
and lays that line out again. The line itself has no width in it, so a
column change may not touch it. `logical_lines` reads exactly that, and
it is the same function `_reflow` builds and throws away, and the same
one that Lillecarl/pymux#135 would keep.

What it is not: a round trip. `_reflow` trims the erased cells off the
end of a line on purpose (Lillecarl/pymux#56), so a buffer is not equal
to itself across a resize. The content is.

**The alternate screen is outside this, and it has to be.** It does not
reflow at all: a resize cuts it down and the cells that no longer fit
are gone, which is what five of the seven judges of the panel do and
what Lillecarl/pymux#192 landed. Losing content is the whole of that
trade, so a property saying a resize loses none cannot describe it. The
generated chunks can turn the alternate screen on, so the two property
tests below say `assume` and leave those examples to
`ptterm/tests/test_the_alternate_screen_reflow.py`.

**The very first resize counts.** These held the lines from after one
resize for a while, because a reflow read the cell the cursor stood on
and the read made it, so a cursor parked past the end of a line gave
that line a blank nobody wrote. The cursor travels as an offset now
and no read makes a cell, so the lines after the first resize are the
lines before it. Lillecarl/pymux#143.
"""

from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from a_screen import a_screen
from pyte.cells import PLAIN_APPEARANCE, WrittenCell
from pyte.streams import Stream

from test_row_versions import a_chunk
from pyte import escape
from pyte.sequences import esc
from pyte.sequences import Csi, csi


def _trimmed(cells):
    """
    One line without the blanks an erase left at the end of it.

    `_reflow` does this so that a line which was never filled does not
    carry its width around (Lillecarl/pymux#56). The test is the class
    and not the character: a space that a program drew is a
    `WrittenCell` and stays.

    It trims all the way to nothing, where `_reflow` stops at one cell.
    That last cell is there for `max_y` and not for a reader: a row of
    blanks and a row that is absent both draw as blanks, so a content
    oracle has to read them the same way. `_reflow` also materialises
    the cell the cursor stands on, which is the same thing again.
    """
    end = len(cells)
    while (
        end > 0
        and not isinstance(cells[end - 1], WrittenCell)
        and cells[end - 1].appearance == PLAIN_APPEARANCE
    ):
        end -= 1
    return cells[:end]


def logical_lines(screen):
    """
    What the buffer holds, as the lines a program wrote.

    A run of rows that a wrap made is one line. The width is gone from
    the answer, so a resize may not change it.

    **Nothing here writes.** `data_buffer` is a defaultdict, so asking
    it about a row makes one, and a row made below `history_floor` is a
    row that came back from the dead (Lillecarl/pymux#134). Every read
    goes through `.get`.
    """
    data_buffer = screen.page.data_buffer
    if not data_buffer:
        return ()

    lines = []
    cells = []

    for number in range(min(data_buffer), max(data_buffer) + 1):
        row = data_buffer.get(number)

        # An absent row is a row of blanks, and a row of blanks is not
        # a wrap, so it ends the line before it.
        if row is None or not row.wrapped:
            lines.append(_trimmed(cells))
            cells = []

        if row:
            for column in range(max(row) + 1):
                cells.append(row[column])

    lines.append(_trimmed(cells))

    # **A line that trimmed to nothing is dropped, wherever it sits.**
    # A row of blanks and a row the buffer never held draw the same,
    # so a content oracle has to read them the same way, which is what
    # `_trimmed` says above. Counting an empty line in the middle and
    # not an absent one breaks that promise, and a resize that
    # materialises a row nobody wrote then reads as lost content.
    #
    # "CSI 0 T" is what found it: a scroll down puts a blank row in
    # the region, the buffer leaves that row absent, and a reflow
    # makes it. Lillecarl/pymux#179 holds the part this oracle cannot
    # judge.
    lines = [line for line in lines if line]

    return tuple(
        tuple((cell.char, cell.appearance) for cell in cells) for cells in lines
    )


#: The widths to resize through. Narrower than the screen so a line
#: wraps, and wider so the rows a wrap made join up again.
WIDTHS = st.lists(st.integers(4, 24), min_size=1, max_size=4)


def test_a_cursor_waiting_to_wrap_invents_no_blank():
    """
    The example that said a reflow was making cells.

    Four "text"s fill a row and start a second, a reverse index takes
    the cursor back to the first, and a fifth "text" fills it. The
    cursor waits to wrap: it stands at column ten of a ten column row,
    on no character at all.

    `_reflow` read that place to know what the cursor stood on, the
    buffer made the cell, and the line came out of the resize one
    space longer. Lillecarl/pymux#143.
    """
    screen = a_screen(columns=10, lines=6)
    Stream(screen).feed("text" * 4 + esc(escape.RI) + "text")

    before = logical_lines(screen)
    screen.resize(6, 4)

    assert logical_lines(screen) == before


@given(st.lists(a_chunk(), min_size=1, max_size=40), WIDTHS)
@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_a_column_change_keeps_every_line(chunks, widths):
    """
    Feed a screen, then resize it through several widths with nothing
    written in between. The lines are the same after each one.
    """
    screen = a_screen(columns=10, lines=6)
    Stream(screen).feed("".join(chunks))
    assume(not screen.in_alternate_screen)

    before = logical_lines(screen)
    for width in widths:
        screen.resize(screen.lines, width)
        assert logical_lines(screen) == before


#: The sizes to resize through, height as well as width. A shorter
#: screen is the case that a width alone never reaches: the reflow
#: looks for the top of the buffer at the last row of the screen, and
#: a smaller height moves that row down past rows the buffer holds.
#: Lillecarl/pymux#145.
SIZES = st.lists(
    st.tuples(st.integers(1, 12), st.integers(4, 24)), min_size=1, max_size=4
)


@given(st.lists(a_chunk(), min_size=1, max_size=40), SIZES)
@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
# The corpus, and today it holds one.
#
# **A drawn example is not remembered.** The gate draws the same
# examples every run now (Lillecarl/pymux#180), which is what makes it
# a gate, and it also means a case outside that draw is a case nobody
# sees again. A database would not help: a nix sandbox throws its
# `.hypothesis` directory away. So an example that once failed is
# written down here, where both profiles run it and a reader can see
# what it is.
#
# This one is a scroll down inside a region. The buffer leaves the
# blank row it made absent, a reflow makes the row, and the resize
# reads as a line that was not there before. It failed about one run
# in eight. Lillecarl/pymux#179 holds the part of it that is still
# open: the oracle stopped counting a blank line, and the two ends
# still do not agree about whether the row is real.
@example(
    chunks=["wider text that wraps around the end of a short row\n" + csi(Csi.SD, 0)],
    sizes=[(1, 4)],
)
def test_a_size_change_keeps_every_line(chunks, sizes):
    """
    The same through several heights as well as several widths.

    A screen that has not filled up holds rows below `max_y`: DECALN
    writes every row of a fresh screen and leaves `max_y` at 0. Making
    that screen shorter left the rows under the new bottom laid out at
    the old width, above the ones the reflow wrote.
    """
    screen = a_screen(columns=10, lines=6)
    Stream(screen).feed("".join(chunks))

    before = logical_lines(screen)
    for lines, columns in sizes:
        screen.resize(lines, columns)
        assert logical_lines(screen) == before


@given(st.lists(a_chunk(), min_size=1, max_size=40), WIDTHS)
@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_a_column_change_keeps_every_line_with_a_short_history(chunks, widths):
    """
    The same, on a pane that keeps almost no scrollback, so that rows
    leave the history while the sequence runs.
    """
    screen = a_screen(columns=10, lines=6, history=5)
    Stream(screen).feed("".join(chunks))
    assume(not screen.in_alternate_screen)

    before = logical_lines(screen)
    for width in widths:
        screen.resize(screen.lines, width)
        assert logical_lines(screen) == before
