"""
What holds the cells: a row, a page, and where you are in one.

`cells.py` says what one cell is. This says what a screen is made of
above the cell: a row of them, a page of rows, the region a scroll
moves, and the place the cursor stands.

None of it decides anything. `screen.py` reads a sequence and writes
here. What reads it back is a front end drawing a frame —
`_TerminalControl.create_content` in ptterm and `Terminal.render_line`
in txterm — and copy mode, which walks the whole buffer.
Lillecarl/pymux#129.
"""
from collections import defaultdict, namedtuple
from enum import IntEnum
from typing import DefaultDict, List, NamedTuple, Tuple

from .cells import Cell

__all__ = (
    "CursorPosition",
    "DoubleHeight",
    "HorizontalMargins",
    "LineAttribute",
    "LogicalLine",
    "Margins",
    "PLAIN_LINE",
    "Page",
    "Row",
    "TextLine",
)


class Margins(NamedTuple):
    """
    The first and the last row of the scrolling region, counted from
    zero. DECSTBM ("CSI Pt ; Pb r") names them.

    It was `pyte.screens.Margins`, and it is the one thing the old
    screen left behind that this one still needs.
    """

    top: int
    bottom: int


#: The first and the last column of the scrolling region, counted from
#: zero. DECSLRM ("CSI Pl ; Pr s") names them. `Margins` names the first
#: and the last row, and this is the other pair.
HorizontalMargins = namedtuple("HorizontalMargins", "left right")


class CursorPosition:
    "Mutable CursorPosition."

    def __init__(self, x: int = 0, y: int = 0) -> None:
        self.x = x
        self.y = y

    def __repr__(self) -> str:
        return f"pymux.CursorPosition(x={self.x!r}, y={self.y!r})"


class DoubleHeight(IntEnum):
    "Which half of a double height line a line is."

    NONE = 0
    TOP = 1
    BOTTOM = 2


class LineAttribute(NamedTuple):
    """
    The DEC line attributes of one line.

    A VT100 draws a line at twice the width, at twice the height, or
    both. The attribute belongs to the line and not to a cell, so it
    lives on the `Row` and not in a `Cell`.

    ptterm holds it and draws nothing: how wide a line looks is the
    renderer's decision, and a pane is not a whole line of the terminal
    the user runs. The line still holds every column it held, which is
    what kitty, WezTerm, Alacritty, Ghostty and xterm.js all do.
    libvterm alone halves the line, and `test_the_panel.py` holds that
    vote. Lillecarl/pymux#55.
    """

    double_width: bool
    double_height: DoubleHeight


#: A line that carries no attribute. It is never stored: a row that
#: holds it is absent from the map.
PLAIN_LINE = LineAttribute(False, DoubleHeight.NONE)


class Row(DefaultDict[int, Cell]):
    """
    One row of the buffer: its cells, and what is true of the row
    itself rather than of any cell in it.

    **A note about a row lives on the row.** Both of these used to be
    dictionaries of their own, keyed by the row number. Two containers
    that have to be kept in step by hand are two containers that go out
    of step: a row that left the history took its cells and left both
    notes behind, so they grew with the session; `_reflow` had to
    rebuild both to match the new numbering; and `_move_rows` moved the
    cells and left the wrap mark where it was. None of that can happen
    to something the row carries. Lillecarl/pymux#134.

    Every terminal that was read for Lillecarl/pymux#135 does the same:
    Alacritty and kitty put the wrap mark on the last cell of the row,
    WezTerm and Ghostty on the row.

    A cell that nobody wrote is absent, so an untouched row costs one
    dictionary and the default answers for every column.
    """

    __slots__ = ("wrapped", "attribute")

    def __init__(self, default_char: Cell) -> None:
        super().__init__(lambda: default_char)

        #: Did a wrap bring this row into being? Then it holds the rest
        #: of the row above and is not a line of its own, and a reflow
        #: joins the two back together before it lays them out again.
        self.wrapped: bool = False

        #: The DEC line attribute of this row: twice as wide, or the
        #: top or the bottom half of twice as high. `None` is a plain
        #: row, which is nearly all of them.
        self.attribute: LineAttribute | None = None


class LogicalLine:
    """
    One line as a program wrote it: the cells between one newline and
    the next, and what is true of the line rather than of a cell in it.

    **There is no width in it.** A `Row` is a line cut to fit a screen,
    and this is the line before the cut. That is the whole difference:
    a column change decides where a line breaks and cannot touch what
    the line holds.

    `Screen._reflow` builds one of these for every line of the buffer,
    lays them out at the new width, and throws them away. Keeping them
    instead is Lillecarl/pymux#135, and this is the type that would be
    kept.

    The attribute comes from the row the line starts on, because that
    is the row the program addressed when it sent "ESC # 6".
    """

    __slots__ = ("cells", "attribute")

    def __init__(self, attribute: "LineAttribute | None" = None) -> None:
        self.cells: List[Cell] = []

        #: The DEC line attribute of this line, or `None` for a plain
        #: one, which is nearly all of them.
        self.attribute = attribute

    def __repr__(self) -> str:
        return "LogicalLine(%r, %r)" % (
            "".join(cell.char for cell in self.cells),
            self.attribute,
        )


