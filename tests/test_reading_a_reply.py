"""
A terminal's answer, read into the class that names it, and written back.

Each class in `pyte.sequences` both writes its sequence and reads it,
so the one test every class owes is the round trip: what it writes, it
reads back as itself. The rest pins the bytes real terminals send,
which are what a reader meets, and the near misses each must refuse.
"""

from __future__ import annotations

import pytest

from pyte.keys.events import KeyboardFlag
from pyte.modes import AnsiMode, ModeState, PrivateMode
from pyte.sequences.csi import Csi, CsiSequence, Marker, ask_mode
from pyte.sequences.kitty_graphics import GraphicsReply
from pyte.sequences.replies import parse_reply
from pyte.sequences.reports import (
    AttributesKind,
    CellSizeReport,
    ColorScheme,
    ColorSchemeReport,
    CursorPositionReport,
    DeviceAttributes,
    DeviceStatus,
    FocusReport,
    InBandSizeReport,
    KeyboardFlagsReport,
    KeyOptionReport,
    ModeReport,
    ScreenCellsReport,
    ScreenPixelsReport,
    SgrMouseReport,
    StatusReport,
    TextAreaCellsReport,
    TextAreaPixelsReport,
)
from pyte.sequences.strings import (
    CapabilityReport,
    ChecksumReport,
    OscString,
    SettingReport,
    StringKind,
    StringSequence,
    Terminator,
    TitleKind,
    TitleReport,
    VersionReport,
)

EVERY_REPLY = [
    ModeReport(PrivateMode.SYNCHRONIZED_OUTPUT, ModeState.SET),
    ModeReport(AnsiMode.INSERT_REPLACE, ModeState.RESET, private=False),
    ModeReport(9999, ModeState.UNKNOWN),
    CursorPositionReport(2, 3),
    CursorPositionReport(2, 3, page=1),
    DeviceAttributes(AttributesKind.PRIMARY, (62, 4, 22)),
    DeviceAttributes(AttributesKind.SECONDARY, (1, 4000, 29)),
    StatusReport(DeviceStatus.OK),
    StatusReport(DeviceStatus.MALFUNCTION),
    ColorSchemeReport(ColorScheme.DARK),
    CellSizeReport(height=20, width=10),
    TextAreaPixelsReport(height=480, width=800),
    TextAreaCellsReport(rows=24, columns=80),
    ScreenPixelsReport(height=1080, width=1920),
    ScreenCellsReport(rows=54, columns=192),
    InBandSizeReport(rows=24, columns=80, height=480, width=800),
    KeyboardFlagsReport(KeyboardFlag(31)),
    KeyOptionReport(Csi.XTMODKEYS, 4, 2),
    KeyOptionReport(Csi.XTFMTKEYS, 4, 1),
    FocusReport(True),
    FocusReport(False),
    SgrMouseReport(65, 10, 5),
    SgrMouseReport(0, 1, 1, released=True),
    OscString("11", "rgb:0000/0000/0000"),
    OscString("104"),
    SettingReport("0;38:2::1:2:3m"),
    SettingReport(code=0),
    SettingReport("m", code=None),
    VersionReport("kitty(0.39.1)"),
    ChecksumReport(1, 0xFF3A),
    CapabilityReport("544e", "xterm"),
    CapabilityReport("524742"),
    CapabilityReport("6e6f6e65", known=False),
    TitleReport(TitleKind.WINDOW, "vim"),
    TitleReport(TitleKind.ICON, ""),
    GraphicsReply(31, "OK"),
    GraphicsReply(7, "ENOENT:no such image", placement_id=2),
]


