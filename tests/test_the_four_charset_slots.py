"""
Four slots, a locking shift and a single shift.

A VT100 had two slots and the two control characters that pick between
them, SI and SO. A VT220 has four, and the two it added are reached by
an escape: a locking shift moves one of them into the letters until
something says otherwise, and a single shift lends one of them for the
next character alone.

A program that wants one character out of another set uses the second
kind. It designates the set into G2 and writes "ESC N" before the
character, which is cheaper than shifting there and back.
Lillecarl/pymux#373.
"""

import pytest

from pyte import charsets as cs
from pyte.screen import Screen
from pyte.streams import Stream

#: A box drawing character of the DEC line drawing set, which is the
#: one set every terminal has, and the letter that names it.
CORNER = "┌"
CORNER_IS = "l"


def _screen(columns=20):
    screen = Screen(2, columns, write_process_input=lambda data: None)
    return screen, Stream(screen)


def _drawn(sequence, columns=20):
    screen, stream = _screen(columns)
    stream.feed(sequence)
    line = screen.page.data_buffer.get(screen.line_offset)
    if line is None:
        return ""
    return "".join(
        (line[column].char or " ") for column in range(columns)
    ).rstrip()


@pytest.mark.parametrize(
    "designator, slot", sorted(Screen.SLOTS.items(), key=lambda pair: pair[1])
)
def test_each_designator_names_its_own_slot(designator, slot):
    screen, stream = _screen()
    stream.feed("\x1b%s0" % (designator,))
    assert screen.g_charsets[slot] is cs.MAPS["0"]
    assert [
        other for index, other in enumerate(screen.g_charsets) if index != slot
    ] == [cs.LAT1_MAP] * 3


def test_a_slot_alone_draws_nothing_different():
    "G2 holds the line drawing set and the letters still come from G0."
    assert _drawn("\x1b*0" + CORNER_IS) == CORNER_IS


def test_a_locking_shift_brings_g2_in():
    assert _drawn("\x1b*0\x1bn" + CORNER_IS) == CORNER


def test_a_locking_shift_brings_g3_in():
    assert _drawn("\x1b+0\x1bo" + CORNER_IS) == CORNER


def test_shift_in_takes_the_letters_back_to_g0():
    assert _drawn("\x1b*0\x1bn%s\x0f%s" % (CORNER_IS, CORNER_IS)) == (
        CORNER + CORNER_IS
    )


def test_a_single_shift_lends_g2_for_one_character():
    assert _drawn("\x1b*0\x1bN%s%s" % (CORNER_IS, CORNER_IS)) == (
        CORNER + CORNER_IS
    )


def test_a_single_shift_lends_g3_for_one_character():
    assert _drawn("\x1b+0\x1bO%s%s" % (CORNER_IS, CORNER_IS)) == (
        CORNER + CORNER_IS
    )


def test_a_single_shift_leaves_the_locking_shift_where_it_was():
    "It lends a slot. It does not move the one the letters come from."
    screen, stream = _screen()
    stream.feed("\x1b*0\x1bN" + CORNER_IS)
    assert screen.gl == 0
    assert screen.single_shift is None


def test_a_single_shift_waits_for_a_character_and_not_for_a_byte():
    """
    A VT220 spends the shift on the next graphic character. A move of
    the cursor between the two is not one, so it still applies.
    """
    assert _drawn("\x1b*0\x1bN\x1b[3G" + CORNER_IS) == "  " + CORNER


def test_a_single_shift_is_spent_by_the_first_character_of_a_run():
    assert _drawn("\x1b*0\x1bNlqk") == CORNER + "qk"


def test_a_save_and_a_restore_carry_all_four_slots():
    screen, stream = _screen()
    stream.feed("\x1b*0\x1b7\x1b*B\x1b8")
    assert screen.g_charsets[2] is cs.MAPS["0"]


def test_a_restore_does_not_share_the_list_it_restored():
    "A savepoint that shared the list would change under the restore."
    screen, stream = _screen()
    stream.feed("\x1b7\x1b8\x1b*0")
    assert screen.savepoints[-1].g_charsets[2] is cs.LAT1_MAP


def test_a_reset_puts_every_slot_back_to_ascii():
    screen, stream = _screen()
    stream.feed("\x1b*0\x1b+0\x1bn\x1bc")
    assert screen.g_charsets == [cs.LAT1_MAP] * 4
    assert screen.gl == 0


def test_a_national_set_reaches_g2_as_well():
    assert _drawn("\x1b*A\x1bN#") == "£"
