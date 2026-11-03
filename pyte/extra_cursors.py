"""
kitty's multiple cursors: the extra cursors a program asks the terminal
to draw, and the one colour pair that all of them share.
https://sw.kovidgoyal.net/kitty/multiple-cursors-protocol/
Lillecarl/pymux#891.

A program writes "CSI > SHAPE ; WHERE : COORDINATES ... SP q". A screen
holds what it asked for in an `ExtraCursors`, and what draws the screen
reads that. A cell is a row and a column of the screen, counted from
zero, and a scroll moves none of them: the protocol says so.

The arithmetic is kitty's, `screen_multi_cursor` in kitty/screen.c,
down to the coordinate zero: kitty takes one away from an unsigned
number, so a zero there is the largest number there is.
"""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, ClassVar, Final, NamedTuple

from .colors import Color, SgrColor
from .keep import Keep
from .parameters import CursorShape

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = (
    "SUPPORTED",
    "UNSET_COLOR",
    "ColorSpace",
    "CursorColor",
    "ExtraCommand",
    "ExtraCursors",
    "ExtraShape",
    "Where",
    "shape_drawn",
)


class ExtraShape(IntEnum):
    "What an extra cursor looks like, as the first parameter names it."

    NONE = 0
    BLOCK = 1
    BEAM = 2
    UNDERLINE = 3
    #: Whatever shape the main cursor has. DECSCUSR can change it later.
    MAIN = 29


class ExtraCommand(IntEnum):
    "The first parameters that name no shape."

    TEXT_COLOR = 30
    CURSOR_COLOR = 40
    ASK_CURSORS = 100
    ASK_COLORS = 101


class Where(IntEnum):
    "The kind of a group of coordinates: the number in front of them."

    MAIN_CURSOR = 0
    POINTS = 2
    RECTANGLES = 4


class ColorSpace(IntEnum):
    "The number in front of a colour of 30 or 40."

    #: The colour of the main cursor.
    UNSET = 0
    #: Reverse video: the cursor takes the colours of the cell under it.
    SPECIAL = 1
    RGB = 2
    INDEXED = 5


#: Everything this screen reads, as it answers "CSI > SP q".
SUPPORTED: Final = (
    ExtraShape.BLOCK,
    ExtraShape.BEAM,
    ExtraShape.UNDERLINE,
    ExtraShape.MAIN,
    ExtraCommand.TEXT_COLOR,
    ExtraCommand.CURSOR_COLOR,
    ExtraCommand.ASK_CURSORS,
    ExtraCommand.ASK_COLORS,
)

#: kitty's `index_type` is unsigned, so one less than a zero is this.
_WRAPPED: Final = 2**32 - 1


class CursorColor(NamedTuple):
    "One colour of the pair: the cursor's own, or the text's under it."

    space: ColorSpace = ColorSpace.UNSET
    #: The colour, for `RGB` and `INDEXED`.
    color: SgrColor | None = None

    def parameters(self) -> tuple[int, ...]:
        "The colour as its space and the numbers after it."
        color = self.color
        if self.space == ColorSpace.RGB and color is not None and color.rgb is not None:
            return (self.space, *color.rgb)
        if self.space == ColorSpace.INDEXED and color is not None and color.index is not None:
            return (self.space, color.index)
        return (self.space,)

    @classmethod
    def read(cls, numbers: Sequence[int]) -> CursorColor | None:
        """
        The colour that `numbers` names, or None when they name none and
        the colour stays as it was. kitty keeps the low byte of each
        number.
        """
        if not numbers:
            return None
        space, values = numbers[0], numbers[1:]
        if space == ColorSpace.UNSET:
            return UNSET_COLOR
        if space == ColorSpace.SPECIAL:
            return cls(ColorSpace.SPECIAL)
        if space == ColorSpace.RGB and len(values) >= len(Color._fields):
            rgb = Color(*(value & 0xFF for value in values[: len(Color._fields)]))
            return cls(ColorSpace.RGB, SgrColor(rgb=rgb))
        if space == ColorSpace.INDEXED and values:
            return cls(ColorSpace.INDEXED, SgrColor(index=values[0] & 0xFF))
        return None


UNSET_COLOR: Final = CursorColor()


def shape_drawn(shape: ExtraShape, main: CursorShape) -> ExtraShape:
    "The shape to draw: `MAIN` takes the one DECSCUSR gave the main cursor."
    if shape != ExtraShape.MAIN:
        return shape
    if main in (CursorShape.BLINKING_UNDERLINE, CursorShape.STEADY_UNDERLINE):
        return ExtraShape.UNDERLINE
    if main in (CursorShape.BLINKING_BAR, CursorShape.STEADY_BAR):
        return ExtraShape.BEAM
    return ExtraShape.BLOCK


