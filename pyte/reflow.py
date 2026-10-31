"""
The arithmetic of laying a buffer out again at a new width.

It lays out the screen and the lines that reach it, and leaves the
history where it is. A reader of the history reads lines and not rows,
so the width those rows were laid out at never reaches it.
Lillecarl/pymux#135.

These read and write the rows and nothing else. Moving the cursor,
`max_y` and the floors is the screen's: `Screen._reflow`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from .cells import PLAIN_APPEARANCE, WrittenCell
from .page import LogicalLine, Row

__all__ = ["first_row_to_lay_out", "highest_row_held", "lay_out"]


def highest_row_held(data_buffer: Mapping[int, Row], bottom: int, lines: int) -> int:
    """
    The highest row number the buffer holds. It holds one.

    `bottom` is the last row of the screen those rows were written
    into, and `lines` the height of that screen. **A resize has to read
    it before it changes the height**, because the search below starts
    there and the new height moves it. A shorter screen moved it down
    past rows of the buffer, and the search stopped at the first row
    under the new bottom: six rows of DECALN turned into three that a
    resize laid out again and three that kept the old width above them.

    **Not `Screen.highest_row`.** That one answers `max_y` at the least,
    because a front end draws every row of the screen. This one answers
    the buffer, which can stop below `max_y`: the cursor moves down
    without writing, and an erase drops the rows it clears. A reflow
    that starts above the buffer counts the absent rows as blank lines,
    stops higher up than it should, and leaves real rows at the old
    width. `tests/test_reflow_bounds.py` catches it.

    **It looks down instead of reading every key.** No row of the
    buffer sits above `bottom`, and `tests/test_the_top_of_the_buffer.py`
    is the proof of that bound. So the first row the search meets going
    down is the answer, whatever the search stops at.

    **The last row of the screen, and not `max_y`.** `max_y` is the
    highest row that was ever written, and a screen that has not filled
    up yet reaches further down than that: DECALN writes every row of a
    fresh screen and leaves `max_y` at 0.

    The search gives up after the rows of one screen, and `max` answers
    what is left. A screen a program cleared holds no row at all, and
    the gap down to the last row of the history is as deep as the
    history. That fall back costs what this cost before: `max` walks
    every key, which at fifty thousand rows is 392 microseconds of a
    resize that takes 1,200. Lillecarl/pymux#145.
    """
    for number in range(bottom, bottom - lines, -1):
        if number in data_buffer:
            return number

    return max(data_buffer)


def first_row_to_lay_out(data_buffer: Mapping[int, Row], last: int, wanted: int, lines: int, floor: int) -> int:
    """
    The first row a reflow has to lay out again.

    It walks up from `last` and stops at the first row of a line, once
    three things are true: it holds a line for every one of the `lines`
    rows of the screen, it has reached `wanted` (the top of the screen
    or the cursor, whichever is higher up), and so it has reached both.

    **A line for every row is enough at any width.** A line takes at
    least one row however wide the screen becomes, so `lines` of them
    always fill it. Widening takes rows away from a line and never takes
    the line away.

    The other two say what a reflow may not leave behind. A row of the
    screen that keeps its old layout is a row a person sees at the wrong
    width, and the cursor has to travel with the character it stands on.

    It stops at the lowest row the buffer holds at the latest. **Not at
    `floor`** (the history floor), which only says that nothing lives
    under it: the buffer can start above the floor, and a reflow that
    laid out from under the lowest row would write the rows out one
    number too low and move the whole buffer down.

    It learns that row on the way rather than asking `min` for it. The
    walk passes every row between `last` and the floor, so it has seen
    the lowest one by the time it gets there, and asking `min` would
    read every key of the buffer to find a number that only matters when
    the walk runs all the way down. Lillecarl/pymux#145.
    """
    collected = 0
    lowest = last
    for number in range(last, floor - 1, -1):
        row = data_buffer.get(number)

        if row is not None:
            lowest = number

            # A row a wrap made is the middle of a line, and a line
            # is taken whole. A row the buffer does not hold is a
            # blank line, and a blank line starts one.
            if row.wrapped:
                continue

        collected += 1
        if collected >= lines and number <= wanted:
            # `lowest` and not `number`: the walk goes down to the
            # floor, and the floor only says that nothing lives
            # under it. Every row between the two is a row the
            # buffer does not hold, and laying out from under the
            # lowest row it holds writes every row one number too
            # low. `lowest` is `number` itself on a row that is
            # there.
            return lowest

    return lowest


def lay_out(
    data_buffer: defaultdict[int, Row],
    lines: list[LogicalLine],
    first: int,
    last: int,
    width: int,
    cursor: tuple[int, int],
) -> tuple[int, tuple[int, int] | None]:
    """
    Write `lines` over the rows `first` to `last` at `width` columns.

    `cursor` is where the cursor stands as a line and an offset into it,
    the way `Page.unwrap` finds it. Answers the highest row written and
    the row and column the cursor lands on, or None when no line held it.
    """
    cy, cx = cursor

    # Take the blanks off the end of each line, so that a line that
    # was never filled does not carry its width around. Not a blank
    # a background was painted on.
    #
    # A blank that a program wrote is content, and it stays. The
    # test is the class and not the character: a space out of
    # `draw` is a `WrittenCell`, and the blank that an erase leaves
    # is not. Reading the character instead lost the space after a
    # shell prompt on every resize. Lillecarl/pymux#56.
    #
    # Also make sure that lines consist of at lesat one character,
    # otherwise we can't calculate `max_y` correctly. (This is important
    # for the `clear` command.)
    #
    # The cursor needs nothing held back here. It travels as an
    # offset from the start of its line, and an offset past the
    # end of one is where it stands on a full row or on a row a
    # program moved onto and did not write. Lillecarl/pymux#143.
    for line in lines:
        cells = line.cells
        while len(cells) > 1 and not isinstance(cells[-1], WrittenCell) and cells[-1].appearance == PLAIN_APPEARANCE:
            cells.pop()

    # The rows the lines came from go, and the lines take their
    # place. They go first: a wider screen needs fewer rows for the
    # same lines, and a row of the old layout left under the new
    # ones would come back as soon as `max_y` grew again.
    for number in range(first, last + 1):
        data_buffer.pop(number, None)

    # Wrap lines again according to the screen width.
    new_row_index = first
    new_column_index = 0

    #: The highest row this writes on. It is `max_y` at the end,
    #: and it is counted here because reading it back is
    #: `max(data_buffer)`, which walks the history that a reflow
    #: exists to leave alone.
    highest = first - 1

    # Where the cursor lands, kept apart from where it stood.
    #
    # The loop wrote the answer back into `cy` and `cx`, so the
    # line and the offset the cursor came from and the row and the
    # column it went to were the same two numbers. A later line
    # then matched the answer and moved the cursor again. Four
    # characters, one "CSI T" and a narrowing was enough: the
    # cursor landed a row low, on the "t" of "text" instead of on
    # the blank it stood on, and the check at the end of
    # `Screen._reflow` raised. Lillecarl/pymux#110.
    new_cursor_position = None

    for line_index, line in enumerate(lines):
        # The row being written, held rather than looked up per cell:
        # this loop is the cost of a resize, and ptterm's
        # `tests/instruction-budgets.txt` counts it. Only a line with
        # cells takes one, because looking a row up makes it.
        if line.cells:
            row = data_buffer[new_row_index]
        if line.marks:
            # On the first row of the line, where a prompt starts.
            data_buffer[new_row_index].marks = line.marks

        for column_index, char in enumerate(line.cells):
            char_width = char.width

            # **The empty second half of a double width character goes
            # in the second of the two cells its character took**, and
            # not at the next free one: it is zero wide, so the next
            # character landed on it and took its place, and every
            # wide character came out of a resize followed by a blank
            # (Lillecarl/pymux#548's pictures). A half whose
            # character is not there is dropped, as an edit drops it.
            if not char_width and char.char == "":
                before = row.get(new_column_index - 2)
                if before is not None and before.width > 1:
                    row[new_column_index - 1] = char
                    if cy == line_index and cx == column_index:
                        new_cursor_position = (new_row_index, new_column_index - 1)
                continue

            # Check for space on the current line.
            if new_column_index + char_width > width:
                new_row_index += 1
                new_column_index = 0
                row = data_buffer[new_row_index]
                row.wrapped = True

            if cy == line_index and cx == column_index:
                new_cursor_position = (new_row_index, new_column_index)

            # Add character to new buffer.
            row[new_column_index] = char
            new_column_index += char_width
            highest = new_row_index

        # A cursor that stands past the end of its line lands the
        # same distance past the last cell of it, wrapping the way
        # a character would. No cell in the loop above matched it,
        # because there is no cell there. Lillecarl/pymux#143.
        if cy == line_index and cx >= len(line.cells):
            cursor_row = new_row_index
            cursor_column = new_column_index + cx - len(line.cells)
            while cursor_column >= width:
                cursor_column -= width
                cursor_row += 1
            new_cursor_position = (cursor_row, cursor_column)

        new_row_index += 1
        new_column_index = 0

    return highest, new_cursor_position
