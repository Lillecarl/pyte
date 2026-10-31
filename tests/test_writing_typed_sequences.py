"""
The typed writers of `pyte.sequences`: each writes what its protocol says.

These hold the bytes as literals on purpose. A writer judged against
itself proves nothing, and these are the sequences a terminal reads.
"""

from __future__ import annotations

from pyte import escape
from pyte.images import PixelFormat
from pyte.keys.events import FlagsMode, KeyboardFlag
from pyte.parameters import EraseExtent
from pyte.sequences.csi import csi
from pyte.sequences.kitty_graphics import (
    GRAPHICS_START,
    Action,
    Delete,
    GraphicsCommand,
    GraphicsKey,
    Quiet,
    parse_control_data,
)
from pyte.sequences.kitty_keyboard import ask_flags, pop_flags, push_flags, set_flags
from pyte.sequences.rendition import ColorSpace, Sgr, sgr
from pyte.sequences.reports import ask_cursor_position, ask_status


def test_the_keyboard_flags_differ_by_their_marker_alone():
    assert push_flags(KeyboardFlag.DISAMBIGUATE | KeyboardFlag.REPORT_ALL_KEYS) == "\x1b[>9u"
    assert pop_flags() == "\x1b[<1u"
    assert pop_flags(3) == "\x1b[<3u"
    assert set_flags(KeyboardFlag.DISAMBIGUATE) == "\x1b[=1;1u"
    assert set_flags(KeyboardFlag.DISAMBIGUATE, FlagsMode.CLEAR_THE_BITS) == "\x1b[=1;3u"
    assert ask_flags() == "\x1b[?u"


def test_a_rendition_by_name():
    assert sgr() == "\x1b[m"
    assert sgr(Sgr.REVERSE) == "\x1b[7m"
    assert sgr(Sgr.FOREGROUND, ColorSpace.DIRECT, 1, 2, 3) == "\x1b[38;2;1;2;3m"
    assert sgr(Sgr.BACKGROUND, ColorSpace.INDEXED, 4) == "\x1b[48;5;4m"


def test_the_questions_a_terminal_answers():
    assert ask_status() == "\x1b[5n"
    assert ask_cursor_position() == "\x1b[6n"
    assert csi(escape.EL, EraseExtent.ALL) == "\x1b[2K"


def test_a_graphics_command_keeps_the_order_of_its_keys():
    command = GraphicsCommand(
        {GraphicsKey.ACTION: Action.DELETE, GraphicsKey.DELETE: Delete.ALL_AND_FREE, GraphicsKey.QUIET: Quiet.NOTHING}
    )
    assert str(command) == "\x1b_Ga=d,d=A,q=2\x1b\\"
    assert str(command).startswith(GRAPHICS_START)


def test_a_graphics_payload_of_none_writes_no_separator():
    "An empty payload is the last chunk of an empty image, and keeps its ';'."
    keys = {GraphicsKey.MORE: 0}
    assert str(GraphicsCommand(keys)) == "\x1b_Gm=0\x1b\\"
    assert str(GraphicsCommand(keys, "")) == "\x1b_Gm=0;\x1b\\"
    assert str(GraphicsCommand(keys, "QUJD")) == "\x1b_Gm=0;QUJD\x1b\\"


def test_what_a_command_writes_the_screen_reads_back():
    command = GraphicsCommand(
        {GraphicsKey.ACTION: Action.TRANSMIT, GraphicsKey.IMAGE_ID: 7, GraphicsKey.FORMAT: PixelFormat.RGBA},
        "QUJD",
    )
    body = str(command)[len(GRAPHICS_START) : -len("\x1b\\")]
    assert parse_control_data(body) == ({"a": "t", "i": "7", "f": "32"}, "QUJD")


def test_a_frame_edit_names_the_letters_it_reuses():
    "r and X mean the frame and the composition in an edit; the names are aliases."
    assert GraphicsKey.EDIT_FRAME is GraphicsKey.ROWS
    assert GraphicsKey.COMPOSITION is GraphicsKey.CELL_X
