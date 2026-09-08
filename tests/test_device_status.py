"""
What "CSI Ps n" and "CSI ? Ps n" answer.

DSR asks the terminal about itself. Most of the questions are about a
part that a pane does not have: a printer, a keyboard, a locator, a
macro store. Each of those has a legal answer that says "no", and a
terminal has to give it.

A query with no answer is worse than a wrong answer. The program waits
for one, and every answer after it arrives one place out of step. That
is why the whole class of these tests failed while only some of them
were missing.
"""
import pytest

from pyte.screen import Screen
from pyte.streams import Stream
from pyte import escape
from pyte.sequences import csi


def _screen(lines=8, columns=20):
    answers = []
    screen = Screen(lines, columns, write_process_input=answers.append)
    stream = Stream(screen)
    return screen, stream, answers


@pytest.mark.parametrize(
    "query, answer",
    [
        # DSRPrinterPort: no printer.
        (csi(escape.DSR, 15, private='?'), csi(escape.DSR, 13, private='?')),
        # DSRUDKLocked: the user defined keys are unlocked.
        (csi(escape.DSR, 25, private='?'), csi(escape.DSR, 20, private='?')),
        # DSRKeyboard: North American, ready, a PC keyboard.
        (csi(escape.DSR, 26, private='?'), csi(escape.DSR, 27, 1, 0, 5, private='?')),
        # DSRLocatorStatus: no locator.
        (csi(escape.DSR, 55, private='?'), csi(escape.DSR, 50, private='?')),
        # DSRLocatorId: the kind of locator is not known.
        (csi(escape.DSR, 56, private='?'), csi(escape.DSR, 57, 0, private='?')),
        # DECMSR: no room for a macro. This answer carries no private
        # marker, and ends with "* {".
        (csi(escape.DSR, 62, private='?'), "\x1b[0*{"),
        # DSRDataIntegrity: no error since the last report.
        (csi(escape.DSR, 75, private='?'), csi(escape.DSR, 70, private='?')),
        # DSRMultipleSessionStatus: one session.
        (csi(escape.DSR, 85, private='?'), csi(escape.DSR, 83, private='?')),
    ],
)
def test_a_part_that_is_not_here_still_answers(query, answer):
    _screen_, stream, answers = _screen()
    stream.feed(query)
    assert answers == [answer]


def test_the_checksum_of_the_macros_is_zero():
    "DECCKSR carries the number of the request back with the answer."
    _screen_, stream, answers = _screen()
    stream.feed(csi(escape.DSR, 63, 123, private='?'))
    assert answers == ["\x1bP123!~0000\x1b\\"]


def test_the_terminal_says_it_is_well():
    _screen_, stream, answers = _screen()
    stream.feed(csi(escape.DSR, 5))
    assert answers == ["\x1b[0n"]


def test_the_cursor_position_comes_back():
    _screen_, stream, answers = _screen()
    stream.feed(csi(escape.CUP, 6, 5) + csi(escape.DSR, 6))
    assert answers == ["\x1b[6;5R"]


def test_the_page_number_follows_the_position():
    "DECXCPR ('CSI ? 6 n') adds the page, and a pane holds one page."
    _screen_, stream, answers = _screen()
    stream.feed(csi(escape.CUP, 6, 5) + csi(escape.DSR, 6, private='?'))
    assert answers == ["\x1b[?6;5;1R"]


def test_a_report_nobody_knows_is_left_alone():
    "An answer to a question pyte does not know would be a wrong answer."
    _screen_, stream, answers = _screen()
    stream.feed(csi(escape.DSR, 4242, private='?'))
    assert answers == []
