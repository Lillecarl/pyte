"""
The application keypad, which a program turns on with `smkx`.

A keypad key sends a digit by default and an SS3 form once a program
asks, so that the program can tell the keypad from the row of numbers
above the letters. `less`, `mc` and everything built on curses ask.

terminfo's `smkx` is usually "\\E[?1h\\E=": the application cursor
keys and this, in one string. pyte acted on the first half and
ignored the second, which is a state no real terminal is ever in.
Lillecarl/pymux#175.

The table is xterm's, out of `kypd_num` and `kypd_apl` in its
`input.c`. Both are indexed by the keysym less `XK_KP_Space`, so the
pair says what one key sends in each mode.
"""
import pyte
from pyte.keys import FunctionalKey
from pyte.modes import PrivateMode

#: The name of each key, the sequence a terminal that disambiguates
#: sends for it, what a pane reads with the numeric keypad, and what
#: it reads with the application keypad.
KEYPAD = [
    ("0", FunctionalKey.KP_0, "0", "\x1bOp"),
    ("1", FunctionalKey.KP_1, "1", "\x1bOq"),
    ("5", FunctionalKey.KP_5, "5", "\x1bOu"),
    ("9", FunctionalKey.KP_9, "9", "\x1bOy"),
    ("multiply", FunctionalKey.KP_MULTIPLY, "*", "\x1bOj"),
    ("add", FunctionalKey.KP_ADD, "+", "\x1bOk"),
    ("separator", FunctionalKey.KP_SEPARATOR, "", "\x1bOl"),
    ("subtract", FunctionalKey.KP_SUBTRACT, "-", "\x1bOm"),
    ("decimal", FunctionalKey.KP_DECIMAL, ".", "\x1bOn"),
    ("divide", FunctionalKey.KP_DIVIDE, "/", "\x1bOo"),
    ("equal", FunctionalKey.KP_EQUAL, "=", "\x1bOX"),
    ("enter", FunctionalKey.KP_ENTER, "\r", "\x1bOM"),
]

#: What the terminal of the person sends for a keypad key. It only
#: says "keypad" once something asked it to disambiguate; before that
#: it folds the key onto the main keyboard and nothing downstream can
#: tell the two apart.
def sent_for(key: int) -> str:
    return "\x1b[%du" % key


def a_screen():
    screen = pyte.Screen(20, 5, write_process_input=lambda data: None)
    return screen, pyte.Stream(screen)


def test_the_keypad_sends_digits_to_begin_with():
    screen, _ = a_screen()
    for name, key, numeric, _application in KEYPAD:
        assert screen.encode_key(sent_for(key)) == numeric, name


def test_deckpam_turns_the_application_keypad_on():
    "`ESC =`, which is the half of `smkx` that did nothing."
    screen, stream = a_screen()

    stream.feed("\x1b=")

    assert screen.in_application_keypad
    assert PrivateMode.APPLICATION_KEYPAD.flag in screen.mode


def test_decnkm_is_the_other_spelling():
    "Private mode 66 is the newer name for the same thing."
    screen, stream = a_screen()

    stream.feed("\x1b[?66h")

    assert screen.in_application_keypad


def test_every_keypad_key_sends_its_ss3_form():
    screen, stream = a_screen()
    stream.feed("\x1b=")

    for name, key, _numeric, application in KEYPAD:
        assert screen.encode_key(sent_for(key)) == application, name


def test_deckpnm_puts_the_digits_back():
    "`ESC >`, which is `rmkx`."
    screen, stream = a_screen()
    stream.feed("\x1b=")

    stream.feed("\x1b>")

    assert not screen.in_application_keypad
    assert screen.encode_key(sent_for(FunctionalKey.KP_0)) == "0"


def test_smkx_turns_on_both_halves():
    """
    terminfo sends the two in one string, so a screen that acts on one
    and not the other is in a state no real terminal is ever in.
    """
    screen, stream = a_screen()

    stream.feed("\x1b[?1h\x1b=")

    assert screen.in_application_mode
    assert screen.in_application_keypad
    assert screen.encode_key("\x1b[A") == "\x1bOA"
    assert screen.encode_key(sent_for(FunctionalKey.KP_0)) == "\x1bOp"