class TextLine(NamedTuple):
    """
    One line of the buffer as text, and the rows it is laid out on.

    `Page.text_lines` gives these. The rows are there so that a reader
    which shows the text can ask `Page.unwrap` for the cells of one
    line when somebody looks at it.
    """

    text: str

    #: The first and the last row the line takes, both inside it.
    first: int
    last: int


class Page:
    """
    One screen of cells, and whether the cursor shows on it.

    A terminal holds two of these. `set_mode` puts the first one away
    and takes the alternate screen, and `reset_mode` gives it back, so
    the two things that belong to a screen rather than to the terminal
    live together in one object that a swap can carry.

    This was `prompt_toolkit.layout.screen.Screen`. A pane never used
    the rest of that class: the floats, the menu positions, the windows
    and the write positions all belong to a program that draws an
    interface, and a pane draws what another program wrote. Holding
    them here tied the screen to one toolkit for nothing.
    Lillecarl/pymux#11.
    """

    __slots__ = ("data_buffer", "show_cursor")

    def __init__(self, default_char: Cell) -> None:
        #: The cells, by row and then by column. A row that nobody
        #: wrote to is absent, and so is a column, so the cost of an
        #: empty screen is one dictionary.
        self.data_buffer: DefaultDict[int, Row] = defaultdict(
            lambda: Row(default_char)
        )

        #: Does the cursor show? DECTCEM ("?25") sets it, and it belongs
        #: to the screen in front, so the alternate screen has its own.
        self.show_cursor = True

    def wrapped(self, row: int) -> bool:
        """
        Did a wrap bring this row into being?

        `.get` and not `[]`: the buffer makes a row for a number it does
        not hold, and a row made below the floor of the history is a row
        that came back from the dead. Lillecarl/pymux#134.
        """
        line = self.data_buffer.get(row)
        return line is not None and line.wrapped

    def text_lines(self, first: int, last: int) -> "List[TextLine]":
        """
        The lines the range holds, as text and as the rows each one
        is laid out on.

        **It carries no cell.** A reader that shows text and wants the
        cells of one line only when somebody looks at it asks this, and
        then `unwrap` for the rows of that one line. Copy mode does
        that: it opens on fifty thousand rows and shows a screenful,
        and it pays for the text of all of them because a `Document`
        holds one string. Lillecarl/pymux#131.

        The rows come with the text and not in a list beside it. Two
        containers that a caller has to keep in step are two containers
        that go out of step. Lillecarl/pymux#134.

        Nothing here writes, and a row the buffer does not hold gives
        no characters.
        """
        if first > last:
            return []

        lines = []
        text = ""
        start = first
        data_buffer = self.data_buffer

        for number in range(first, last + 1):
            row = data_buffer.get(number)

            # A row that no wrap made starts a line, which ends the one
            # before it. The first row of the range starts the first
            # line whether a wrap made it or not: the caller asked for
            # these rows, so a line it cuts into arrives cut.
            if number != first and not (row is not None and row.wrapped):
                lines.append(TextLine(text, start, number - 1))
                text = ""
                start = number

            if row:
                # One join per row and not one per line: nearly every
                # line is one row, and a second join over a list of one
                # cost a third of the whole read. A line that spans
                # rows adds to the string, which CPython does in place.
                text += "".join(
                    row[column].char for column in range(max(row) + 1)
                )

        lines.append(TextLine(text, start, last))
        return lines

    def unwrap(
        self, first: int, last: int, cursor: "Tuple[int, int] | None" = None
    ) -> "Tuple[List[LogicalLine], Tuple[int, int] | None]":
        """
        The rows from `first` to `last` as the lines a program wrote.

        A run of rows joined by the wrap mark is one line, and a line
        carries no width. That is what makes laying one out again all
        that a column change has to do, and it is why the answer can be
        kept: Lillecarl/pymux#135.

        `cursor` is a row and a column to follow through the unwrapping.
        The answer says where it landed, as a line and an offset in it,
        or `None` when it was not in the range.

        The range is a range and not the whole buffer, because the whole
        buffer is what a reflow costs today. A caller that wants only
        the rows on the screen asks for those.

        Nothing here writes. A row the buffer does not hold contributes
        no cells and ends the line before it, which is the same thing a
        row of blanks does.

        The answer holds one line for every line the range starts, and
        nothing after them.
        """
        lines: List[LogicalLine] = []
        line: "LogicalLine | None" = None
        cells: List[Cell] = []
        found = None

        # The cursor as two numbers, because the loop below runs once
        # per cell of the range and building a tuple to compare there
        # cost ten percent of a reflow. A row of -1 matches nothing.
        cursor_row, cursor_column = cursor if cursor is not None else (-1, -1)

        data_buffer = self.data_buffer
        for number in range(first, last + 1):
            if line is None:
                # A row starts the line, and the end of a line does not.
                # Making the next one at the end of this one leaves an
                # empty line after the last row, which `_reflow` lays
                # out as nothing but a reader prints as a blank line.
                line = LogicalLine()
                lines.append(line)
                cells = line.cells

            row = data_buffer.get(number)

            if row is not None:
                if not row.wrapped:
                    line.attribute = row.attribute

                # `default` answers an empty row without writing to it.
                for column in range(0, max(row, default=-1) + 1):
                    if number == cursor_row and column == cursor_column:
                        found = (len(lines) - 1, len(cells))
                    cells.append(row[column])

            if not self.wrapped(number + 1):
                line = None

        return lines, found
