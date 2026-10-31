"""
A screen as the bytes that paint it again.

`repaint(screen)` gives the escape sequences that take any screen of the
same size to the state of `screen`: its history, its page, the
alternate page in front of it, and what a program set and reads back.
A mirror feeds them through its own parser, so a peer of another build
reads what both builds speak, and nothing names a class or a field.
`freeze.py` is the other way to carry a screen, and only a hot upgrade
takes it: there both sides are one build. Lillecarl/pymux#759.

`tests/test_repaint.py` lists what the bytes cannot carry, and why.
The largest: a sixel image (Lillecarl/pymux#857), the parked
alternate page while the first page is in front, and the history below
`reflow_floor`, which arrives laid out at the width the screen has now.
The marks on rows are not here either: the embedder sets them
(`Screen.mark_row`), so `marks_of` and `mark` carry them beside the
bytes.

The bytes ask the screen nothing, but some still make it answer (a set
of "?2048" tells the size): `paint` feeds them with the screen's
callbacks held.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from . import charsets as cs
from . import control, escape
from .cells import PLAIN, UNWRITTEN, ErasedCell, Protection, Rendition, protection_of
from .images import GraphicsPlacement, GraphicsState, PixelFormat
from .modes import PRIVATE_MODE_SHIFT, AnsiMode, PrivateMode, flag_of
from .osc import Osc
from .page import Row, RowMark
from .parameters import DEFAULT_CONFORMANCE_LEVEL, AttributeExtent, StatusDisplay, StatusLineType
from .sequences.csi import Csi, Marker, csi
from .sequences.escapes import Escape, announce, esc
from .sequences.kitty_graphics import Action, GraphicsCommand, GraphicsKey, Quiet
from .sequences.strings import osc
from .sgr import parameters_of

if TYPE_CHECKING:
    from .screen import Screen
    from .streams import Stream

__all__ = ["mark", "marks_of", "paint", "repaint"]

#: The base64 one graphics command carries at most, as kitty sends it.
_CHUNK = 4096

#: XTSAVE, "CSI ? Pm s". DECSLRM ends in the same byte without the marker.
_XTSAVE = "s"

#: The title stack's push, "CSI 22 ; 0 t": both titles at once.
_PUSH_TITLES = 22

#: The private modes a reset leaves on. `Screen.reset` says why each one.
_RESET_MODES = frozenset(
    [
        PrivateMode.AUTOWRAP.flag,
        PrivateMode.SHOW_CURSOR.flag,
        PrivateMode.ALTERNATE_SCROLL.flag,
        PrivateMode.GRAPHEME_CLUSTERS.flag,
    ]
)

#: The modes that take the other page. A page is painted, not switched to.
_PAGE_MODES = frozenset(
    [
        PrivateMode.ALTERNATE_SCREEN.flag,
        PrivateMode.ALTERNATE_SCREEN_AGAIN.flag,
        PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag,
    ]
)

#: Set before the rows they change: DECCOLM clears the page, and the
#: cluster rule decides which characters join.
_FIRST_MODES = (
    PrivateMode.ALLOW_80_TO_132.flag,
    PrivateMode.NO_CLEAR_ON_COLUMN_CHANGE.flag,
    PrivateMode.COLUMNS_132.flag,
    PrivateMode.GRAPHEME_CLUSTERS.flag,
)

#: Set apart from the rest. A set of "?1048" saves the cursor and "?6"
#: sends it home, so both go with the savepoint; insert mode would push
#: the cell that a waiting cursor draws again.
_HELD_MODES = frozenset([PrivateMode.SAVE_CURSOR.flag, PrivateMode.ORIGIN.flag, AnsiMode.INSERT_REPLACE])

#: The designation of each character set, by the table it names.
_DESIGNATION = {id(table): code for code, table in reversed(list(cs.MAPS.items()))}

#: The intermediate byte that names each of G0 to G3.
_SLOTS = ("(", ")", "*", "+")

#: The shift that takes each slot into GL.
_SHIFTS = (control.SI, control.SO, esc(Escape.LS2), esc(Escape.LS3))

_ASCII = [cs.LAT1_MAP] * 4


def repaint(screen: Screen, pending: str = "") -> str:
    """
    The bytes that take a screen of the same size to the state of
    `screen`. `pending` is the sequence its parser is in the middle of
    (`Stream.replay`). It goes last, so the far parser stands where the
    near one stands.
    """
    return _Painter(screen).run() + pending


def marks_of(screen: Screen) -> list[list[int]]:
    """
    The marks on the rows of each page, as `[parked, row, marks]`: the
    row counts from the top of its page, and `parked` is 1 for the
    first page while the alternate page is in front. Rows under
    `reflow_floor` are left out, since they arrive laid out anew.
    """
    marks = []
    for parked, buffer, state in _pages(screen):
        top = max(0, state["max_y"] - screen.lines + 1)
        floor = max(min(state["history_floor"], top), min(state["reflow_floor"], top))
        for number, row in buffer.items():
            if row.marks and number >= floor:
                marks.append([parked, number - top, int(row.marks)])
    return marks


def mark(screen: Screen, marks: list[list[int]]) -> None:
    "Put the marks `marks_of` gave on the rows they name, of a screen `repaint` painted."
    pages = {parked: (buffer, state) for parked, buffer, state in _pages(screen)}
    for parked, row, marks_here in marks:
        held = pages.get(parked)
        if held is None:
            continue
        buffer, state = held
        number = max(0, state["max_y"] - screen.lines + 1) + row
        if number >= state["history_floor"]:
            buffer[number].marks = RowMark(marks_here)


def _pages(screen: Screen) -> list[tuple[int, Any, dict]]:
    pages = [(0, screen.page.data_buffer, {name: getattr(screen, name) for name in screen.swap_variables})]
    if screen._original_screen is not None:
        pages.append((1, screen._original_screen.data_buffer, screen._original_screen_vars))
    return pages


def paint(stream: Stream, text: str) -> None:
    """
    Feed what `repaint` gave into `stream`, with its screen telling
    nobody: a repaint states what is, and an answer to it would reach
    the program as typing.
    """
    screen = stream.screen
    kept = {name: getattr(screen, name) for name in _CALLBACKS}
    for name in _CALLBACKS:
        setattr(screen, name, _nothing)
    try:
        stream.feed(text)
    finally:
        for name, value in kept.items():
            setattr(screen, name, value)


#: What a screen tells the world through, which a repaint holds.
_CALLBACKS = ("write_process_input", "bell_func", "osc_func", "resize_func", "surroundings_func")


def _nothing(*args: object) -> None:
    pass


def _mode_sequence(flag: int, final: str) -> str:
    "SM or RM of one mode, by the number `Screen.mode` holds it as."
    if flag >> PRIVATE_MODE_SHIFT:
        return csi(final, flag >> PRIVATE_MODE_SHIFT, private=Marker.QUESTION)
    return csi(final, flag)


def _placements_by_row(graphics: GraphicsState) -> dict[int, list[GraphicsPlacement]]:
    "The placements a kitty command can make again, by the row each starts on."
    by_row: dict[int, list[GraphicsPlacement]] = {}
    for placement in graphics.placements:
        image = graphics.images_by_id.get(placement.image_id)
        if image is None or image.format == PixelFormat.SIXEL or placement.crop is not None:
            continue
        by_row.setdefault(placement.y, []).append(placement)
    return by_row


class _Painter:
    """
    One repaint. It keeps what the far screen holds as it goes -- the
    pen, the modes, the character sets -- so each change writes only
    the difference.
    """

    def __init__(self, screen: Screen) -> None:
        self.screen = screen
        self.columns = screen.columns
        self.lines = screen.lines
        self.parts: list[str] = []
        self.rendition = PLAIN
        self.hyperlink = ("", "")
        self.protection = 0
        self.modes = set(_RESET_MODES)
        self.g_charsets = list(_ASCII)
        self.gl = 0

    def run(self) -> str:
        screen = self.screen
        self.put(esc(escape.RIS))
        if screen.conformance_level != DEFAULT_CONFORMANCE_LEVEL:
            self.put(csi(Csi.DECSCL, screen.conformance_level, 1 if screen.seven_bit_controls else 0))
        elif not screen.seven_bit_controls:
            self.put(announce(escape.S8C1T))
        self.terminal()

        front = {name: getattr(screen, name) for name in screen.swap_variables}
        if screen.in_alternate_screen:
            assert screen._original_screen is not None
            # The set may hold more than one page mode (Lillecarl/pymux#856),
            # and only "?1049" saves the cursor: a first page with no save
            # was not left by it.
            held = [mode for mode in _PAGE_MODES if mode in screen.mode]
            with_cursor = PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag
            if with_cursor in held and screen._original_screen_vars["savepoints"]:
                entered_by = with_cursor
            else:
                entered_by = min([mode for mode in held if mode != with_cursor] or [PrivateMode.ALTERNATE_SCREEN.flag])
            self.page(screen._original_screen, screen._original_screen_vars, front=False, entered_by=entered_by)
            self.set_modes([entered_by])
            # The other page starts where the first one left the cursor,
            # under its character sets: home, and plain letters.
            self.put(csi(escape.CUP))
            self.charsets(_ASCII, 0)
        self.page(screen.page, front, front=True)
        return "".join(self.parts)

    def put(self, text: str) -> None:
        self.parts.append(text)

    # -- what belongs to the terminal and not to a page ----------------

    def terminal(self) -> None:
        screen = self.screen
        titles = screen.titles
        for icon, window in titles.stack:
            self.put(osc("2", window) + osc("1", icon) + csi(Csi.XTWINOPS, _PUSH_TITLES, 0))
        if titles.window or titles.stack:
            self.put(osc("2", titles.window))
        if titles.icon or titles.stack:
            self.put(osc("1", titles.icon))
        for mode in sorted(titles.modes):
            self.put(csi(Csi.XTWINOPS, mode, private=Marker.GREATER))

        colors = screen.colors
        for index, color in sorted(colors.by_index.items()):
            self.put(osc(Osc.PALETTE_COLOR, str(index), color.spec))
        for code, color in sorted(colors.by_code.items()):
            self.put(osc(code, color.spec))
        if screen.tab_color is not None:
            for channel, value in zip(("red", "green", "blue"), screen.tab_color):
                self.put(osc(Osc.TAB_COLOR, "1", "bg", channel, "brightness", str(value)))

        for resource, value in sorted(screen.key_modifier_options.items()):
            self.put(csi(Csi.XTMODKEYS, resource, value, private=Marker.GREATER))
        for resource, value in sorted(screen.key_format_options.items()):
            self.put(csi(Csi.XTFMTKEYS, resource, value, private=Marker.GREATER))

        if screen.cursor_style_asked:
            self.put(csi(Csi.DECSCUSR, screen.cursor_style))
        if screen.attribute_extent != AttributeExtent.STREAM:
            self.put(csi(Csi.DECSACE, screen.attribute_extent))
        if screen.status_line != StatusLineType.NONE:
            self.put(csi(Csi.DECSSDT, screen.status_line))
        if screen.active_display != StatusDisplay.MAIN:
            self.put(csi(Csi.DECSASD, screen.active_display))
        if screen.lines_per_screen != screen.lines:
            self.put(csi(Csi.DECSNLS, screen.lines_per_screen))

        # XTSAVE reads each mode as it stands, so it is set for the save.
        # The pages set their own modes after this.
        for number, on in sorted(screen.saved_modes.items()):
            flag = flag_of(number)
            if flag in _PAGE_MODES or flag in _HELD_MODES:
                continue
            if on:
                self.set_modes([flag])
            else:
                self.reset_modes([flag])
            self.put(csi(_XTSAVE, number, private=Marker.QUESTION))

    # -- one page ------------------------------------------------------

    def page(self, page: Any, state: dict, front: bool, entered_by: int | None = None) -> None:
        "Paint one page and what it carries; `state` holds its `Screen.swap_variables`."
        screen = self.screen
        mode = state["mode"]
        # Rows go in wrapping, over what is there, counted from the top.
        self.set_modes([PrivateMode.AUTOWRAP.flag] if PrivateMode.AUTOWRAP.flag not in self.modes else [])
        self.reset_modes([AnsiMode.INSERT_REPLACE] if AnsiMode.INSERT_REPLACE in self.modes else [])
        self.origin(False)
        self.set_modes([flag for flag in _FIRST_MODES if flag in mode and flag not in self.modes])
        self.reset_modes([flag for flag in _FIRST_MODES if flag not in mode and flag in self.modes])
        graphics = state["graphics"]
        self.images(graphics)

        buffer = page.data_buffer
        max_y = state["max_y"]
        top = max(0, max_y - self.lines + 1)
        # A clear of the history leaves its floor over rows the page still shows.
        floor = min(state["history_floor"], top)
        flowed = max(floor, min(state["reflow_floor"], top))
        placements = _placements_by_row(graphics)

        self.lines_of(page, floor, flowed - 1)
        full = self.rows(buffer, flowed, max_y, placements)
        # Rows under the cursor's lowest reach: a program put the cursor
        # there without a linefeed, or DECALN filled them.
        for number in range(max_y + 1, top + self.lines):
            row = buffer.get(number)
            if not row:
                full = False
                continue
            if not (full and row.wrapped and 0 in row):
                self.pen_to(PLAIN, self.hyperlink, self.protection)
                self.put(csi(escape.CUP, number - top + 1, 1))
            full = self.row(row)
        self.under_images(buffer, top, placements)

        self.tabstops(state["tabstops"])
        for flags in state["kitty_flags_stack"]:
            self.put(csi(Csi.KITTY_KEYBOARD, flags, private=Marker.GREATER))
        if state["pointer_shapes"].stack:
            self.put(osc(Osc.POINTER_SHAPE, ">" + ",".join(state["pointer_shapes"].stack)))

        later = [flag for flag in mode if flag not in _PAGE_MODES and flag not in _HELD_MODES]
        self.set_modes([flag for flag in later if flag not in self.modes])
        self.reset_modes(
            [flag for flag in self.modes if flag not in mode and flag not in _PAGE_MODES and flag not in _HELD_MODES]
        )
        if page.show_cursor != (PrivateMode.SHOW_CURSOR.flag in mode):
            self.put(_mode_sequence(PrivateMode.SHOW_CURSOR.flag, escape.SM if page.show_cursor else escape.RM))

        # "?1049h" saves the first page's cursor as it switches, so that
        # page stands where its save says and leaves the save to it.
        save = entered_by != PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag
        savepoints = state["savepoints"]
        if savepoints:
            self.savepoint(savepoints[0], buffer, top, mode, save)
        if not front:
            return

        if screen.margins is not None:
            self.put(csi(escape.DECSTBM, screen.margins.top + 1, screen.margins.bottom + 1))
        if screen.horizontal_margins is not None:
            left, right = screen.horizontal_margins
            self.put(csi(Csi.DECSLRM, left + 1, right + 1))
        self.origin(PrivateMode.ORIGIN.flag in mode)
        self.cursor(state["pt_cursor_position"], state["pending_wrap"], buffer, top)
        if AnsiMode.INSERT_REPLACE in mode:
            self.set_modes([AnsiMode.INSERT_REPLACE])
        if PrivateMode.SAVE_CURSOR.flag in mode:
            # Set by the savepoint, or set here with nothing saved.
            self.modes.add(PrivateMode.SAVE_CURSOR.flag)
        self.pen_to(screen._rendition, (screen.hyperlink_id, screen.hyperlink), screen.protection)
        self.charsets(state["g_charsets"], state["gl"])
        if screen.single_shift is not None:
            self.put(esc(Escape.SS2 if screen.single_shift == 2 else Escape.SS3))

    def set_modes(self, flags: Iterable[int]) -> None:
        for flag in sorted(flags):
            self.put(_mode_sequence(flag, escape.SM))
            self.modes.add(flag)

    def reset_modes(self, flags: Iterable[int]) -> None:
        for flag in sorted(flags):
            self.put(_mode_sequence(flag, escape.RM))
            self.modes.discard(flag)

    def origin(self, on: bool) -> None:
        if on != (PrivateMode.ORIGIN.flag in self.modes):
            (self.set_modes if on else self.reset_modes)([PrivateMode.ORIGIN.flag])

    # -- rows ----------------------------------------------------------

    def lines_of(self, page: Any, first: int, last: int) -> None:
        """
        The history below `reflow_floor`, which keeps the width it was
        written at: the lines a program wrote, each laid out at this
        width as it goes in.
        """
        if first > last:
            return
        lines, _found = page.unwrap(first, last)
        for line in lines:
            row = Row()
            for column, cell in enumerate(line.cells):
                row[column] = cell
            self.row(row, wraps=True)
            self.newline()

    def rows(self, buffer: Any, first: int, last: int, placements: dict) -> bool:
        "Paint the rows from `first` to `last`, one under the other. True when the last one is full."
        full = False
        for number in range(first, last + 1):
            row = buffer.get(number)
            if number > first:
                # A full row wraps onto the next by itself, which marks it.
                wraps = full and row is not None and row.wrapped and 0 in row
                if not wraps:
                    self.newline()
            for placement in placements.get(number, ()):
                self.place(placement)
            full = self.row(row) if row is not None else False
        return full

    def newline(self) -> None:
        # A line that comes in takes the background that is set.
        self.pen_to(PLAIN, self.hyperlink, self.protection)
        self.put(control.CR + control.LF)

    def row(self, row: Row, wraps: bool = False) -> bool:
        """
        Paint one row from the left edge. True when its last column is
        written, so the next character wraps. With `wraps`, a row wider
        than the screen goes on onto the rows under it.
        """
        x = 0
        text: list[str] = []
        erased = 0
        edge = None if wraps else self.columns

        def flush() -> None:
            nonlocal erased
            if text:
                self.put("".join(text))
                text.clear()
            if erased:
                self.put(csi(escape.ECH, erased) + csi(escape.CUF, erased))
                erased = 0

        for column in sorted(row):
            cell = row[column]
            if cell is UNWRITTEN or not cell.char or (edge is not None and column >= edge):
                continue
            if column > x:
                flush()
                self.put(csi(escape.CUF, column - x))
                x = column
            appearance = cell.appearance
            if type(cell) is ErasedCell:
                if text or (erased and self.rendition != appearance.rendition):
                    flush()
                if not erased:
                    self.pen_to(appearance.rendition, self.hyperlink, self.protection)
                erased += 1
                x = column + 1
                continue
            hyperlink = (appearance.hyperlink_id, appearance.hyperlink)
            protection = protection_of(cell)
            if (
                erased
                or self.rendition != appearance.rendition
                or self.hyperlink != hyperlink
                or self.protection != protection
            ):
                flush()
                self.pen_to(appearance.rendition, hyperlink, protection)
            text.append(cell.char)
            x = column + cell.width
        # Only a character drawn in the last column leaves the cursor
        # waiting to wrap; an erase leaves it where it stands.
        waits = not erased and edge is not None and x >= edge
        if erased:
            self.put(csi(escape.ECH, erased))
            erased = 0
        flush()
        return waits

    def pen_to(self, rendition: Rendition, hyperlink: tuple[str, str], protection: int) -> None:
        if rendition != self.rendition:
            self.put(control.CSI + parameters_of(rendition) + escape.SGR)
            self.rendition = rendition
        if hyperlink != self.hyperlink:
            link_id, target = hyperlink
            self.put(osc(Osc.HYPERLINK, "id=" + link_id if link_id else "", target))
            self.hyperlink = hyperlink
        if protection != self.protection:
            iso = bool(protection & Protection.ISO)
            if iso != bool(self.protection & Protection.ISO):
                self.put(esc(Escape.SPA if iso else Escape.EPA))
            dec = bool(protection & Protection.DEC)
            if dec != bool(self.protection & Protection.DEC):
                self.put(csi(Csi.DECSCA, 1 if dec else 0))
            self.protection = protection

    # -- images --------------------------------------------------------

    def images(self, graphics: GraphicsState) -> None:
        "Send every image a kitty command can carry, quietly, and place none."
        for image_id, image in sorted(graphics.images_by_id.items()):
            if image.format == PixelFormat.SIXEL:
                continue
            payload = base64.b64encode(image.data).decode("ascii")
            chunks = [payload[start : start + _CHUNK] for start in range(0, len(payload), _CHUNK)] or [""]
            for number, chunk in enumerate(chunks):
                keys: dict[GraphicsKey, Any] = {}
                if number == 0:
                    keys[GraphicsKey.ACTION] = Action.TRANSMIT
                    keys[GraphicsKey.QUIET] = Quiet.NOTHING
                    keys[GraphicsKey.FORMAT] = image.format
                    if image.format != PixelFormat.PNG:
                        keys[GraphicsKey.WIDTH] = image.width
                        keys[GraphicsKey.HEIGHT] = image.height
                    if image_id:
                        keys[GraphicsKey.IMAGE_ID] = image_id
                keys[GraphicsKey.MORE] = int(number < len(chunks) - 1)
                self.put(str(GraphicsCommand(keys, chunk)))

    def place(self, placement: GraphicsPlacement) -> None:
        "Place an image on the row about to be painted, and leave the cursor on its left edge."
        keys: dict[GraphicsKey, Any] = {GraphicsKey.ACTION: Action.PUT, GraphicsKey.QUIET: Quiet.NOTHING}
        if placement.image_id:
            keys[GraphicsKey.IMAGE_ID] = placement.image_id
        if placement.placement_id:
            keys[GraphicsKey.PLACEMENT_ID] = placement.placement_id
        if placement.asked_for_the_box:
            keys[GraphicsKey.COLUMNS] = placement.columns
            keys[GraphicsKey.ROWS] = placement.rows
        if placement.z:
            keys[GraphicsKey.Z_INDEX] = placement.z
        if placement.virtual:
            keys[GraphicsKey.VIRTUAL] = 1
        keys[GraphicsKey.CURSOR] = 1
        if placement.x:
            self.put(csi(escape.CHA, placement.x + 1))
        self.put(str(GraphicsCommand(keys)))
        if placement.x:
            self.put(control.CR)

    def under_images(self, buffer: Any, top: int, placements: dict) -> None:
        """
        A placement takes the cells under it as it lands, and a program
        may have written over it since: the rows it lies on are painted
        again, those on the page at least.
        """
        rows: set[int] = set()
        for start, placed in placements.items():
            for placement in placed:
                if not placement.virtual and placement.z >= 0:
                    rows.update(range(max(start, top), min(start + placement.rows, top + self.lines)))
        for number in sorted(rows):
            row = buffer.get(number)
            if row:
                self.pen_to(PLAIN, self.hyperlink, self.protection)
                self.put(csi(escape.CUP, number - top + 1, 1))
                self.row(row)

    # -- what a page carries besides its rows --------------------------

    def tabstops(self, stops: set[int]) -> None:
        default = set(range(8, 1000, 8))
        if stops == default:
            return
        added, removed = stops - default, default - stops
        if all(stop < self.columns for stop in added | removed):
            for stop in sorted(removed):
                self.put(csi(escape.CHA, stop + 1) + csi(escape.TBC, 0))
        else:
            self.put(csi(escape.TBC, 3))
            added = {stop for stop in stops if stop < self.columns}
        for stop in sorted(added):
            self.put(csi(escape.CHA, stop + 1) + esc(escape.HTS))
        self.put(control.CR)

    def savepoint(self, savepoint: Any, buffer: Any, top: int, mode: Any, save: bool) -> None:
        "Stand where `savepoint` says, with its pen and character sets, and save it."
        self.origin(False)
        self.cursor_at(savepoint.cursor_x, savepoint.cursor_y, savepoint.pending_wrap, buffer, top)
        self.pen_to(savepoint.rendition, self.hyperlink, savepoint.protection)
        self.charsets(savepoint.g_charsets, savepoint.gl)
        if savepoint.origin:
            # A set of "?6" sends the cursor home, so the save goes first
            # and then the mode, which the save holds as it was.
            self.modes.add(PrivateMode.ORIGIN.flag)
        if save:
            if PrivateMode.SAVE_CURSOR.flag in mode:
                self.put(_mode_sequence(PrivateMode.SAVE_CURSOR.flag, escape.SM))
            else:
                self.put(esc(escape.DECSC))
        if savepoint.origin:
            self.put(_mode_sequence(PrivateMode.ORIGIN.flag, escape.SM))
        if save:
            self.charsets(_ASCII, 0)

    def cursor(self, position: Any, pending_wrap: bool, buffer: Any, top: int) -> None:
        screen = self.screen
        if PrivateMode.ORIGIN.flag in self.modes:
            # Counted from the margins.
            top_margin = screen.margins.top if screen.margins else 0
            left_margin = screen.horizontal_margins.left if screen.horizontal_margins else 0
            self.put(csi(escape.CUP, position.y - top - top_margin + 1, position.x - left_margin + 1))
            return
        self.cursor_at(position.x, position.y - top, pending_wrap, buffer, top)

    def cursor_at(self, x: int, y: int, pending_wrap: bool, buffer: Any, top: int) -> None:
        """
        Put the cursor on row `y` of the page. A cursor that waits to
        wrap waits after a character, so the one before it is drawn
        again.
        """
        if not pending_wrap or x == 0:
            self.put(csi(escape.CUP, y + 1, x + 1))
            return
        self.put(csi(escape.CUP, y + 1, x))
        row = buffer.get(top + y)
        cell = row.get(x - 1) if row is not None else None
        rendition, hyperlink, protection = self.rendition, self.hyperlink, self.protection
        if cell is None or cell is UNWRITTEN or type(cell) is ErasedCell or not cell.char:
            self.pen_to(PLAIN, ("", ""), 0)
            self.put(" ")
        else:
            appearance = cell.appearance
            self.pen_to(appearance.rendition, (appearance.hyperlink_id, appearance.hyperlink), protection_of(cell))
            self.put(cell.char)
        self.pen_to(rendition, hyperlink, protection)

    def charsets(self, g_charsets: list, gl: int) -> None:
        for slot, table in enumerate(g_charsets):
            if table is not self.g_charsets[slot]:
                code = _DESIGNATION.get(id(table))
                if code is not None:
                    self.put(control.ESC + _SLOTS[slot] + code)
                    self.g_charsets[slot] = table
        if gl != self.gl:
            self.put(_SHIFTS[gl])
            self.gl = gl
