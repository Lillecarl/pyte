"""
What a program reads when the mouse does something over its screen.

A program asks for reports with one of three modes, and each one spells
the same button differently: X10 as bytes, urxvt as shifted numbers in
text, SGR as plain numbers with the press and the release told apart by
the final byte. `mouse_report` picks the mode the screen is in and
writes the report. A widget maps its own toolkit's events to a
`MouseAction` and hands the answer to `Screen.reply_csi`.

The wheel on the alternate screen is not a report: there it moves the
cursor, `WHEEL_ARROWS` times `ARROWS_PER_WHEEL_STEP`, for a program that
asked for the alternate screen and no mouse. Lillecarl/pymux#422.
"""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .screen import Screen

__all__ = ["ARROWS_PER_WHEEL_STEP", "WHEEL_ARROWS", "MouseAction", "mouse_report", "reports_mouse"]


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

#: X10 writes each coordinate as one byte as well, one based and
#: shifted by the same 32. So a zero based column travels as `x + 33`.
_COORDINATE_OFFSET = _BUTTON_OFFSET + 1

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

#: The button that SGR writes, and the final byte that says whether the
#: press went down or came up. SGR is the only protocol that tells them
#: apart that way, and the only one that leaves the button unshifted.
_SGR_BUTTONS = {
    MouseAction.PRESS: (0, "M"),
    MouseAction.RELEASE: (0, "m"),
    MouseAction.WHEEL_UP: (_WHEEL, "M"),
    MouseAction.WHEEL_DOWN: (_WHEEL + 1, "M"),
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


def mouse_report(screen: Screen, action: MouseAction, column: int, row: int) -> str | None:
    """
    The report of `action` at a zero based cell, as the body of a CSI
    for `Screen.reply_csi`, or None when the screen's mode sends nothing.

    `reply_csi` and not a literal "\\x1b[": a mouse report is a C1
    control that the terminal sends on its own, and S8C1T asks for one
    byte in front of it. xterm writes every one of them through
    `unparseputc1`, which is not a query only path.
    """
    if screen.sgr_mouse_support_enabled:
        # Xterm SGR mode: the button as text, and the final byte says
        # press or release.
        button, final = _SGR_BUTTONS[action]
        return f"<{button};{column + 1};{row + 1}{final}"
    if screen.urxvt_mouse_support_enabled:
        # Urxvt mode: the shifted button as text, and always "M". A
        # release is button three, so the two are told apart by the
        # button and not by the final byte.
        return f"{_SHIFTED_BUTTONS[action]};{column + 1};{row + 1}M"
    if screen.mouse_support_enabled:
        # X10: the same shifted button, written as one byte, and the
        # two coordinates after it.
        if column >= _X10_COLUMNS or row >= _X10_COLUMNS:
            return None
        return "M%s%s%s" % (
            chr(_SHIFTED_BUTTONS[action]),
            _one_byte(column + _COORDINATE_OFFSET),
            _one_byte(row + _COORDINATE_OFFSET),
        )
    return None
