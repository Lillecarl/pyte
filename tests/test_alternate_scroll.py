"""
"?1007": the wheel is arrows on the alternate screen.

That screen has no history, so a wheel has nothing to scroll there. A
pager or a transcript on it scrolls on arrows instead, and this mode
says the wheel sends them. codex sets it for its transcript.
Lillecarl/pymux#422.

It starts on. Ghostty and Alacritty start it on, and kitty (`fake_scroll`
in `mouse.c`) and WezTerm send the arrows with no mode at all; xterm
alone starts it off.
"""

from pyte import escape
from pyte.modes import PrivateMode
from pyte.screen import Screen
from pyte.sequences import Csi, csi, esc, reset_mode, set_mode
from pyte.streams import Stream

ALTERNATE = set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
MAIN = reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
OFF = reset_mode(PrivateMode.ALTERNATE_SCROLL)
ON = set_mode(PrivateMode.ALTERNATE_SCROLL)


def make_screen():
    "Return (screen, stream, what the screen answered)."
    answers = []
    screen = Screen(4, 20, write_process_input=answers.append)
    return screen, Stream(screen), answers


def test_the_first_screen_has_a_history_so_the_wheel_is_not_arrows():
    screen, _stream, _answers = make_screen()
    assert screen.wheel_sends_arrows is False


def test_the_alternate_screen_takes_arrows_with_no_mode_asked_for():
    screen, stream, _answers = make_screen()
    stream.feed(ALTERNATE)
    assert screen.wheel_sends_arrows is True


def test_a_program_can_turn_it_off():
    screen, stream, _answers = make_screen()
    stream.feed(ALTERNATE + OFF)
    assert screen.wheel_sends_arrows is False


def test_a_program_can_turn_it_back_on():
    "A set has to get past the level and embedder filters of `set_mode`."
    screen, stream, _answers = make_screen()
    stream.feed(ALTERNATE + OFF + ON)
    assert screen.wheel_sends_arrows is True


def test_it_ends_with_the_alternate_screen():
    screen, stream, _answers = make_screen()
    stream.feed(ALTERNATE + ON + MAIN)
    assert screen.wheel_sends_arrows is False


def test_decrqm_answers_for_it():
    "A mode this screen acts on has to be one it can report."
    _screen, stream, answers = make_screen()
    stream.feed(csi(Csi.DECRQM, 1007, private="?"))
    assert answers == ["\x1b[?1007;1$y"]
    answers.clear()
    stream.feed(OFF + csi(Csi.DECRQM, 1007, private="?"))
    assert answers == ["\x1b[?1007;2$y"]


def test_a_soft_reset_leaves_it_as_it_was():
    "xterm's DECSTR does not touch it: the wheel is the person's setting."
    screen, stream, _answers = make_screen()
    stream.feed(OFF + csi(Csi.DECSTR) + ALTERNATE)
    assert screen.wheel_sends_arrows is False


def test_a_hard_reset_turns_it_back_on():
    screen, stream, _answers = make_screen()
    stream.feed(OFF + esc(escape.RIS) + ALTERNATE)
    assert screen.wheel_sends_arrows is True
