"""
The page of a screen as rows of named data: what a pymux server sends a
peer that mirrors one of its panes.

The peer holds the visible page and nothing else. The owner keeps the
history and runs what reads it (copy mode, search, capture), so the
peer has no state to keep in step with the owner's, and each frame
holds only the rows that changed since the last one it was sent.
Lillecarl/pymux#759.

**The format is the protocol between two builds** that a person
upgrades at different times. So it names nothing of this package: a
run of cells carries its characters, the SGR parameters that style
them and the link they sit in. Every field is named and a missing one
has a default, so a newer owner may add one and an older peer reads on
past it. Each character carries its own column: two builds may count
the width of a character differently, and the owner's count is the
one the program drew to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .cells import _CHAR_CACHE, _ERASED_CACHE, UNWRITTEN, ErasedCell, appearance_of
from .page import Row
from .parameters import CursorShape
from .sgr import parameters_of, rendition_of

if TYPE_CHECKING:
    from .screen import Screen

__all__ = ["GridWriter", "put_frame", "row_data", "row_of"]

#: The SGR parameters of a plain pen, which a run leaves out.
_PLAIN_SGR = "0"


def row_data(row: Row | None, columns: int) -> dict[str, Any]:
    "One row as named data: runs of cells that share how they look."
    runs: list[dict[str, Any]] = []
    run: dict[str, Any] | None = None
    appearance = None
    erased = False
    after = -1
    for column in sorted(row or ()):
        assert row is not None
        cell = row[column]
        if cell is UNWRITTEN or column >= columns:
            continue
        kind = type(cell) is ErasedCell
        if run is not None and cell.appearance is appearance and kind == erased and column == after:
            run["cells"].append(cell.char)
        else:
            appearance, erased = cell.appearance, kind
            run = {"x": column, "cells": [cell.char]}
            sgr = parameters_of(appearance.rendition)
            if sgr != _PLAIN_SGR:
                run["sgr"] = sgr
            if appearance.hyperlink:
                run["link"] = appearance.hyperlink
            if appearance.hyperlink_id:
                run["link_id"] = appearance.hyperlink_id
            if erased:
                run["erased"] = True
            runs.append(run)
        after = column + 1
    data: dict[str, Any] = {"runs": runs}
    if row is not None and row.wrapped:
        data["wrapped"] = True
    return data


def row_of(data: dict[str, Any]) -> Row:
    "The row that `row_data` describes."
    row = Row()
    for run in data.get("runs") or ():
        appearance = appearance_of[
            rendition_of(str(run.get("sgr", _PLAIN_SGR))), str(run.get("link", "")), str(run.get("link_id", ""))
        ]
        cells = _ERASED_CACHE if run.get("erased") else _CHAR_CACHE
        x = int(run.get("x", 0))
        for offset, char in enumerate(run.get("cells") or ()):
            row[x + offset] = cells[str(char), appearance]
    row.wrapped = bool(data.get("wrapped"))
    return row


def _cursor_of(screen: Screen) -> dict[str, Any]:
    position = screen.pt_cursor_position
    cursor = {
        "x": position.x,
        "y": position.y - screen.line_offset,
        "waits": screen.pending_wrap,
        "visible": screen.page.show_cursor,
    }
    # Only a shape a program asked for: the terminal keeps its own otherwise.
    if screen.cursor_style_asked:
        cursor["style"] = int(screen.cursor_style)
    return cursor


class GridWriter:
    """
    What one peer was last sent of one screen, so the next frame holds
    only what differs.
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, Any] | None] = []
        self.size: tuple[int, int] | None = None
        self.cursor: dict[str, Any] | None = None
        self.top = -1
        self.writes = -1
        self.everything_at = -1

    def frame(self, screen: Screen) -> dict[str, Any] | None:
        "The rows and the cursor that changed since the last frame, or `None` when nothing did."
        lines, columns = screen.lines, screen.columns
        top = screen.line_offset
        written_at = screen.written_at
        everything_at = screen.everything_at
        whole = (
            (lines, columns) != self.size
            or top != self.top
            or everything_at != self.everything_at
            or len(self.sent) != lines
        )
        if whole:
            self.sent = [None] * lines
        since = -1 if whole else self.writes
        buffer = screen.page.data_buffer
        rows = []
        for y in range(lines):
            number = top + y
            if written_at.get(number, everything_at) <= since:
                continue
            data = row_data(buffer.get(number), columns)
            if data != self.sent[y]:
                self.sent[y] = data
                rows.append([y, data])
        cursor = _cursor_of(screen)
        self.size, self.top, self.writes, self.everything_at = (lines, columns), top, screen.writes, everything_at
        if not rows and cursor == self.cursor and not whole:
            return None
        self.cursor = cursor
        return {"lines": lines, "columns": columns, "rows": rows, "cursor": cursor}


def put_frame(screen: Screen, frame: dict[str, Any]) -> None:
    """
    Put a frame a `GridWriter` made on a screen that shows nothing else.
    Its page is rows 0 to `lines - 1`, with no history over it.
    """
    lines = int(frame.get("lines", screen.lines))
    columns = int(frame.get("columns", screen.columns))
    if (lines, columns) != (screen.lines, screen.columns):
        screen.resize(lines, columns)
        # The owner sends every row after a resize; what a reflow made
        # of the old ones is nobody's.
        screen.page.data_buffer.clear()
        screen.history_floor = screen.reflow_floor = 0
        screen.touch_everything()
    buffer = screen.page.data_buffer
    screen.max_y = lines - 1
    for y, data in frame.get("rows") or ():
        y = int(y)
        if not 0 <= y < lines:
            continue
        row = row_of(data)
        if row or row.wrapped:
            buffer[y] = row
        else:
            buffer.pop(y, None)
        screen.touch(y)
    cursor = frame.get("cursor")
    if cursor:
        position = screen.pt_cursor_position
        position.x = min(max(int(cursor.get("x", 0)), 0), columns)
        position.y = min(max(int(cursor.get("y", 0)), 0), lines - 1)
        screen.pending_wrap = bool(cursor.get("waits"))
        screen.page.show_cursor = bool(cursor.get("visible", True))
        style = cursor.get("style")
        screen.cursor_style_asked = style is not None
        if style is not None and int(style) in iter(CursorShape):
            screen.cursor_style = CursorShape(int(style))
