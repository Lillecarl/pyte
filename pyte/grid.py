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

An image crosses once, under its id, and the placements name it. The
peer draws it as its own terminal can.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from .cells import _CHAR_CACHE, _ERASED_CACHE, UNWRITTEN, ErasedCell, appearance_of
from .images import GraphicsImage, GraphicsPlacement
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


def _about(screen: Screen) -> dict[str, Any]:
    "What a program set that the peer shows beside the page: the title and the pointer's shape."
    return {"title": screen.titles.window, "pointer": screen.pointer_shapes.shape}


def _placement_data(placement: GraphicsPlacement, top: int) -> dict[str, Any]:
    data: dict[str, Any] = {
        "image": placement.image_id,
        "placement": placement.placement_id,
        "x": placement.x,
        "y": placement.y - top,
        "columns": placement.columns,
        "rows": placement.rows,
        "z": placement.z,
        "asked": placement.asked_for_the_box,
    }
    if placement.virtual:
        data["virtual"] = True
    if placement.crop is not None:
        data["crop"] = list(placement.crop)
    return data


def _placement_of(data: dict[str, Any]) -> GraphicsPlacement:
    crop = data.get("crop")
    return GraphicsPlacement(
        int(data.get("image", 0)),
        int(data.get("placement", 0)),
        int(data.get("x", 0)),
        int(data.get("y", 0)),
        int(data.get("columns", 0)),
        int(data.get("rows", 0)),
        int(data.get("z", 0)),
        bool(data.get("virtual")),
        bool(data.get("asked", True)),
        None if crop is None else (int(crop[0]), int(crop[1]), int(crop[2]), int(crop[3])),
    )


def _image_data(image_id: int, image: GraphicsImage) -> dict[str, Any]:
    return {
        "id": image_id,
        "format": int(image.format),
        "width": image.width,
        "height": image.height,
        "data": base64.b64encode(image.data).decode("ascii"),
    }


def _shown_placements(screen: Screen) -> list[GraphicsPlacement]:
    "The placements a person can see on the page, and every one the placeholders of a row may point at."
    top = screen.line_offset
    bottom = top + screen.lines
    return [
        placement
        for placement in screen.graphics.placements
        if placement.virtual or (placement.y < bottom and placement.y + placement.rows > top)
    ]


class GridWriter:
    """
    What one peer was last sent of one screen, so the next frame holds
    only what differs.
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, Any] | None] = []
        self.size: tuple[int, int] | None = None
        self.cursor: dict[str, Any] | None = None
        self.about: dict[str, Any] | None = None
        self.placements: list[dict[str, Any]] | None = None
        #: The image the peer holds under each id. Held, not compared by
        #: content: a program may send new pixels under an old id.
        self.images: dict[int, GraphicsImage] = {}
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
        about = _about(screen)
        self.size, self.top, self.writes, self.everything_at = (lines, columns), top, screen.writes, everything_at
        pictures = self._pictures(screen, whole)
        if not rows and cursor == self.cursor and about == self.about and not pictures and not whole:
            return None
        self.cursor, self.about = cursor, about
        return {"lines": lines, "columns": columns, "rows": rows, "cursor": cursor, **about, **pictures}

    def _pictures(self, screen: Screen, whole: bool) -> dict[str, Any]:
        """
        The placements, when they changed, and each image they show
        that the peer does not hold yet. An image crosses once.
        """
        shown = _shown_placements(screen) if screen.graphics.placements or self.placements else []
        placements = [_placement_data(placement, screen.line_offset) for placement in shown]
        if placements == self.placements and not whole:
            return {}
        self.placements = placements
        by_id = screen.graphics.images_by_id
        wanted = {placement.image_id: by_id[placement.image_id] for placement in shown if placement.image_id in by_id}
        pictures: dict[str, Any] = {"placements": placements}
        new = [
            _image_data(image_id, image) for image_id, image in wanted.items() if self.images.get(image_id) is not image
        ]
        if new:
            pictures["images"] = new
        if new or wanted.keys() != self.images.keys() or whole:
            pictures["image_ids"] = sorted(wanted)
        self.images = wanted
        return pictures


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
    if "title" in frame:
        screen.titles.window = str(frame["title"])
    if "pointer" in frame:
        pointer = str(frame["pointer"])
        screen.pointer_shapes.stack = [pointer] if pointer else []
    _put_pictures(screen, frame)


def _put_pictures(screen: Screen, frame: dict[str, Any]) -> None:
    graphics = screen.graphics
    for data in frame.get("images") or ():
        try:
            pixels = base64.b64decode(str(data.get("data", "")))
        except ValueError:
            continue
        graphics.images_by_id[int(data.get("id", 0))] = GraphicsImage(
            int(data.get("format", 0)), int(data.get("width", 0)), int(data.get("height", 0)), pixels
        )
    if "image_ids" in frame:
        kept = {int(image_id) for image_id in frame["image_ids"] or ()}
        for image_id in [image_id for image_id in graphics.images_by_id if image_id not in kept]:
            del graphics.images_by_id[image_id]
    if "placements" in frame:
        graphics.placements = [_placement_of(data) for data in frame["placements"] or ()]
