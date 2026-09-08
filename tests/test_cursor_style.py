"""
The cursor of a pane: its shape, and whether it blinks.

Two sequences write the same cursor. DECSCUSR ("CSI Ps SP q") names the
shape and the blinking in one number. Private mode 12 names only the
blinking. So both write `cursor_style`, and every reader gets one
answer: the blinking shapes are the odd numbers, and the steady one of
a pair is the number after it.

The pane keeps this, and what draws the pane puts it on the terminal of
the user.
"""
from pyte.screen import Screen
from pyte.streams import Stream
from pyte.modes import PrivateMode
from pyte.sequences import Csi, csi, reset_mode, set_mode


def make_screen():
    "Return (screen, stream, responses)."
    responses = []
    screen = Screen(24, 80, write_process_input=responses.append)
    stream = Stream(screen)
    return screen, stream, responses


def test_a_terminal_starts_with_a_blinking_block():
    screen, stream, responses = make_screen()
    assert screen.cursor_style == 1
    assert screen.cursor_blinks


def test_decscusr_names_the_shape():
    screen, stream, responses = make_screen()
    for request, style in (
        (csi(Csi.DECSCUSR, 2), 2),
        (csi(Csi.DECSCUSR, 3), 3),
        (csi(Csi.DECSCUSR, 4), 4),
        (csi(Csi.DECSCUSR, 5), 5),
        (csi(Csi.DECSCUSR, 6), 6),
    ):
        stream.feed(request)
        assert screen.cursor_style == style


def test_zero_means_the_shape_a_terminal_starts_with():
    screen, stream, responses = make_screen()
    stream.feed(csi(Csi.DECSCUSR, 6))
    stream.feed(csi(Csi.DECSCUSR, 0))
    assert screen.cursor_style == 1


def test_a_shape_that_nobody_knows_is_left_alone():
    screen, stream, responses = make_screen()
    stream.feed(csi(Csi.DECSCUSR, 6))
    stream.feed(csi(Csi.DECSCUSR, 9))
    assert screen.cursor_style == 6


def test_mode_12_turns_the_blinking_on_and_off():
    screen, stream, responses = make_screen()
    stream.feed(csi(Csi.DECSCUSR, 6))  # A bar that does not blink.
    stream.feed(set_mode(PrivateMode.CURSOR_BLINK))
    assert (screen.cursor_style, screen.cursor_blinks) == (5, True)
    stream.feed(reset_mode(PrivateMode.CURSOR_BLINK))
    assert (screen.cursor_style, screen.cursor_blinks) == (6, False)


def test_mode_12_keeps_the_shape():
    screen, stream, responses = make_screen()
    stream.feed(csi(Csi.DECSCUSR, 4))  # An underline that does not blink.
    stream.feed(set_mode(PrivateMode.CURSOR_BLINK))
    assert screen.cursor_style == 3  # An underline that blinks.


def test_setting_the_blinking_twice_changes_nothing():
    screen, stream, responses = make_screen()
    stream.feed(csi(Csi.DECSCUSR, 2))
    stream.feed(set_mode(PrivateMode.CURSOR_BLINK))
    stream.feed(set_mode(PrivateMode.CURSOR_BLINK))
    assert screen.cursor_style == 1


def test_decrqm_answers_for_the_blinking():
    # The answer comes from the shape, because DECSCUSR writes it too.
    screen, stream, responses = make_screen()
    stream.feed(csi(Csi.DECSCUSR, 6))
    responses.clear()
    stream.feed(csi(Csi.DECRQM, 12, private='?'))
    assert responses == ["\x1b[?12;2$y"]  # Reset.

    stream.feed(csi(Csi.DECSCUSR, 5))
    responses.clear()
    stream.feed(csi(Csi.DECRQM, 12, private='?'))
    assert responses == ["\x1b[?12;1$y"]  # Set.


def test_decrqss_reports_the_shape():
    screen, stream, responses = make_screen()
    stream.feed(set_mode(PrivateMode.CURSOR_BLINK))
    responses.clear()
    stream.feed("\x1bP$q q\x1b\\")
    assert responses == ["\x1bP1$r1 q\x1b\\"]