def test_the_number_row_is_not_the_keypad():
    "The whole point of the mode is that a program can tell them apart."
    screen, stream = a_screen()
    stream.feed("\x1b=")

    assert screen.encode_key("0") == "0"
    assert screen.encode_key("+") == "+"
    assert screen.encode_key("\r") == "\r"


def test_a_keypad_arrow_follows_the_cursor_keys_and_not_the_keypad():
    """
    The arrows on the keypad are cursor keys. DECCKM decides them, and
    this mode does not touch them.
    """
    screen, stream = a_screen()
    stream.feed("\x1b=")

    assert screen.encode_key(sent_for(FunctionalKey.KP_UP)) == "\x1b[A"

    stream.feed("\x1b[?1h")
    assert screen.encode_key(sent_for(FunctionalKey.KP_UP)) == "\x1bOA"


def test_a_modified_keypad_key_is_not_in_this_mode():
    """
    xterm gives a modified keypad key to `modifyKeypadKeys`, and this
    screen has no such resource, so the key folds as it did.
    """
    screen, stream = a_screen()
    stream.feed("\x1b=")

    assert screen.encode_key("\x1b[%d;5u" % FunctionalKey.KP_0) == "0"


def test_a_pane_that_asked_for_more_reads_the_number_of_the_key():
    """
    The SS3 form belongs to the legacy mode, the way the SS3 arrow
    does. A pane that pushed a kitty flag reads the key itself.
    """
    screen, stream = a_screen()
    stream.feed("\x1b=")
    stream.feed("\x1b[>1u")

    assert screen.encode_key(sent_for(FunctionalKey.KP_0)) == "\x1b[57399u"


def test_a_reset_puts_the_keypad_back():
    screen, stream = a_screen()
    stream.feed("\x1b=")

    stream.feed("\x1bc")

    assert not screen.in_application_keypad


# ----------------------------------------------------------------------
# DECBKM, which is the other keyboard mode on the same list.


def test_the_backarrow_sends_a_delete_to_begin_with():
    """
    Which is what a pty reports as its erase character: `stty` on a
    fresh one says "erase = ^?". A pane that sent the backspace would
    be a pane where the key does not erase in bash, in python, or
    anywhere else that reads a line.
    """
    screen, _ = a_screen()
    assert not screen.backarrow_sends_backspace
    assert screen.encode_key("\x7f") == "\x7f"


def test_decbkm_makes_it_a_backspace():
    "DECBKM, private mode 67. Lillecarl/pymux#184."
    screen, stream = a_screen()

    stream.feed("\x1b[?67h")

    assert screen.backarrow_sends_backspace
    assert screen.encode_key("\x7f") == "\x08"


def test_ctrl_swaps_the_two_and_decbkm_swaps_them_again():
    "kitty writes the first half of that, and xterm both."
    screen, stream = a_screen()
    assert screen.encode_key("\x1b[127;5u") == "\x08"

    stream.feed("\x1b[?67h")

    assert screen.encode_key("\x1b[127;5u") == "\x7f"


def test_alt_still_puts_an_escape_in_front():
    screen, stream = a_screen()
    assert screen.encode_key("\x1b\x7f") == "\x1b\x7f"

    stream.feed("\x1b[?67h")

    assert screen.encode_key("\x1b\x7f") == "\x1b\x08"


def test_resetting_decbkm_puts_the_delete_back():
    screen, stream = a_screen()
    stream.feed("\x1b[?67h")

    stream.feed("\x1b[?67l")

    assert screen.encode_key("\x7f") == "\x7f"


def test_a_pane_that_asked_to_disambiguate_still_reads_it():
    """
    The backspace is one of the three keys that keep their legacy
    bytes under that flag, and DECBKM says what those bytes are.
    """
    screen, stream = a_screen()
    stream.feed("\x1b[?67h\x1b[>1u")

    assert screen.encode_key("\x7f") == "\x08"
