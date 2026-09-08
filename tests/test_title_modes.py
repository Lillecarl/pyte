"""
The title modes of xterm: how a title is written and how it is read.

A title is text, and not every title is text a terminal can carry: a
byte that is not valid UTF-8 has no way through "OSC 0", "OSC 1" or
"OSC 2". So xterm has four modes that "CSI > Ps t" sets and
"CSI > Ps T" takes away. Two say how a program writes a title, and two
say how the terminal reports one back.

`SMTitleTests` of esctest2 asks for all four. Lillecarl/pymux#44 is
where the gap was found.
"""
import pytest

from pyte.parameters import TitleMode
from pyte.screen import Screen
from pyte.streams import Stream
from pyte.sequences import Csi, csi

#: "CSI > Ps t": set a title mode. "CSI > Ps T": take it away.
SET = "\x1b[>%st"
RESET = "\x1b[>%sT"

#: "OSC 2": the window title. "OSC 1": the icon name.
TITLE = "\x1b]2;%s\x1b\\"
ICON = "\x1b]1;%s\x1b\\"

#: "CSI 21 t": report the window title. "CSI 20 t": the icon name.
ASK_FOR_TITLE = csi(Csi.XTWINOPS, 21)
ASK_FOR_ICON = csi(Csi.XTWINOPS, 20)


def make_screen():
    "Return (screen, stream, the answers it wrote back)."
    answers = []
    screen = Screen(4, 20, write_process_input=answers.append)
    return screen, Stream(screen), answers


# ----------------------------------------------------------------------
# Setting the modes.


def test_a_terminal_starts_with_no_title_mode():
    screen, _stream, _answers = make_screen()
    assert screen.titles.modes == set()


def test_one_sequence_can_set_several_modes():
    screen, stream, _answers = make_screen()
    stream.feed(SET % "0;3")
    assert screen.titles.modes == {TitleMode.SET_HEX, TitleMode.QUERY_UTF8}


def test_a_mode_can_be_taken_away_again():
    screen, stream, _answers = make_screen()
    stream.feed(SET % "0;1" + RESET % "1")
    assert screen.titles.modes == {TitleMode.SET_HEX}


def test_a_sequence_with_no_parameter_names_the_first_mode():
    "A missing number is a zero here, the way it is everywhere else."
    screen, stream, _answers = make_screen()
    stream.feed(SET % "")
    assert screen.titles.modes == {TitleMode.SET_HEX}
    stream.feed(RESET % "")
    assert screen.titles.modes == set()


def test_a_number_that_no_mode_has_is_ignored():
    "And it does not take the modes beside it in the same sequence."
    screen, stream, _answers = make_screen()
    stream.feed(SET % "0;9")
    assert screen.titles.modes == {TitleMode.SET_HEX}


def test_a_reset_takes_every_title_mode_away():
    screen, stream, _answers = make_screen()
    stream.feed(SET % "0;1")
    stream.feed("\x1bc")  # RIS.
    assert screen.titles.modes == set()


# ----------------------------------------------------------------------
# The marker tells the two sequences apart.


def test_the_marker_is_what_makes_it_a_title_mode():
    """
    Without it "CSI 4 t" asks for a resize in pixels, and "CSI 1 T"
    scrolls the region down.
    """
    asks = []
    screen = Screen(
        4, 20,
        write_process_input=lambda data: None,
        resize_func=lambda lines, columns: asks.append((lines, columns)),
    )
    stream = Stream(screen)
    stream.feed(csi(Csi.XTWINOPS, 4, private='>'))
    assert asks == []
    assert screen.titles.modes == set()


def test_a_plain_scroll_down_still_scrolls():
    screen, stream, _answers = make_screen()
    stream.feed("one\r\ntwo")
    stream.feed(csi(Csi.SD, 1))
    assert screen.data_buffer[1][0].char == "o"


# ----------------------------------------------------------------------
# Writing a title.


def test_a_title_is_plain_text_until_a_program_says_otherwise():
    screen, stream, _answers = make_screen()
    stream.feed(TITLE % "ab")
    assert screen.titles.window == "ab"


def test_a_hexadecimal_title_is_decoded():
    screen, stream, _answers = make_screen()
    stream.feed(SET % "0" + TITLE % "6162")
    assert screen.titles.window == "ab"


def test_a_hexadecimal_icon_name_is_decoded():
    screen, stream, _answers = make_screen()
    stream.feed(SET % "0" + ICON % "61")
    assert screen.titles.icon == "a"


def test_the_bytes_of_a_hexadecimal_title_are_utf_8():
    screen, stream, _answers = make_screen()
    stream.feed(SET % "0" + TITLE % "c3a4")
    assert screen.titles.window == "ä"


@pytest.mark.parametrize("written", ["61z", "616", "hello"])
def test_a_title_that_is_not_hexadecimal_arrives_as_it_stands(written):
    "A title nobody can read is still better than no title at all."
    screen, stream, _answers = make_screen()
    stream.feed(SET % "0" + TITLE % written)
    assert screen.titles.window == written


# ----------------------------------------------------------------------
# Reading a title back.


def test_a_title_is_reported_as_plain_text():
    screen, stream, answers = make_screen()
    stream.feed(TITLE % "ab" + ASK_FOR_TITLE)
    assert answers == ["\x1b]lab\x1b\\"]


def test_a_title_is_reported_in_hexadecimal_when_asked_for():
    screen, stream, answers = make_screen()
    stream.feed(SET % "1" + TITLE % "ab" + ASK_FOR_TITLE)
    assert answers == ["\x1b]l6162\x1b\\"]


def test_an_icon_name_is_reported_in_hexadecimal_as_well():
    screen, stream, answers = make_screen()
    stream.feed(SET % "1" + ICON % "a" + ASK_FOR_ICON)
    assert answers == ["\x1b]L61\x1b\\"]


# ----------------------------------------------------------------------
# The two sides are independent, which is what esctest2 checks.


def test_a_program_can_write_hexadecimal_and_read_text():
    "SMTitleTests.test_SMTitle_SetHexQueryUTF8 of esctest2."
    screen, stream, answers = make_screen()
    stream.feed(RESET % "2;1" + SET % "0;3")
    stream.feed(TITLE % "6162" + ASK_FOR_TITLE)
    assert answers == ["\x1b]lab\x1b\\"]


def test_a_program_can_write_text_and_read_hexadecimal():
    "SMTitleTests.test_SMTitle_SetUTF8QueryHex of esctest2."
    screen, stream, answers = make_screen()
    stream.feed(RESET % "0;3" + SET % "2;1")
    stream.feed(TITLE % "ab" + ASK_FOR_TITLE)
    assert answers == ["\x1b]l6162\x1b\\"]


def test_the_utf_8_modes_change_nothing():
    """
    They pick between UTF-8 and Latin-1, and a pane reads and writes
    UTF-8 everywhere. So they are recorded and do nothing.
    """
    screen, stream, answers = make_screen()
    stream.feed(SET % "2;3" + TITLE % "ä" + ASK_FOR_TITLE)
    assert screen.titles.window == "ä"
    assert answers == ["\x1b]lä\x1b\\"]
