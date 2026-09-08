import io

import pytest

import pyte
from pyte.screen import Screen

from a_screen import a_screen, display
from pyte import charsets as cs, control as ctrl, escape as esc
from pyte import escape
from pyte.sequences import announce


class counter:
    def __init__(self):
        self.count = 0

    def __call__(self, *args, **kwargs):
        self.count += 1


class argcheck(counter):
    def __call__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        super().__call__()


class argstore:
    def __init__(self):
        self.seen = []

    def __call__(self, *args):
        self.seen.extend(args)


class IntentionalException(Exception):
    pass


def test_basic_sequences():
    for cmd, event in pyte.Stream.escape.items():
        screen = a_screen(80, 24)
        handler = counter()
        setattr(screen, event, handler)

        stream = pyte.Stream(screen)
        stream.feed(ctrl.ESC)
        assert not handler.count

        stream.feed(cmd)
        assert handler.count == 1, event


def test_linefeed():
    # ``linefeed`` is somewhat an exception, there's three ways to
    # trigger it.
    handler = counter()
    screen = a_screen(80, 24)
    screen.linefeed = handler

    stream = pyte.Stream(screen)
    stream.feed(ctrl.LF + ctrl.VT + ctrl.FF)
    assert handler.count == 3


def test_unknown_sequences():
    handler = argcheck()
    screen = a_screen(80, 24)
    screen.debug = handler

    stream = pyte.Stream(screen)
    # "Y" names no sequence. "Z" did until the parser learned CBT.
    stream.feed(ctrl.CSI + "6;Y")
    assert handler.count == 1
    assert handler.args == (6, 0)
    assert handler.kwargs == {}


def test_non_csi_sequences():
    for cmd, event in pyte.Stream.csi.items():
        # a) single param
        handler = argcheck()
        screen = a_screen(80, 24)
        setattr(screen, event, handler)

        stream = pyte.Stream(screen)
        stream.feed(ctrl.ESC + "[5" + cmd)
        assert handler.count == 1
        assert handler.args == (5, )

        # b) multiple params, and starts with CSI, not ESC [
        handler = argcheck()
        screen = a_screen(80, 24)
        setattr(screen, event, handler)

        stream = pyte.Stream(screen)
        stream.feed(ctrl.CSI + "5;12" + cmd)
        assert handler.count == 1
        assert handler.args == (5, 12)


def test_set_mode():
    bugger = counter()
    screen = a_screen(80, 24)
    handler = argcheck()
    screen.debug = bugger
    screen.set_mode = handler

    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "?9;2h")
    assert not bugger.count
    assert handler.count == 1
    assert handler.args == (9, 2)
    assert handler.kwargs == {"private": True}


def test_reset_mode():
    bugger = counter()
    screen = a_screen(80, 24)
    handler = argcheck()
    screen.debug = bugger
    screen.reset_mode = handler

    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "?9;2l")
    assert not bugger.count
    assert handler.count == 1
    assert handler.args == (9, 2)


def test_missing_params():
    handler = argcheck()
    screen = a_screen(80, 24)
    screen.cursor_position = handler

    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + ";" + esc.HVP)
    assert handler.count == 1
    assert handler.args == (0, 0)


def test_overflow():
    # Parameters are not capped: the kitty keyboard protocol uses
    # functional key codes above 9999. (The screen clamps positions
    # itself where needed.)
    handler = argcheck()
    screen = a_screen(80, 24)
    screen.cursor_position = handler

    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "999999999999999;99999999999999" + esc.HVP)
    assert handler.count == 1
    assert handler.args == (999999999999999, 99999999999999)


def test_interrupt():
    bugger = argstore()
    handler = argcheck()

    screen = a_screen(80, 24)
    screen.draw = bugger
    screen.cursor_position = handler

    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "10;" + ctrl.SUB + "10" + esc.HVP)

    assert not handler.count
    assert bugger.seen == [
        ctrl.SUB, "10" + esc.HVP
    ]


def test_control_characters():
    handler = argcheck()
    screen = a_screen(80, 24)
    screen.cursor_position = handler

    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "10;\t\t\n\r\n10" + esc.HVP)

    assert handler.count == 1
    assert handler.args == (10, 10)


