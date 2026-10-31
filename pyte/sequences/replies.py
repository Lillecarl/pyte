"""
Any answer a terminal gives, read once into the class that names it.

    >>> parse_reply("\\x1b[?2026;1$y")
    ModeReport(mode=<PrivateMode.SYNCHRONIZED_OUTPUT: 2026>, state=<ModeState.SET: 1>, private=True)

A reader matches on the type:

    match parse_reply(text):
        case ModeReport(mode=PrivateMode.SYNCHRONIZED_OUTPUT) as report:
            ...
        case StatusReport():
            ...

A string sequence that no class here names comes back as the
`StringSequence` it is: a terminal answers in APC, DCS and OSC for
protocols pyte has no class for, and the bytes are a reply all the
same. A CSI sequence that no class names is None, because it may be a
key.
"""

from __future__ import annotations

from .csi import CsiSequence
from .kitty_graphics import GraphicsReply
from .reports import (
    CellSizeReport,
    ColorSchemeReport,
    CursorPositionReport,
    DeviceAttributes,
    FocusReport,
    InBandSizeReport,
    KeyboardFlagsReport,
    ModeReport,
    SgrMouseReport,
    StatusReport,
    TextAreaCellsReport,
    TextAreaPixelsReport,
)
from .strings import OscString, SettingReport, StringSequence, VersionReport

__all__ = ("Reply", "parse_reply")

Reply = (
    CellSizeReport
    | ColorSchemeReport
    | CursorPositionReport
    | DeviceAttributes
    | FocusReport
    | GraphicsReply
    | InBandSizeReport
    | KeyboardFlagsReport
    | ModeReport
    | OscString
    | SettingReport
    | SgrMouseReport
    | StatusReport
    | StringSequence
    | TextAreaCellsReport
    | TextAreaPixelsReport
    | VersionReport
)

#: The readers of a CSI reply, each tried on the one sequence read.
_CSI_REPLIES = (
    ModeReport,
    CursorPositionReport,
    DeviceAttributes,
    StatusReport,
    ColorSchemeReport,
    CellSizeReport,
    TextAreaPixelsReport,
    TextAreaCellsReport,
    InBandSizeReport,
    KeyboardFlagsReport,
    FocusReport,
    SgrMouseReport,
)

#: The readers of a string reply.
_STRING_REPLIES = (OscString, SettingReport, VersionReport, GraphicsReply)


def parse_reply(text: str) -> Reply | None:
    "The reply `text` is, whole, or None."
    sequence = CsiSequence.parse(text)
    if sequence is not None:
        for kind in _CSI_REPLIES:
            reply = kind.read(sequence)
            if reply is not None:
                return reply
        return None
    string = StringSequence.parse(text)
    if string is None:
        return None
    for kind in _STRING_REPLIES:
        reply = kind.read(string)
        if reply is not None:
            return reply
    return string
