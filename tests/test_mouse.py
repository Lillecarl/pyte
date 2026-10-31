"""
The mouse report a program reads, by the mode it asked for.

These read what `mouse_report` answers, which is the body of a CSI.
`ptterm/tests/test_the_widget.py` reads the same reports off the wire,
through a widget.
"""

from __future__ import annotations

import pytest

from pyte.modes import PrivateMode
from pyte.mouse import MouseAction, mouse_report, reports_mouse
from pyte.screen import Screen
from pyte.sequences.csi import set_mode
from pyte.streams import Stream


def screen_in(*modes: PrivateMode) -> Screen:
    screen = Screen(24, 300, write_process_input=lambda data: None)
    stream = Stream(screen)
    for mode in modes:
        stream.feed(set_mode(mode))
    return screen


def test_a_screen_that_asked_for_nothing_reports_nothing():
    screen = screen_in()
    assert not reports_mouse(screen)
    assert mouse_report(screen, MouseAction.PRESS, 0, 0) is None


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
    assert mouse_report(screen, action, 2, 1) == report


def test_urxvt_tells_a_release_by_button_three():
    screen = screen_in(PrivateMode.MOUSE_REPORTING, PrivateMode.URXVT_MOUSE)
    assert mouse_report(screen, MouseAction.PRESS, 2, 1) == "32;3;2M"
    assert mouse_report(screen, MouseAction.RELEASE, 2, 1) == "35;3;2M"


def test_x10_writes_a_coordinate_over_127_as_one_byte():
    "chr(128) is two bytes in UTF-8; a surrogate is one. Lillecarl/pymux#139."
    screen = screen_in(PrivateMode.MOUSE_REPORTING)
    assert mouse_report(screen, MouseAction.PRESS, 95, 1) == "M \udc80\x22"


def test_x10_sends_nothing_past_its_last_column():
    screen = screen_in(PrivateMode.MOUSE_REPORTING)
    assert mouse_report(screen, MouseAction.PRESS, 222, 0) is not None
    assert mouse_report(screen, MouseAction.PRESS, 223, 0) is None
