"""
XTSAVE and XTRESTORE: putting private modes away and bringing them back.

A program that wants to change a mode and give it back the way it
found it saves it first. The two commands share their final byte with
DECSLRM and DECSTBM, and the private marker says which is meant.
"""

from __future__ import annotations

import pytest

from pyte import escape
from pyte.modes import AnsiMode, PrivateMode, flag_of
from pyte.screen import Screen
from pyte.sequences.csi import Csi, Marker, csi, reset_mode, set_mode
from pyte.streams import Stream


@pytest.fixture
def pane():
    responses = []
    screen = Screen(24, 80, write_process_input=responses.append)
    return screen, Stream(screen), responses


def is_set(screen, number):
    "True while the private mode `number` is set."
    return flag_of(number) in screen.mode


def test_a_saved_mode_comes_back_as_it_was(pane):
    screen, stream, _responses = pane
    stream.feed(set_mode(PrivateMode.AUTOWRAP))  # Autowrap on.
    stream.feed(csi(Csi.DECSLRM, 7, private=Marker.QUESTION))  # Save it.
    stream.feed(reset_mode(PrivateMode.AUTOWRAP))  # Off.
    assert not is_set(screen, 7)
    stream.feed(csi(escape.DECSTBM, 7, private=Marker.QUESTION))  # Back.
    assert is_set(screen, 7)


def test_a_mode_saved_while_off_comes_back_off(pane):
    screen, stream, _responses = pane
    stream.feed(reset_mode(PrivateMode.AUTOWRAP))
    stream.feed(csi(Csi.DECSLRM, 7, private=Marker.QUESTION))
    stream.feed(set_mode(PrivateMode.AUTOWRAP))
    assert is_set(screen, 7)
    stream.feed(csi(escape.DECSTBM, 7, private=Marker.QUESTION))
    assert not is_set(screen, 7)


def test_one_sequence_saves_several_modes(pane):
    screen, stream, _responses = pane
    stream.feed(set_mode(PrivateMode.AUTOWRAP) + reset_mode(PrivateMode.SHOW_CURSOR))
    stream.feed(csi(Csi.DECSLRM, 7, 25, private=Marker.QUESTION))
    stream.feed(reset_mode(PrivateMode.AUTOWRAP) + set_mode(PrivateMode.SHOW_CURSOR))
    stream.feed(csi(escape.DECSTBM, 7, 25, private=Marker.QUESTION))
    assert is_set(screen, 7)
    assert not is_set(screen, 25)


def test_a_mode_that_no_terminal_carries_is_saved_as_off(pane):
    # A program may save and read back anything, so the number does
    # not have to name a mode that this pane knows.
    screen, stream, _responses = pane
    stream.feed(csi(Csi.DECSLRM, 12345, private=Marker.QUESTION))
    assert screen.saved_modes == {12345: False}


def test_restoring_a_mode_that_was_never_saved_changes_nothing(pane):
    screen, stream, _responses = pane
    stream.feed(set_mode(PrivateMode.AUTOWRAP))
    stream.feed(csi(escape.DECSTBM, 7, private=Marker.QUESTION))
    assert is_set(screen, 7)


def test_no_number_saves_and_restores_kittys_set(pane):
    "kitty's form: every mode that moves nothing, ANSI ones included."
    screen, stream, _responses = pane
    on = [PrivateMode.BRACKETED_PASTE, PrivateMode.SGR_MOUSE, PrivateMode.BUTTON_EVENT_MOUSE]
    stream.feed("".join(set_mode(mode) for mode in on) + reset_mode(PrivateMode.SHOW_CURSOR))
    stream.feed(csi(escape.SM, AnsiMode.INSERT_REPLACE))
    stream.feed(csi(Csi.DECSLRM, private=Marker.QUESTION))
    stream.feed("".join(reset_mode(mode) for mode in on) + set_mode(PrivateMode.SHOW_CURSOR))
    stream.feed(set_mode(PrivateMode.ANY_EVENT_MOUSE) + csi(escape.RM, AnsiMode.INSERT_REPLACE))
    stream.feed(csi(escape.DECSTBM, private=Marker.QUESTION))
    assert all(is_set(screen, mode) for mode in on)
    assert not is_set(screen, PrivateMode.ANY_EVENT_MOUSE)
    assert not is_set(screen, PrivateMode.SHOW_CURSOR)
    assert not screen.page.show_cursor
    assert AnsiMode.INSERT_REPLACE in screen.mode


def test_no_number_leaves_a_mode_that_moves_the_screen(pane):
    "Origin mode homes the cursor, so kitty leaves it out of the set."
    screen, stream, _responses = pane
    stream.feed(csi(Csi.DECSLRM, private=Marker.QUESTION))
    stream.feed(set_mode(PrivateMode.ORIGIN))
    stream.feed(csi(escape.DECSTBM, private=Marker.QUESTION))
    assert is_set(screen, PrivateMode.ORIGIN)


def test_restoring_inband_resize_sends_no_report(pane):
    screen, stream, responses = pane
    stream.feed(set_mode(PrivateMode.INBAND_RESIZE) + csi(Csi.DECSLRM, private=Marker.QUESTION))
    stream.feed(reset_mode(PrivateMode.INBAND_RESIZE))
    responses.clear()
    stream.feed(csi(escape.DECSTBM, private=Marker.QUESTION))
    assert is_set(screen, PrivateMode.INBAND_RESIZE)
    assert responses == []


def test_the_private_marker_tells_a_save_from_a_region(pane):
    # "CSI Pl ; Pr s" names a region and "CSI ? Pm s" puts modes away.
    # One final byte, two commands.
    screen, stream, _responses = pane
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 3, 20))
    assert screen.horizontal_margins == (2, 19)
    stream.feed(csi(Csi.DECSLRM, 7, private=Marker.QUESTION))
    assert screen.horizontal_margins == (2, 19)
    assert 7 in screen.saved_modes


def test_the_private_marker_tells_a_restore_from_a_region(pane):
    # "CSI Pt ; Pb r" names a region and "CSI ? Pm r" brings modes back.
    screen, stream, _responses = pane
    stream.feed(csi(escape.DECSTBM, 3, 20))
    assert screen.margins == (2, 19)
    stream.feed(csi(escape.DECSTBM, 7, private=Marker.QUESTION))
    assert screen.margins == (2, 19)


def test_a_region_without_the_marker_still_reaches_decstbm(pane):
    # The private branch must not swallow the plain form.
    screen, stream, _responses = pane
    stream.feed(csi(escape.DECSTBM, 5, 20))
    assert screen.margins == (4, 19)
