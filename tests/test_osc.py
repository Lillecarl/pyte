"""
Tests for the OSC parser.

The code of an OSC sequence is a number of any length. Reading a single
character turned "OSC 11" into "OSC 1", so every code above nine ran
the wrong handler.
"""
import pyte


class Recorder:
    "Screen stub that records every dispatched event."

    def __init__(self):
        self.events = []

    def draw(self, data):
        self.events.append(("draw", data))

    def debug(self, *args, **kwargs):
        self.events.append(("debug", args, kwargs))

    def __getattr__(self, name):
        def handler(*args, **kwargs):
            self.events.append((name, args, kwargs))
        return handler


def feed(sequence):
    screen = Recorder()
    pyte.Stream(screen).feed(sequence)
    return screen.events


def test_the_title():
    assert feed("\x1b]2;hello\x07") == [("set_title", ("hello",), {})]


def test_the_icon_name():
    assert feed("\x1b]1;hello\x07") == [("set_icon_name", ("hello",), {})]


def test_code_zero_sets_both():
    assert feed("\x1b]0;hello\x07") == [
        ("set_icon_name", ("hello",), {}),
        ("set_title", ("hello",), {}),
    ]


def test_a_two_digit_code_is_not_a_one_digit_one():
    # "OSC 11" asks for the background colour. It used to arrive as
    # "OSC 1" with the payload ";?", which set the icon name.
    assert feed("\x1b]11;?\x07") == [("osc", ("11", "?"), {})]


def test_a_long_code():
    assert feed("\x1b]30001\x1b\\") == [("osc", ("30001", ""), {})]


def test_the_clipboard_code():
    assert feed("\x1b]52;c;aGVsbG8=\x07") == [
        ("osc", ("52", "c;aGVsbG8="), {})
    ]


def test_the_string_terminator_ends_a_sequence():
    assert feed("\x1b]11;rgb:00/00/00\x1b\\") == [
        ("osc", ("11", "rgb:00/00/00"), {})
    ]


def test_the_eight_bit_string_terminator():
    assert feed("\x1b]11;?\x9c") == [("osc", ("11", "?"), {})]


def test_an_escape_inside_the_payload_stays():
    assert feed("\x1b]99;i=1\x1bxdone\x07") == [
        ("osc", ("99", "i=1\x1bxdone"), {})
    ]


def test_a_code_without_a_payload():
    assert feed("\x1b]22\x07") == [("osc", ("22", ""), {})]


def test_text_after_a_sequence_is_drawn():
    assert feed("\x1b]11;?\x07hi") == [
        ("osc", ("11", "?"), {}),
        ("draw", "hi"),
    ]


def test_the_legacy_palette_codes_are_skipped():
    assert feed("\x1bPhello") == []
    assert feed("\x1b]Rhi") == [("draw", "hi")]


def test_a_plain_screen_ignores_an_unknown_sequence():
    screen = pyte.Screen(20, 2)
    pyte.Stream(screen).feed("\x1b]11;?\x07hi")
    assert screen.display[0].strip() == "hi"