def _cell(number: int) -> int:
    return number - 1 if number > 0 else _WRAPPED


def _groups(numbers: Sequence[int], size: int) -> Iterator[Sequence[int]]:
    "Whole groups of `size`; the numbers left over count for nothing."
    for start in range(0, len(numbers) - size + 1, size):
        yield numbers[start : start + size]


class ExtraCursors:
    """
    The extra cursors of a screen, and their colours.

    `cells` maps a row and a column to a shape that is never `NONE`.
    `changes` counts every sequence that may have changed anything, so a
    reader that drew at one count knows when to draw again.
    """

    __slots__ = ("cells", "changes", "cursor_color", "text_color")

    KEEP: ClassVar[dict[str, Keep]] = {
        "cells": Keep.SAVED,
        "text_color": Keep.SAVED,
        "cursor_color": Keep.SAVED,
        "changes": Keep.SAVED,
    }

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], ExtraShape] = {}
        self.text_color = UNSET_COLOR
        self.cursor_color = UNSET_COLOR
        self.changes = 0

    def clear(self) -> None:
        "Take every cursor away: ED 2, 3 and 22, and a switch of screen."
        if self.cells:
            self.cells = {}
            self.changes += 1

    def reset(self) -> None:
        "Take the cursors and the colours away: RIS and DECSTR."
        self.cells = {}
        self.text_color = self.cursor_color = UNSET_COLOR
        self.changes += 1

    def crop(self, lines: int, columns: int) -> None:
        "Drop the cursors a smaller screen no longer holds."
        kept = {cell: shape for cell, shape in self.cells.items() if cell[0] < lines and cell[1] < columns}
        if len(kept) != len(self.cells):
            self.cells = kept
            self.changes += 1

    def in_row(self, row: int) -> dict[int, ExtraShape]:
        "The cursors of one row of the screen, by column."
        return {column: shape for (y, column), shape in self.cells.items() if y == row}

    def rows(self) -> set[int]:
        return {row for row, _column in self.cells}

    def listed(self) -> list[tuple[int, int, ExtraShape]]:
        "Every cursor as a row, a column and a shape, top to bottom."
        return [(row, column, shape) for (row, column), shape in sorted(self.cells.items())]

    def set_color(self, which: ExtraCommand, numbers: Sequence[int]) -> None:
        color = CursorColor.read(numbers)
        self.changes += 1
        if color is None:
            return
        if which == ExtraCommand.CURSOR_COLOR:
            self.cursor_color = color
        else:
            self.text_color = color

    def set_shape(
        self,
        shape: ExtraShape,
        where: int,
        numbers: Sequence[int],
        lines: int,
        columns: int,
        main: tuple[int, int],
    ) -> None:
        """
        Put `shape` on the cells of one group, or take the cursors off
        them for `NONE`. `numbers` are the coordinates after the kind,
        and `main` is where the main cursor stands.
        """
        self.changes += 1
        if where == Where.MAIN_CURSOR:
            row, column = main
            self._set_points(shape, (min(row, lines - 1) + 1, min(column, columns - 1) + 1), lines, columns)
        elif where == Where.POINTS:
            self._set_points(shape, numbers, lines, columns)
        elif where == Where.RECTANGLES:
            self._set_rectangles(shape, numbers, lines, columns)

    def _set_points(self, shape: ExtraShape, numbers: Sequence[int], lines: int, columns: int) -> None:
        cells = dict(self.cells)
        for y, x in _groups(numbers, 2):
            cell = (_cell(y), _cell(x))
            if shape == ExtraShape.NONE:
                cells.pop(cell, None)
            elif cell[0] < lines and cell[1] < columns:
                cells[cell] = shape
        self.cells = cells

    def _set_rectangles(self, shape: ExtraShape, numbers: Sequence[int], lines: int, columns: int) -> None:
        # Fewer than four numbers is the whole screen, in kitty: the
        # protocol's "CSI > 0 ; 4 SP q" clears everything this way.
        if len(numbers) < 4:
            if shape == ExtraShape.NONE:
                self.cells = {}
            else:
                self.cells = {(row, column): shape for row in range(lines) for column in range(columns)}
            return
        rectangles = [tuple(_cell(number) for number in group) for group in _groups(numbers, 4)]
        cells = {
            (row, column): drawn
            for (row, column), drawn in self.cells.items()
            if not any(top <= row <= bottom and left <= column <= right for top, left, bottom, right in rectangles)
        }
        if shape != ExtraShape.NONE:
            for top, left, bottom, right in rectangles:
                bottom = min(bottom, lines - 1)
                right = min(right, columns - 1)
                for row in range(top, bottom + 1):
                    for column in range(left, right + 1):
                        cells[row, column] = shape
        self.cells = cells
