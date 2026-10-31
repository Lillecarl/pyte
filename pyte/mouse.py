"""
What a program reads when the mouse does something over its screen.

A program asks for reports with one of three modes, and each one spells
the same button differently: X10 as bytes, urxvt as shifted numbers in
text, SGR as plain numbers with the press and the release told apart by
the final byte. `mouse_report` picks the mode the screen is in and
writes the report. A widget maps its own toolkit's events to a
`MouseAction` and hands the report to `Screen.reply`.

The wheel on the alternate screen is not a report: there it moves the
cursor, `WHEEL_ARROWS` times `ARROWS_PER_WHEEL_STEP`, for a program that
asked for the alternate screen and no mouse. Lillecarl/pymux#422.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, ClassVar

from .sequences.csi import CsiReport, CsiSequence
from .sequences.reports import SgrMouseReport

if TYPE_CHECKING:
    from .screen import Screen

__all__ = [
    "ARROWS_PER_WHEEL_STEP",
    "WHEEL_ARROWS",
    "MouseAction",
    "UrxvtMouseReport",
    "X10MouseReport",
    "mouse_report",
    "reports_mouse",
]


class MouseAction(IntEnum):
    "What the mouse did, in the terms every mode reports."

    PRESS = 1
    RELEASE = 2
    WHEEL_UP = 3
    WHEEL_DOWN = 4


#: Bit six of the button says the event came from the wheel, so the two
#: wheel directions are the button numbers 64 and 65. kitty calls it
#: `SCROLL_BUTTON_INDICATOR` in `kitty/mouse.c`.
_WHEEL = 1 << 6

#: A release is button three in every protocol older than SGR. kitty:
#: "action == RELEASE && mouse_tracking_protocol < SGR_PROTOCOL".
_RELEASE_BUTTON = 3

#: X10 and urxvt shift the button by 32, so that X10 can write it as a
#: printable byte. SGR does not: it writes the number as text, which is
#: the reason that protocol exists. kitty adds the same 32 in
#: `encode_mouse_event_impl`, for the urxvt and the X10 cases only.
_BUTTON_OFFSET = 32

#: How far to the right and how far down an X10 report reaches.
#:
#: This is X10's own limit. A coordinate byte holds `223 + 32` and no
#: more, and kitty writes the same bound as
#: "if (x > 223 || y > 223) return 0", counting from one. A press
#: further out sends nothing, which is what kitty does with it.
#:
#: It was 96, which is narrower than a great many panes: a press past
#: column 96 went nowhere. Lillecarl/pymux#139.
_X10_COLUMNS = 223

#: The button that SGR writes, and whether it was a release, which SGR
#: writes as the final byte. SGR is the only protocol that tells them
#: apart that way, and the only one that leaves the button unshifted.
_SGR_BUTTONS = {
    MouseAction.PRESS: (0, False),
    MouseAction.RELEASE: (0, True),
    MouseAction.WHEEL_UP: (_WHEEL, False),
    MouseAction.WHEEL_DOWN: (_WHEEL + 1, False),
}

#: The button that urxvt and X10 write. One table, because the two
#: protocols encode the same number and differ only in how they spell
#: it: urxvt as text, X10 as one byte.
_SHIFTED_BUTTONS = {
    MouseAction.PRESS: _BUTTON_OFFSET,
    MouseAction.RELEASE: _RELEASE_BUTTON + _BUTTON_OFFSET,
    MouseAction.WHEEL_UP: _WHEEL + _BUTTON_OFFSET,
    MouseAction.WHEEL_DOWN: _WHEEL + 1 + _BUTTON_OFFSET,
}

#: The key a wheel step is on the alternate screen, before the keyboard
#: mode of the pane spells it.
WHEEL_ARROWS = {
    MouseAction.WHEEL_UP: "\x1b[A",
    MouseAction.WHEEL_DOWN: "\x1b[B",
}

#: What xterm (`scroll-back(5,line)`) and kitty (`wheel_scroll_multiplier`)
#: send by default. The outer terminal reports one event per notch
#: while pymux holds the mouse, so this is the whole step.
ARROWS_PER_WHEEL_STEP = 5


def _one_byte(value: int) -> str:
    """
    One byte of an X10 mouse report, as a character the backend writes
    as that byte and nothing else.

    A value above 127 is a byte and not a character, so UTF-8 has no
    one byte spelling for it: `chr(128)` went out as two, and the
    program read the first as the column and the second as the row.

    It travels as a surrogate instead, which is Python's channel for a
    byte that is not a character, and `ptyhost/backends/posix.py`
    encodes it back with "surrogateescape". `Screen._control` spells the
    eight bit C1 controls the same way. Lillecarl/pymux#139.
    """
    if value < 0x80:
        return chr(value)
    return chr(0xDC00 + value)


def reports_mouse(screen: Screen) -> bool:
    "Whether the program on this screen asked for mouse reports, in any mode."
    return screen.sgr_mouse_support_enabled or screen.urxvt_mouse_support_enabled or screen.mouse_support_enabled


@dataclass(frozen=True)
class UrxvtMouseReport(CsiReport):
    """
    urxvt's report: "CSI button ; column ; row M", the button shifted
    and the cell counted from one. A release is button three, so the
    final byte is always "M".
    """

    FINAL: ClassVar[str] = "M"

    button: int
    column: int
    row: int

    def sequence(self) -> CsiSequence:
        return CsiSequence(self.FINAL, (self.button, self.column, self.row))


@dataclass(frozen=True)
class X10MouseReport(CsiReport):
    """
    X10's report: "CSI M" and three bytes, the shifted button and the
    cell, each coordinate one based and shifted by 32.

    The bytes are not parameters, so the report has a body and no
    `sequence()`.
    """

    FINAL: ClassVar[str] = "M"

    button: int
    column: int
    row: int

    def body(self) -> str:
        return "%s%s%s%s" % (
            self.FINAL,
            chr(self.button),
            _one_byte(self.column + _BUTTON_OFFSET),
            _one_byte(self.row + _BUTTON_OFFSET),
        )


def mouse_report(screen: Screen, action: MouseAction, column: int, row: int) -> CsiReport | None:
    """
    The report of `action` at a zero based cell, for `Screen.reply`, or
    None when the screen's mode sends nothing.

    `Screen.reply` and not `str()`: a mouse report is a C1 control that
    the terminal sends on its own, and S8C1T asks for one byte in front
    of it. xterm writes every one of them through `unparseputc1`, which
    is not a query only path.
    """
    if screen.sgr_mouse_support_enabled:
        button, released = _SGR_BUTTONS[action]
        return SgrMouseReport(button, column + 1, row + 1, released=released)
    if screen.urxvt_mouse_support_enabled:
        return UrxvtMouseReport(_SHIFTED_BUTTONS[action], column + 1, row + 1)
    if screen.mouse_support_enabled:
        if column >= _X10_COLUMNS or row >= _X10_COLUMNS:
            return None
        return X10MouseReport(_SHIFTED_BUTTONS[action], column + 1, row + 1)
    return None