@pytest.mark.parametrize('osc,st', [
    (ctrl.OSC_C0, ctrl.ST_C0),
    (ctrl.OSC_C0, ctrl.ST_C1),
    (ctrl.OSC_C1, ctrl.ST_C0),
    (ctrl.OSC_C1, ctrl.ST_C1)
])
def test_set_title_icon_name(osc, st):
    screen = a_screen(80, 24)
    stream = pyte.Stream(screen)

    # a) set only icon name
    stream.feed(osc + "1;foo" + st)
    assert screen.titles.icon == "foo"

    # b) set only title
    stream.feed(osc + "2;foo" + st)
    assert screen.titles.window == "foo"

    # c) set both icon name and title
    stream.feed(osc + "0;bar" + st)
    assert screen.titles.window == screen.titles.icon == "bar"

    # d) set both icon name and title then terminate with BEL
    stream.feed(osc + "0;bar" + st)
    assert screen.titles.window == screen.titles.icon == "bar"

    # e) test ➜ ('\xe2\x9e\x9c') symbol, that contains string terminator \x9c
    stream.feed("➜")
    assert screen.page.data_buffer[0][0].char == "➜"


def test_compatibility_api():
    screen = a_screen(80, 24)
    stream = pyte.Stream()
    stream.attach(screen)

    # All of the following shouldn't raise errors.
    # a) adding more than one listener
    stream.attach(a_screen(80, 24))

    # b) feeding text
    stream.feed("привет")

    # c) detaching an attached screen.
    stream.detach(screen)


def test_define_charset():
    # Should be a noop. All input is UTF8.
    screen = a_screen(3, 3)
    stream = pyte.Stream(screen)
    stream.feed(ctrl.ESC + "(B")
    assert display(screen)[0] == " " * 3


def test_non_utf8_shifts():
    screen = a_screen(3, 3)
    handler = screen.shift_in = screen.shift_out = argcheck()
    stream = pyte.Stream(screen)
    stream.use_utf8 = False
    stream.feed(ctrl.SI)
    stream.feed(ctrl.SO)
    assert handler.count == 2


def test_dollar_skip():
    screen = a_screen(3, 3)
    handler = screen.draw = argcheck()
    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "12$p")
    assert handler.count == 0
    stream.feed(ctrl.CSI + "1;2;3;4$x")
    assert handler.count == 0


def test_dollar_is_an_intermediate_byte():
    """
    "CSI Ps $ p" (DECRQM) is not "CSI Ps p". The "$" names the
    sequence, so it belongs to the key that picks the handler.
    """
    calls = []

    class Watching(Screen):
        def request_mode(self, *args, **kwargs):
            calls.append((args, kwargs))

    stream = pyte.Stream()
    stream.csi = dict(stream.csi, **{"$p": "request_mode"})
    stream.attach(a_screen(3, 3, Watching))

    stream.feed(ctrl.CSI + "?2004$p")
    assert calls == [((2004,), {"private": True})]

    del calls[:]
    stream.feed(ctrl.CSI + "4$p")
    assert calls == [((4,), {})]


def test_an_unknown_dollar_sequence_is_not_drawn():
    "It reaches `debug`, like every other sequence without a handler."
    screen = a_screen(3, 3)
    handler = screen.draw = argcheck()
    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "1;2$z" + "ok")
    assert handler.count == 1  # Only the "ok".


def test_the_space_of_an_announcer_is_an_intermediate_byte():
    """
    "ESC SP G" is S8C1T, and the space names it. A stream that does not
    read the space stops at it, and the "G" lands on the screen as text.
    """
    screen = a_screen(3, 3)
    handler = screen.draw = argcheck()
    stream = pyte.Stream(screen)
    stream.feed(announce(escape.S8C1T))
    assert handler.count == 0
    assert screen.seven_bit_controls is False

    stream.feed(announce(escape.S7C1T))
    assert handler.count == 0
    assert screen.seven_bit_controls is True


def test_an_unknown_announcer_is_eaten_as_well():
    """
    "ESC SP L" names an ANSI conformance level. pyte does nothing with
    it, and the "L" still must not be drawn.
    """
    screen = a_screen(3, 3)
    handler = screen.draw = argcheck()
    stream = pyte.Stream(screen)
    stream.feed("\x1b L" + "ok")
    assert handler.count == 1  # Only the "ok".


@pytest.mark.parametrize("input,expected", [
    (b"foo", [["draw", ["foo"], {}]]),
    (b"\x1b[1;24r\x1b[4l\x1b[24;1H", [
        ["set_margins", [1, 24], {}],
        ["reset_mode", [4], {}],
        ["cursor_position", [24, 1], {}]])
])
def test_debug_stream(input, expected):
    output = io.StringIO()
    stream = pyte.ByteStream(pyte.DebugScreen(to=output))
    stream.feed(input)

    output.seek(0)
    assert [eval(line) for line in output] == expected


