"""
The mouse report a program reads, by the modes it asked for.

These read the body of what `mouse_report` answers: what follows the CSI.
`ptterm/tests/test_the_widget.py` reads the same reports off the wire,
through a widget, and `ptterm/tests/test_mouse_against_kitty.py` holds
the cell reports to kitty's encoder.
"""

from __future__ import annotations

import pytest

from pyte.modes import PrivateMode
from pyte.mouse import MouseAction, MouseBits, MouseButton, MouseInput, mouse_report, reports_mouse
from pyte.screen import Screen
from pyte.sequences.csi import set_mode
from pyte.streams import Stream


def screen_in(*modes: PrivateMode) -> Screen:
    screen = Screen(24, 300, write_process_input=lambda data: None)
    stream = Stream(screen)
    for mode in modes:
        stream.feed(set_mode(mode))
    return screen


def body(screen: Screen, action: MouseAction, column: int, row: int, **more) -> str:
    report = mouse_report(screen, MouseInput(action, column, row, **more))
    assert report is not None
    return report.body()


def test_a_screen_that_asked_for_nothing_reports_nothing():
    screen = screen_in()
    assert not reports_mouse(screen)
    assert mouse_report(screen, MouseInput(MouseAction.PRESS, 0, 0)) is None


def test_a_protocol_alone_asks_for_no_reports():
    "1006 says how to spell a report, not that one goes."
    screen = screen_in(PrivateMode.SGR_MOUSE)
    assert not reports_mouse(screen)
    assert mouse_report(screen, MouseInput(MouseAction.PRESS, 0, 0)) is None


@pytest.mark.parametrize(
    ("action", "report"),
    [
        (MouseAction.PRESS, "<0;3;2M"),
        (MouseAction.RELEASE, "<0;3;2m"),
        (MouseAction.WHEEL_UP, "<64;3;2M"),
        (MouseAction.WHEEL_DOWN, "<65;3;2M"),
    ],
)
def test_sgr_tells_a_release_by_the_final_byte(action, report):
    screen = screen_in(PrivateMode.MOUSE_REPORTING, PrivateMode.SGR_MOUSE)
    assert body(screen, action, 2, 1) == report


@pytest.mark.parametrize(
    ("button", "report"),
    [(MouseButton.LEFT, "<0;1;1M"), (MouseButton.MIDDLE, "<1;1;1M"), (MouseButton.RIGHT, "<2;1;1M")],
)
def test_a_press_names_its_button(button, report):
    screen = screen_in(PrivateMode.MOUSE_REPORTING, PrivateMode.SGR_MOUSE)
    assert body(screen, MouseAction.PRESS, 0, 0, button=button) == report


def test_a_press_carries_the_modifiers():
    screen = screen_in(PrivateMode.MOUSE_REPORTING, PrivateMode.SGR_MOUSE)
    modifiers = MouseBits.SHIFT | MouseBits.CONTROL
    assert body(screen, MouseAction.PRESS, 0, 0, button=MouseButton.RIGHT, modifiers=modifiers) == "<22;1;1M"


def test_button_tracking_sends_no_move():
    screen = screen_in(PrivateMode.MOUSE_REPORTING, PrivateMode.SGR_MOUSE)
    assert mouse_report(screen, MouseInput(MouseAction.MOVE, 0, 0)) is None
    assert mouse_report(screen, MouseInput(MouseAction.MOVE, 0, 0, button=MouseButton.NONE)) is None


def test_motion_tracking_sends_a_drag_and_no_hover():
    screen = screen_in(PrivateMode.BUTTON_EVENT_MOUSE, PrivateMode.SGR_MOUSE)
    assert body(screen, MouseAction.MOVE, 0, 0, button=MouseButton.MIDDLE) == "<33;1;1M"
    assert mouse_report(screen, MouseInput(MouseAction.MOVE, 0, 0, button=MouseButton.NONE)) is None


def test_any_tracking_sends_a_hover():
    screen = screen_in(PrivateMode.ANY_EVENT_MOUSE, PrivateMode.SGR_MOUSE)
    assert body(screen, MouseAction.MOVE, 4, 2, button=MouseButton.NONE) == "<35;5;3M"


def test_pixels_count_from_zero_at_the_cell_size():
    "Column 2, a quarter across, on a 10x20 cell: pixel 22.5, which C's round makes 23."
    screen = screen_in(PrivateMode.ANY_EVENT_MOUSE, PrivateMode.SGR_PIXEL_MOUSE)
    screen.set_cell_size(10, 20)
    assert body(screen, MouseAction.PRESS, 2, 1, across=0.25, down=0.5) == "<0;23;30M"
    assert body(screen, MouseAction.RELEASE, 0, 0, across=0.0, down=0.0) == "<0;0;0m"


def test_a_leave_is_a_pixel_motion_report_in_any_tracking_mode():
    "kitty's leave: 256 and the motion bit, in 1016 alone. Lillecarl/pymux#899."
    screen = screen_in(PrivateMode.SGR_PIXEL_MOUSE)
    assert body(screen, MouseAction.LEAVE, 0, 0, button=MouseButton.NONE) == "<288;5;10M"
    screen = screen_in(PrivateMode.ANY_EVENT_MOUSE, PrivateMode.SGR_MOUSE)
    assert mouse_report(screen, MouseInput(MouseAction.LEAVE, 0, 0)) is None


def test_urxvt_tells_a_release_by_button_three():
    screen = screen_in(PrivateMode.MOUSE_REPORTING, PrivateMode.URXVT_MOUSE)
    assert body(screen, MouseAction.PRESS, 2, 1) == "32;3;2M"
    assert body(screen, MouseAction.RELEASE, 2, 1, button=MouseButton.RIGHT) == "35;3;2M"


def test_x10_writes_a_coordinate_over_127_as_one_byte():
    "chr(128) is two bytes in UTF-8; a surrogate is one. Lillecarl/pymux#139."
    screen = screen_in(PrivateMode.MOUSE_REPORTING)
    assert body(screen, MouseAction.PRESS, 95, 1) == "M \udc80\x22"


def test_x10_sends_nothing_past_its_last_column():
    screen = screen_in(PrivateMode.MOUSE_REPORTING)
    assert mouse_report(screen, MouseInput(MouseAction.PRESS, 222, 0)) is not None
    assert mouse_report(screen, MouseInput(MouseAction.PRESS, 223, 0)) is None
