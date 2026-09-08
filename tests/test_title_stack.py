"""
The window title and the icon label, and the stack that holds them.

"CSI 20 t" and "CSI 21 t" ask for them. "CSI 22 t" remembers them and
"CSI 23 t" brings them back, which is what a program does around a
title of its own. A pane has both, so it answers all four.
"""
from pyte.screen import Screen
from pyte.streams import Stream
from pyte.sequences import Csi, csi
from pyte import escape
from pyte.sequences import esc


def _screen(lines=5, columns=10):
    answers = []
    screen = Screen(lines, columns, write_process_input=answers.append)
    stream = Stream(screen)
    return screen, stream, answers


def _titles(stream, window, icon):
    stream.feed("\x1b]2;%s\x1b\\\x1b]1;%s\x1b\\" % (window, icon))


# ----------------------------------------------------------------------
# The reports.


def test_the_window_title_is_reported():
    _screen_, stream, answers = _screen()
    stream.feed("\x1b]2;a window\x1b\\")
    stream.feed(csi(Csi.XTWINOPS, 21))
    assert answers == ["\x1b]la window\x1b\\"]


def test_the_icon_label_is_reported():
    _screen_, stream, answers = _screen()
    stream.feed("\x1b]1;an icon\x1b\\")
    stream.feed(csi(Csi.XTWINOPS, 20))
    assert answers == ["\x1b]Lan icon\x1b\\"]


def test_a_title_that_was_never_set_is_reported_empty():
    _screen_, stream, answers = _screen()
    stream.feed(csi(Csi.XTWINOPS, 20) + csi(Csi.XTWINOPS, 21))
    assert answers == ["\x1b]L\x1b\\", "\x1b]l\x1b\\"]


def test_one_sequence_sets_both():
    "OSC 0 names the window title and the icon label together."
    _screen_, stream, answers = _screen()
    stream.feed("\x1b]0;both\x1b\\")
    stream.feed(csi(Csi.XTWINOPS, 20) + csi(Csi.XTWINOPS, 21))
    assert answers == ["\x1b]Lboth\x1b\\", "\x1b]lboth\x1b\\"]


# ----------------------------------------------------------------------
# The stack.


def test_a_push_and_a_pop_bring_both_titles_back():
    screen, stream, _answers = _screen()
    _titles(stream, "window", "icon")
    stream.feed(csi(Csi.XTWINOPS, 22, 0))
    _titles(stream, "x", "x")
    stream.feed(csi(Csi.XTWINOPS, 23, 0))
    assert (screen.titles.window, screen.titles.icon) == ("window", "icon")


def test_a_pop_of_the_icon_leaves_the_window_title():
    screen, stream, _answers = _screen()
    _titles(stream, "window", "icon")
    stream.feed(csi(Csi.XTWINOPS, 22, 0))
    _titles(stream, "x", "x")
    stream.feed(csi(Csi.XTWINOPS, 23, 1))
    assert (screen.titles.window, screen.titles.icon) == ("x", "icon")


def test_a_pop_of_the_window_title_leaves_the_icon():
    screen, stream, _answers = _screen()
    _titles(stream, "window", "icon")
    stream.feed(csi(Csi.XTWINOPS, 22, 0))
    _titles(stream, "x", "x")
    stream.feed(csi(Csi.XTWINOPS, 23, 2))
    assert (screen.titles.window, screen.titles.icon) == ("window", "x")


def test_a_pop_takes_one_entry_off_whichever_title_it_names():
    """
    One stack holds both titles.

    A pop of the icon label takes the whole entry, so a pop of the
    window title after it finds nothing and changes nothing.
    """
    screen, stream, _answers = _screen()
    _titles(stream, "window", "icon")
    stream.feed(csi(Csi.XTWINOPS, 22, 0))
    _titles(stream, "x", "x")
    stream.feed(csi(Csi.XTWINOPS, 23, 1) + csi(Csi.XTWINOPS, 23, 2))
    assert (screen.titles.window, screen.titles.icon) == ("x", "icon")


def test_a_push_remembers_both_titles_whichever_it_names():
    screen, stream, _answers = _screen()
    _titles(stream, "window", "icon")
    stream.feed(csi(Csi.XTWINOPS, 22, 1))  # The icon label alone.
    _titles(stream, "y", "z")
    stream.feed(csi(Csi.XTWINOPS, 23, 0))
    assert (screen.titles.window, screen.titles.icon) == ("window", "icon")


def test_two_pushes_come_back_in_order():
    screen, stream, _answers = _screen()
    stream.feed("\x1b]1;first\x1b\\\x1b[22;1t")
    stream.feed("\x1b]1;second\x1b\\\x1b[22;1t")
    stream.feed("\x1b]1;now\x1b\\")

    stream.feed(csi(Csi.XTWINOPS, 23, 1))
    assert screen.titles.icon == "second"
    stream.feed(csi(Csi.XTWINOPS, 23, 1))
    assert screen.titles.icon == "first"


def test_a_pop_of_an_empty_stack_changes_nothing():
    screen, stream, _answers = _screen()
    _titles(stream, "window", "icon")
    stream.feed(csi(Csi.XTWINOPS, 23, 0))
    assert (screen.titles.window, screen.titles.icon) == ("window", "icon")


def test_a_pop_without_a_parameter_brings_both_back():
    screen, stream, _answers = _screen()
    _titles(stream, "window", "icon")
    stream.feed(csi(Csi.XTWINOPS, 22))
    _titles(stream, "x", "x")
    stream.feed(csi(Csi.XTWINOPS, 23))
    assert (screen.titles.window, screen.titles.icon) == ("window", "icon")


def test_the_stack_does_not_grow_without_end():
    "A program that pushes and never pops may not grow the pane."
    screen, stream, _answers = _screen()
    for number in range(50):
        stream.feed("\x1b]1;%i\x1b\\\x1b[22;1t" % number)
    assert len(screen.titles.stack) == screen.titles.STACK_LIMIT

    stream.feed(csi(Csi.XTWINOPS, 23, 1))
    assert screen.titles.icon == "49"


def test_a_reset_empties_the_stack():
    screen, stream, _answers = _screen()
    _titles(stream, "window", "icon")
    stream.feed(csi(Csi.XTWINOPS, 22, 0))
    stream.feed(esc(escape.RIS))  # RIS.
    assert screen.titles.stack == []