def test_handler_exception():
    # When an error occurs in a handler, the stream should continue to
    # work. See PR #101 for details.

    def failing_handler(*args, **kwargs):
        raise IntentionalException()

    handler = argcheck()
    screen = a_screen(80, 24)
    screen.set_mode = failing_handler
    screen.reset_mode = handler

    stream = pyte.Stream(screen)
    with pytest.raises(IntentionalException):
        stream.feed(ctrl.CSI + "?9;2h")

    stream.feed(ctrl.CSI + "?9;2l")
    assert handler.count == 1


def test_byte_stream_feed():
    screen = a_screen(20, 1)
    screen.draw = handler = argcheck()

    stream = pyte.ByteStream(screen)
    stream.feed("Нерусский текст".encode())
    assert handler.count == 1
    assert handler.args == ("Нерусский текст", )


def test_byte_stream_define_charset_unknown():
    screen = a_screen(3, 3)
    stream = pyte.ByteStream(screen)
    stream.select_other_charset("@")
    default_g0_charset = screen.g0_charset
    # ``"Z"`` is not supported by Linux terminal, so expect a noop.
    assert "Z" not in cs.MAPS
    stream.feed((ctrl.ESC + "(Z").encode())
    assert display(screen)[0] == " " * 3
    assert screen.g0_charset == default_g0_charset


@pytest.mark.parametrize("charset,mapping", cs.MAPS.items())
def test_byte_stream_define_charset(charset, mapping):
    screen = a_screen(3, 3)
    stream = pyte.ByteStream(screen)
    stream.select_other_charset("@")
    stream.feed((ctrl.ESC + "(" + charset).encode())
    assert display(screen)[0] == " " * 3
    assert screen.g0_charset == mapping


def test_byte_stream_select_other_charset():
    stream = pyte.ByteStream(a_screen(3, 3))
    assert stream.use_utf8  # on by default.

    # a) disable utf-8
    stream.select_other_charset("@")
    assert not stream.use_utf8

    # b) unknown code -- noop
    stream.select_other_charset("X")
    assert not stream.use_utf8

    # c) enable utf-8
    stream.select_other_charset("G")
    assert stream.use_utf8


def test_too_many_params():
    # A sequence that carries more parameters than the command takes is
    # not an error. xterm reads the ones it needs and drops the rest.
    # Before this, the extra parameter raised a TypeError and stopped
    # the whole stream.
    screen = a_screen(80, 24)
    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "3;9;9" + esc.CHA)  # CHA takes one parameter.
    assert screen.pt_cursor_position.x == 2

    stream.feed("ok")
    assert display(screen)[0].strip() == "ok"


def test_a_private_marker_on_a_command_that_does_not_take_one():
    # "CSI ? 5 G" names no private command. The marker is dropped and
    # the command runs, rather than raising a TypeError.
    screen = a_screen(80, 24)
    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "?5" + esc.CHA)
    assert screen.pt_cursor_position.x == 4


def test_define_charset_in_utf8_mode():
    # "ESC ( 0" names the line drawing set of the DEC terminals, which
    # is how ncurses draws a box. xterm and kitty both read it in UTF-8
    # mode, and pyte dropped it there, so a box showed letters.
    screen = a_screen(3, 3)
    handler = screen.define_charset = argcheck()
    stream = pyte.Stream(screen)
    stream.feed(ctrl.ESC + "(0")
    assert handler.count == 1
    assert handler.args == ("0",)
    assert handler.kwargs == {"mode": "("}


def test_shifts_in_utf8_mode():
    # The same holds for shift in and shift out, which pick G0 and G1.
    screen = a_screen(3, 3)
    handler = screen.shift_in = screen.shift_out = argcheck()
    stream = pyte.Stream(screen)
    stream.feed(ctrl.SI)
    stream.feed(ctrl.SO)
    assert handler.count == 2


def test_every_intermediate_byte_belongs_to_the_sequence():
    # ECMA-48 gives the intermediate bytes the whole range 0x20 to
    # 0x2f. Reading one of them as the final byte ends the sequence
    # there, and the real final byte lands on the screen as text.
    # "CSI Ps ' }" is DECIC, which pyte does not act on.
    screen = a_screen(3, 3)
    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "2'}hi")
    assert display(screen)[0] == "hi "


def test_hpa_reads_the_backquote():
    # The final byte of HPA is the backquote. The apostrophe is an
    # intermediate byte and names no command of its own.
    screen = a_screen(80, 24)
    stream = pyte.Stream(screen)
    stream.feed(ctrl.CSI + "5`")
    assert screen.pt_cursor_position.x == 4
