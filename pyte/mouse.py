"""
What a program reads when the mouse does something over its screen.

Two choices of the program decide a report. The tracking mode says
which events go: presses and the wheel (1000), drags too (1002), or
every move (1003). The protocol says how they are spelled: X10 as
bytes, urxvt as shifted numbers in text, SGR as plain numbers with the
press and the release told apart by the final byte, and SGR in pixels
(1016). `mouse_report` reads both off the screen and writes the report.
A widget maps its own toolkit's events to a `MouseInput`.

The button number is kitty's arithmetic (`encode_mouse_event_impl` in
`kitty/mouse.c`): the button, then a bit each for the modifiers, motion
and the wheel. `ptterm/tests/test_mouse_against_kitty.py` holds every
cell report to kitty's own encoder.

The wheel on the alternate screen is not a report: there it moves the
cursor, `WHEEL_ARROWS` times `ARROWS_PER_WHEEL_STEP`, for a program that
asked for the alternate screen and no mouse. Lillecarl/pymux#422.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import TYPE_CHECKING, ClassVar

from .modes import PrivateMode
from .sequences.csi import CsiReport, CsiSequence
from .sequences.reports import SgrMouseReport

if TYPE_CHECKING:
    from .screen import Screen

__all__ = [
    "ARROWS_PER_WHEEL_STEP",
    "MODIFIERS",
    "NO_MODIFIERS",
    "WHEEL_ARROWS",
    "MouseAction",
    "MouseBits",
    "MouseButton",
    "MouseInput",
    "UrxvtMouseReport",
    "X10MouseReport",
    "mouse_report",
    "reports_mouse",
    "reports_pixels",
]


class MouseAction(IntEnum):
    "What the mouse did, in the terms every mode reports."

    PRESS = 1
    RELEASE = 2
    WHEEL_UP = 3
    WHEEL_DOWN = 4
    #: A move, with `MouseInput.button` held or `MouseButton.NONE`.
    MOVE = 5
    #: The pointer left the screen, from the cell it was last over.
    LEAVE = 6


class MouseButton(IntEnum):
    "The button, as the low two bits of a report number it."

    LEFT = 0
    MIDDLE = 1
    RIGHT = 2
    NONE = 3


class MouseBits(IntFlag):
    "The bits a report adds to the button. kitty's names end in `_INDICATOR`."

    SHIFT = 1 << 2
    ALT = 1 << 3
    CONTROL = 1 << 4
    MOTION = 1 << 5
    WHEEL = 1 << 6
    LEAVE = 1 << 8


#: The bits a person's keys add.
MODIFIERS = MouseBits.SHIFT | MouseBits.ALT | MouseBits.CONTROL
NO_MODIFIERS = MouseBits(0)


@dataclass(frozen=True)
class MouseInput:
    """
    One thing the mouse did, at a zero based cell of the page.

    `across` and `down` say where in that cell, as fractions: a report in
    pixels needs them. A terminal that reports cells leaves the middle.
    """

    action: MouseAction
    column: int
    row: int
    button: MouseButton = MouseButton.LEFT
    modifiers: MouseBits = NO_MODIFIERS
    across: float = 0.5
    down: float = 0.5


class _Tracking(IntEnum):
    "kitty's `MouseTrackingMode`."

    NONE = 0
    BUTTON = 1
    MOTION = 2
    ANY = 3


def _tracking(screen: Screen) -> _Tracking:
    """
    Which events the program asked for: the one of 1000, 1002 and 1003
    that is set, as `ONE_OF_A_GROUP` keeps it.
    """
    if PrivateMode.ANY_EVENT_MOUSE.flag in screen.mode:
        return _Tracking.ANY
    if PrivateMode.BUTTON_EVENT_MOUSE.flag in screen.mode:
        return _Tracking.MOTION
    if PrivateMode.MOUSE_REPORTING.flag in screen.mode:
        return _Tracking.BUTTON
    return _Tracking.NONE


#: A release is button three in every protocol but SGR: xterm's
#: `button.c` (ButtonRelease) and urxvt's own. kitty keeps the button
#: in urxvt, because its enum puts urxvt after SGR.
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
    """
    Whether the program on this screen asked for mouse reports. A
    protocol alone (1006 with no 1000) asks for none, in kitty and xterm.
    """
    return _tracking(screen) is not _Tracking.NONE


def reports_pixels(screen: Screen) -> bool:
    "Whether a report counts pixels (1016), so that a move inside one cell is news."
    return PrivateMode.SGR_PIXEL_MOUSE.flag in screen.mode


def _reported(tracking: _Tracking, mouse: MouseInput) -> bool:
    """
    kitty's `mouse_event` gate: 1003 sends every move, 1002 only a drag.
    A leave asks for no tracking mode (`set_currently_hovered_window`),
    and only 1016 spells one.
    """
    if mouse.action is MouseAction.LEAVE:
        return True
    if mouse.action is not MouseAction.MOVE:
        return tracking is not _Tracking.NONE
    if mouse.button is MouseButton.NONE:
        return tracking is _Tracking.ANY
    return tracking >= _Tracking.MOTION


def _button(mouse: MouseInput, sgr: bool) -> int:
    "The number a report writes for the button, before any protocol shifts it."
    if mouse.action is MouseAction.WHEEL_UP:
        number = MouseBits.WHEEL
    elif mouse.action is MouseAction.WHEEL_DOWN:
        number = MouseBits.WHEEL | 1
    elif mouse.action is MouseAction.RELEASE and not sgr:
        number = _RELEASE_BUTTON
    elif mouse.action is MouseAction.LEAVE:
        number = MouseBits.LEAVE | MouseBits.MOTION
    else:
        number = int(mouse.button)
        if mouse.action is MouseAction.MOVE:
            number |= MouseBits.MOTION
    return int(number | (mouse.modifiers & MODIFIERS))


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


def mouse_report(screen: Screen, mouse: MouseInput) -> CsiReport | None:
    """
    The report of `mouse`, for `Screen.encode_report`, or None when the
    screen's modes send nothing.

    A report is a C1 control that the terminal sends on its own, and
    S8C1T asks for one byte in front of it. xterm writes every one of
    them through `unparseputc1`, which is not a query only path.

    In pixels, the first pixel is 0, as kitty counts. A move inside one
    cell is a report of its own only there; the caller drops the rest.
    """
    if not _reported(_tracking(screen), mouse):
        return None
    if mouse.action is MouseAction.LEAVE and not reports_pixels(screen):
        return None
    column, row = mouse.column + 1, mouse.row + 1
    released = mouse.action is MouseAction.RELEASE
    if reports_pixels(screen):
        # C's round, as kitty calls it: a half goes up. Python's goes to even.
        x = math.floor((mouse.column + mouse.across) * screen.cell_width + 0.5)
        y = math.floor((mouse.row + mouse.down) * screen.cell_height + 0.5)
        return SgrMouseReport(_button(mouse, sgr=True), x, y, released=released)
    if PrivateMode.SGR_MOUSE.flag in screen.mode:
        return SgrMouseReport(_button(mouse, sgr=True), column, row, released=released)
    button = _button(mouse, sgr=False) + _BUTTON_OFFSET
    if PrivateMode.URXVT_MOUSE.flag in screen.mode:
        return UrxvtMouseReport(button, column, row)
    if mouse.column >= _X10_COLUMNS or mouse.row >= _X10_COLUMNS:
        return None
    return X10MouseReport(button, column, row)