@pytest.mark.parametrize("reply", EVERY_REPLY, ids=repr)
def test_what_a_reply_writes_it_reads_back(reply):
    assert type(reply).parse(str(reply)) == reply
    assert parse_reply(str(reply)) == reply


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Ghostty, asked whether it holds a frame back.
        ("\x1b[?2026;2$y", ModeReport(PrivateMode.SYNCHRONIZED_OUTPUT, ModeState.RESET)),
        # iTerm2 says a mode can never be on.
        ("\x1b[?1016;4$y", ModeReport(PrivateMode.SGR_PIXEL_MOUSE, ModeState.PERMANENTLY_RESET)),
        ("\x1b[?62;4;22c", DeviceAttributes(AttributesKind.PRIMARY, (62, 4, 22))),
        ("\x1b[>1;4000;29c", DeviceAttributes(AttributesKind.SECONDARY, (1, 4000, 29))),
        ("\x1b[0n", StatusReport()),
        ("\x1b[?997;2n", ColorSchemeReport(ColorScheme.LIGHT)),
        ("\x1b[6;35;19t", CellSizeReport(height=35, width=19)),
        ("\x1b[48;90;300;1800;3000t", InBandSizeReport(rows=90, columns=300, height=1800, width=3000)),
        # A terminal with every flag off answers with an empty one.
        ("\x1b[?u", KeyboardFlagsReport(KeyboardFlag(0))),
        ("\x1b[I", FocusReport(True)),
        ("\x1b[<64;60;10M", SgrMouseReport(64, 60, 10)),
        # A colour answer ends at a bell, the way most terminals end one.
        ("\x1b]11;rgb:1e1e/1e1e/2e2e\x07", OscString("11", "rgb:1e1e/1e1e/2e2e", Terminator.BEL)),
        # And in its 8-bit form.
        ("\x9d10;rgb:ffff/ffff/ffff\x9c", OscString("10", "rgb:ffff/ffff/ffff", Terminator.ST_C1)),
        ("\x1bP>|WezTerm 20240203\x1b\\", VersionReport("WezTerm 20240203")),
        # xterm, asked for TN.
        ("\x1bP1+r544e=787465726d\x1b\\", CapabilityReport("544e", "xterm")),
        ("\x1b_Gi=31,p=0;OK\x1b\\", GraphicsReply(31, "OK", placement_id=0)),
    ],
)
def test_what_a_terminal_sends_is_read(text, expected):
    assert parse_reply(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # A key, not a reply: F1, and an arrow.
        "\x1bOP",
        "\x1b[A",
        # A sequence cut short.
        "\x1b[?2026;1$",
        "\x1b]11;rgb:0000/0000/0000",
        # Plain text.
        "hello",
        "",
    ],
)
def test_what_is_no_reply_is_none(text):
    assert parse_reply(text) is None


def test_a_mode_nobody_names_keeps_its_number():
    report = ModeReport.parse("\x1b[?9999;1$y")
    assert report == ModeReport(9999, ModeState.SET)
    assert report is not None and report.is_set and report.is_known


def test_a_report_that_is_not_its_own_is_refused():
    "Each reader asks for its own marker and its own count."
    assert ModeReport.parse("\x1b[>2026;1$y") is None
    assert ColorSchemeReport.parse("\x1b[?996;1n") is None
    assert CellSizeReport.parse("\x1b[4;20;10t") is None
    assert StatusReport.parse("\x1b[5n") is None
    assert SgrMouseReport.parse("\x1b[64;60;10M") is None


def test_a_string_no_class_names_is_still_a_reply():
    "A terminal answers in protocols pyte has no class for, and they must not reach a pane."
    # DECRPTUI, the answer to DA3.
    assert parse_reply("\x1bP!|00000000\x1b\\") == StringSequence(StringKind.DCS, "!|00000000")


def test_an_apc_does_not_end_at_a_bell():
    assert StringSequence.parse("\x1b_Gi=1;OK\x07") is None


def test_a_cursor_position_is_a_reply_and_a_key_alike():
    "The reader of input decides: the bytes are F3 with control too."
    assert parse_reply("\x1b[1;5R") == CursorPositionReport(1, 5)


def test_a_sequence_keeps_what_it_was_written_with():
    sequence = CsiSequence.parse("\x1b[38;2:1:2:3;;5m")
    assert sequence == CsiSequence("m", (38, (2, 1, 2, 3), None, 5))
    assert str(sequence) == "\x1b[38;2:1:2:3;;5m"
    assert sequence.numbers() is None
    assert CsiSequence.parse("\x9b2T") == CsiSequence(Csi.SD, (2,))


def test_asking_for_a_mode_names_the_marker():
    assert ask_mode(PrivateMode.SYNCHRONIZED_OUTPUT) == "\x1b[?2026$p"
    assert ask_mode(AnsiMode.INSERT_REPLACE) == "\x1b[4$p"
    assert CsiSequence.parse(ask_mode(PrivateMode.SYNCHRONIZED_OUTPUT)) == CsiSequence(
        Csi.DECRQM, (PrivateMode.SYNCHRONIZED_OUTPUT,), Marker.QUESTION
    )
