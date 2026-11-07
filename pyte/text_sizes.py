"""
The text a program asked for at another size: kitty's text sizing
protocol, OSC 66, and the DEC line attributes, which become OSC 66.
https://sw.kovidgoyal.net/kitty/text-sizing-protocol/.
Lillecarl/pyterm#892.

**A block lies over cells that draw it at scale one.** The top row
holds the text one cell a column, cut at the block's width, and every
other cell of the block holds a space in the block's appearance. So
copy mode, a search and a terminal without the protocol all read the
text. A renderer that speaks OSC 66 draws `blocks` over those cells.

**DECDWL draws wrong in kitty.** kitty scales a glyph's width and
height by one factor (`scaled_cell_dimensions` in `kitty/fonts.c`), so
no OSC 66 stretches a glyph sideways only. A double width line becomes
"w=2": each glyph at its own size, two cells apart. A double height
line has an exact form, "s=2" on the top row, and the program's copy
on the bottom row is dropped.

The line attribute lasts while the cursor stays on that row. A program
that leaves the row and comes back writes plain text there, where a
VT100 kept the line double. Holding it longer is the row attribute
Lillecarl/pyterm#143 took out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, NamedTuple

from .cells import _CHAR_CACHE, Appearance, Cell, Rendition, appearance_of, character_width, joins
from .keep import Keep
from .sequences.escapes import Sharp
from .sequences.text_sizing import TextSize

if TYPE_CHECKING:
    from .screen import Screen

__all__ = ["DecLine", "SizedBlock", "TextSizes", "graphemes"]


def graphemes(text: str) -> list[str]:
    """
    `text` cut where plain text starts a new cell: a mark of no width
    joins the cell before it, the way kitty's `screen_handle_multicell_command`
    splits a sequence with no width.
    """
    pieces: list[str] = []
    for character in text:
        if pieces and (joins(pieces[-1], character) or character_width(character) == 0):
            pieces[-1] += character
        elif character_width(character) > 0:
            pieces.append(character)
    return pieces


class SizedBlock:
    """
    One block of text at a size: the cells from (`x`, `y`) that it
    covers, what the program sent, and how it asked for it to be drawn.

    `line` names the DEC line attribute that made it, so DECSWL can put
    the text back.
    """

    __slots__ = ("appearance", "columns", "line", "rows", "size", "x", "y")

    #: A snapshot takes the size as the OSC carried it and the look as
    #: plain values, through `sent` and `look`: it freezes neither an
    #: interned appearance nor a frozen dataclass.
    KEEP: ClassVar[dict[str, Keep]] = {
        "x": Keep.SAVED,
        "y": Keep.SAVED,
        "columns": Keep.SAVED,
        "rows": Keep.SAVED,
        "line": Keep.SAVED,
        "sent": Keep.SAVED,
        "look": Keep.SAVED,
        "size": Keep.REBUILT,
        "appearance": Keep.REBUILT,
    }

    def __init__(
        self, x: int, y: int, columns: int, rows: int, size: TextSize, appearance: Appearance, line: str = ""
    ) -> None:
        self.x = x
        self.y = y
        self.columns = columns
        self.rows = rows
        self.size = size
        self.appearance = appearance
        self.line = line

    @property
    def sent(self) -> str:
        return self.size.param()

    @sent.setter
    def sent(self, param: str) -> None:
        self.size = TextSize.decode(param)

    @property
    def look(self) -> tuple[Rendition, str, str]:
        return (self.appearance.rendition, self.appearance.hyperlink, self.appearance.hyperlink_id)

    @look.setter
    def look(self, look: tuple[Rendition, str, str]) -> None:
        self.appearance = appearance_of[look]

    def covers(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.columns and self.y <= y < self.y + self.rows

    def meets(self, top: int, bottom: int, left: int, right: int) -> bool:
        "Whether it lies on a cell of rows `top` to `bottom` and columns `left` up to `right`."
        return self.y <= bottom and top < self.y + self.rows and self.x < right and left < self.x + self.columns

    def __repr__(self) -> str:
        return "SizedBlock(%d, %d, %dx%d, %r)" % (self.x, self.y, self.columns, self.rows, self.size)


class DecLine(NamedTuple):
    "A DEC line attribute, and the row of the data buffer it holds for."

    row: int
    kind: Sharp


class TextSizes:
    """
    The blocks of one screen, and the DEC line attribute of the row the
    cursor is on.

    The alternate screen has its own, as it has its own images.
    """

    __slots__ = ("blocks", "dec_line", "drawing", "held")

    #: `held` is cells outside any row, which `freeze` cannot carry, and
    #: a hot upgrade loses only the right half of a line nobody sees.
    KEEP: ClassVar[dict[str, Keep]] = {
        "blocks": Keep.SAVED,
        "dec_line": Keep.SAVED,
        "drawing": Keep.SAVED,
        "held": Keep.DROPPED,
    }

    def __init__(self) -> None:
        self.blocks: list[SizedBlock] = []
        self.dec_line: DecLine | None = None
        #: The cells past the half of each DEC double row, by row and
        #: column, which DECSWL gives back. A VT100 and xterm keep them,
        #: and vttest calls losing them a misfeature; of the panel only
        #: libvterm drops them. Lillecarl/pyterm#374.
        self.held: dict[int, dict[int, Cell]] = {}
        #: Set while `Screen.draw` draws one character for the blocks,
        #: so that it takes the plain path.
        self.drawing = False

    def after_thaw(self) -> None:
        self.held = {}

    def block_at(self, x: int, y: int) -> SizedBlock | None:
        for block in self.blocks:
            if block.covers(x, y):
                return block
        return None

    def put(self, screen: Screen, block: SizedBlock) -> None:
        "Lay `block` on its cells, over whatever was there."
        for other in [
            other
            for other in self.blocks
            if other.meets(block.y, block.y + block.rows - 1, block.x, block.x + block.columns)
        ]:
            self.remove(screen, other)
        data_buffer = screen.page.data_buffer
        space = _CHAR_CACHE[" ", block.appearance]
        for row in range(block.y, block.y + block.rows):
            line = data_buffer[row]
            for column in range(block.x, block.x + block.columns):
                line[column] = space
        top = data_buffer[block.y]
        column, end = block.x, block.x + block.columns
        for piece in graphemes(block.size.text):
            width = character_width(piece)
            if column + width > end:
                break
            top[column] = _CHAR_CACHE[piece, block.appearance]
            if width > 1:
                top[column + 1] = _CHAR_CACHE["", block.appearance]
                screen._wide_chars = True
            column += width
        screen.repair_wide_char(top, block.x)
        screen.repair_wide_char(top, end)
        self.blocks.append(block)
        screen.touch_rows(range(block.y, block.y + block.rows))

    def remove(self, screen: Screen, block: SizedBlock, spaces: bool = False) -> None:
        """
        Take `block` away, and its cells with it: blank, or spaces in
        its appearance, which is what kitty leaves when text lands on
        the top row anywhere but the first cell.
        """
        self.blocks.remove(block)
        data_buffer = screen.page.data_buffer
        space = _CHAR_CACHE[" ", block.appearance]
        for row in range(block.y, block.y + block.rows):
            line = data_buffer.get(row)
            if line is None:
                continue
            for column in range(block.x, block.x + block.columns):
                if spaces:
                    line[column] = space
                else:
                    line.pop(column, None)
            screen.repair_wide_char(line, block.x)
            screen.repair_wide_char(line, block.x + block.columns)
        screen.touch_rows(range(block.y, block.y + block.rows))

    def cover(self, screen: Screen, top: int, bottom: int, left: int, right: int) -> None:
        """
        An erase took the cells of rows `top` to `bottom`, columns `left`
        up to `right`: every block there goes. An erase to the end of a
        double row reaches its held cells too, from the column under
        `left` on.
        """
        for block in [block for block in self.blocks if block.meets(top, bottom, left, right)]:
            self.remove(screen, block)
        if right < screen.columns:
            return
        for row in [row for row in self.held if top <= row <= bottom]:
            kept = {column: cell for column, cell in self.held[row].items() if column < left // 2}
            if kept:
                self.held[row] = kept
            else:
                del self.held[row]

    def shift(self, screen: Screen, row: int, column: int, count: int, end: int) -> None:
        """
        ICH (`count` above zero) or DCH (below) moved the cells of `row`
        from `column` up to `end`. A block of one row moves with them,
        and one that the edit splits or that the edge cuts goes. A block
        of more rows anywhere from `column` on goes, as the spec says.
        The held cells of the row go as well.
        """
        self.held.pop(row, None)
        for block in list(self.blocks):
            if not block.meets(row, row, column, end):
                continue
            if block.rows > 1:
                self.remove(screen, block)
            elif count > 0:
                if block.x < column or block.x + block.columns + count > end:
                    self.remove(screen, block)
                else:
                    block.x += count
            elif block.x < column - count:
                self.remove(screen, block)
            else:
                block.x += count

    def scroll(self, first_row: int, last_row: int, count: int) -> None:
        """
        Follow a scroll of the rows from `first_row` to `last_row`, both
        included. A positive `count` moves the text up. A block that
        crosses the edge of the region, or that the scroll takes out of
        it, goes; its cells moved with the rest and keep the text.
        """
        if self.dec_line is not None and first_row <= self.dec_line.row <= last_row:
            self.dec_line = None
        kept: list[SizedBlock] = []
        for block in self.blocks:
            top, bottom = block.y, block.y + block.rows - 1
            if bottom < first_row or top > last_row:
                kept.append(block)
                continue
            if top < first_row or bottom > last_row:
                continue
            block.y -= count
            if block.y >= first_row and block.y + block.rows - 1 <= last_row:
                kept.append(block)
        self.blocks = kept
        held: dict[int, dict[int, Cell]] = {}
        for row, cells in self.held.items():
            if not first_row <= row <= last_row:
                held[row] = cells
            elif first_row <= row - count <= last_row:
                held[row - count] = cells
        self.held = held

    def prune_above(self, row: int) -> None:
        "The history lost the rows above `row`."
        self.blocks = [block for block in self.blocks if block.y + block.rows > row]
        self.held = {kept: cells for kept, cells in self.held.items() if kept >= row}

    def prune_below(self, row: int) -> None:
        "The rows below `row` went."
        self.blocks = [block for block in self.blocks if block.y + block.rows - 1 <= row]
        self.held = {kept: cells for kept, cells in self.held.items() if kept <= row}

    def clear(self) -> None:
        self.blocks = []
        self.dec_line = None
        self.held = {}
