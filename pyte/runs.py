"""
The text runs of one row: what a front end draws it with.

A row is a sparse map of cells, and a front end draws runs: a run of
cells that draw the same way is one piece of text in one style.
`txterm` already coalesces its own segments per run; `ptterm` paid
per cell for what only changes per run, and now maps these runs
straight onto fragments. This builds them once, where the cells
live.

A run is `start` and `end` columns, the text between them, and what
every cell of it draws with: the appearance, and whether a program
wrote it. Two neighbours join when both agree and the text draws as
it stands; anything else -- a wide character's two columns, a
control, a cell of an image -- stands on its own, one cell per run.
A gap between two runs holds cells nobody wrote, so a front end pads
it with blanks and reads nothing here for it.

`plain` says the text reaches the screen as it stands. A front end
that maps control characters and image placeholders to blanks does
that mapping per cell today; for a plain run there is nothing to map,
so it joins the style once and hands the whole text over. An exotic
run carries one cell, and the front end maps it the way it always
did.

`blank` says every character is a space. A blank a program wrote
keeps its trailing column where an erased one does not, so a front
end that trims trailing blanks asks this of the last run; anywhere
else the style is the same with or without it, because the mark
changes no attribute, only the measurement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .cells import Appearance
from .placeholders import PLACEHOLDER

if TYPE_CHECKING:
    from .page import Row

__all__ = [
    "Run",
    "runs_of",
]


class Run(NamedTuple):
    """
    Neighbouring cells of one row that draw the same way.

    `start` is the first column and `end` one past the last one the
    text covers; a double width character covers two. `text` is the
    characters in order, `appearance` what draws them, and `written`
    whether a program put them there. `plain` says the text draws as
    it stands, and `blank` says it is all spaces.
    """

    start: int
    end: int
    text: str
    appearance: Appearance
    written: bool
    plain: bool
    blank: bool


def runs_of(row: Row) -> list[Run]:
    """
    The runs of one row, by column.

    The cells come out sorted, because a row is written in cursor
    order and the cursor jumps. A gap between two runs is cells nobody
    wrote.
    """
    runs: list[Run] = []

    start = 0
    end = 0
    text: list[str] | None = None
    appearance: Appearance | None = None
    written = False
    blank = True

    for column, cell in sorted(row.items()):
        char = cell.char
        # Whether the character draws as it stands: printable ASCII
        # does, and so does anything above it that is not an image
        # placeholder. A control -- the parser eats those, so one in a
        # cell is a bug no front end may pass on -- the delete
        # character, and the placeholder, whose combining marks no
        # font has, do not. Written out rather than called: this runs
        # once per cell of every rebuilt row.
        if " " <= char <= "~":
            char_plain = True
        elif char < " " or char == "\x7f":
            char_plain = False
        else:
            char_plain = not char.startswith(PLACEHOLDER)
        char_appearance = cell.appearance
        char_written = cell.written
        char_blank = char == " "
        # A run goes on while the columns touch and every cell draws
        # the same way: the same appearance, written or erased alike.
        # A front end hands one style to the whole run, and the mark
        # that keeps a written blank changes no attribute, so blank
        # cells join any run and only the trailing one asks after
        # them. Anything that does not draw as it stands -- a wide
        # character's two columns, a control, a cell of an image --
        # breaks the run, and stands on its own.
        if (
            text is not None
            and column == end
            and char_appearance is appearance
            and char_written == written
            and cell.width == 1
            and char_plain
        ):
            if not char_blank:
                blank = False
            text.append(char)
            end = column + 1
            continue
        if text is not None:
            assert appearance is not None
            runs.append(
                Run(start, end, "".join(text), appearance, written, True, blank)
            )
        if cell.width == 1 and char_plain:
            start = column
            end = column + 1
            text = [char]
            appearance = char_appearance
            written = char_written
            blank = char_blank
        else:
            runs.append(
                Run(
                    column,
                    column + cell.width,
                    char,
                    char_appearance,
                    char_written,
                    False,
                    False,
                )
            )
            text = None
    if text is not None:
        assert appearance is not None
        runs.append(Run(start, end, "".join(text), appearance, written, True, blank))

    # A blank a program wrote keeps its trailing column, so the run
    # at the end gives up its trailing blanks: they draw under a
    # style of their own, the way one cell at a time always did.
    if runs:
        last = runs[-1]
        if last.plain and not last.blank:
            stripped = last.text.rstrip(" ")
            if stripped and len(stripped) != len(last.text):
                cut = len(stripped)
                runs[-1] = Run(
                    last.start,
                    last.start + cut,
                    stripped,
                    last.appearance,
                    last.written,
                    True,
                    False,
                )
                runs.append(
                    Run(
                        last.start + cut,
                        last.end,
                        last.text[cut:],
                        last.appearance,
                        last.written,
                        True,
                        True,
                    )
                )

    return runs
