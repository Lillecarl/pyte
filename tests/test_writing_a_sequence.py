"""
Building a sequence from the name of what it is.

Escape sequences reach this codebase as hand-typed strings in a few
thousand places. Every one of them packs typed values into positional
slots of a plain string: `"\\x1b[97;5u"` carries a code point and a
mask of modifiers, `"\\x1b[?1049h"` carries a mode number. Getting a
digit wrong compiles and passes review as easily as getting it right.
Lillecarl/pymux#165.

**This file keeps its literals, and it is the only one that should.**
The bytes here are what proves the builder, so writing them through
the builder would prove nothing. Everywhere else is the other way
round: the builder says what the sequence means, and this says what
the builder writes.

The literals are also why `pyte/tools/name_the_sequences.py` may not
touch this file, and its exclusion list says so.
"""

import pytest

from pyte import escape
from pyte.modes import AnsiMode, PrivateMode
from pyte.osc import Osc
from pyte.sequences import (
    Csi,
    Escape,
    Sharp,
    Terminator,
    announce,
    apc,
    csi,
    dcs,
    decrqss,
    esc,
    osc,
    reset_mode,
    set_mode,
    sharp,
)


def test_a_sequence_with_no_parameters():
    assert csi(escape.CUB) == "\x1b[D"
    assert csi(escape.ED) == "\x1b[J"


def test_a_sequence_with_parameters():
    assert csi(escape.CUP, 1, 1) == "\x1b[1;1H"
    assert csi(Csi.SD, 2) == "\x1b[2T"
    assert csi(escape.DECSTBM, 2, 4) == "\x1b[2;4r"


def test_the_intermediate_bytes_go_after_the_parameters():
    """
    A final byte carries its intermediates, and they belong at the end.

    DECSCUSR is "CSI Ps SP q": the space is part of the name and the
    parameter comes before it. Writing the name in front of the
    parameter gives "CSI SP q Ps", which is not a sequence at all.
    """
    assert csi(Csi.DECSCUSR, 4) == "\x1b[4 q"
    assert csi(Csi.DECSTR) == "\x1b[!p"
    assert csi(Csi.KITTY_UNSCROLL, 3) == "\x1b[3 D"


def test_an_empty_parameter_is_written_as_nothing():
    "Which is how a program asks for the default of that position."
    assert csi(escape.CUP, None, 5) == "\x1b[;5H"
    assert csi(escape.CUP, 5, None) == "\x1b[5;H"
    assert csi(escape.SGR, None) == "\x1b[m"


def test_subparameters_are_joined_by_colons():
    assert csi(escape.SGR, 38, (2, 1, 2, 3)) == "\x1b[38;2:1:2:3m"
    assert csi(Csi.KITTY_KEYBOARD, (97, 65), 5) == "\x1b[97:65;5u"


def test_an_empty_subparameter_is_written_as_nothing():
    "The colon form of an RGB colour leaves the colour space out."
    assert csi(escape.SGR, 38, (2, None, 1, 2, 3)) == "\x1b[38;2::1:2:3m"


def test_the_private_marker_goes_before_the_parameters():
    assert csi(escape.DA, 62, 1, 6, private="?") == "\x1b[?62;1;6c"
    assert csi(escape.SGR, 4, 2, private=">") == "\x1b[>4;2m"
    assert csi(Csi.KITTY_KEYBOARD, 1, private=">") == "\x1b[>1u"


# ----------------------------------------------------------------------
# The sequences that are ESC and one or two more bytes.


def test_an_escape_sequence_with_no_intermediate_byte():
    assert esc(escape.RIS) == "\x1bc"
    assert esc(escape.RI) == "\x1bM"
    assert esc(Escape.DECID) == "\x1bZ"


def test_the_sharp_family():
    assert sharp(Sharp.DECDWL) == "\x1b#6"
    assert sharp(Sharp.DECDHL_TOP) == "\x1b#3"
    assert sharp(Sharp.DECSWL) == "\x1b#5"


def test_the_intermediate_byte_is_the_whole_difference():
    """
    "ESC 8" restores the cursor and "ESC # 8" fills the screen with
    "E". The final byte is the same, and only the "#" says which.
    """
    assert esc(escape.DECRC) == "\x1b8"
    assert sharp(Sharp.DECALN) == "\x1b#8"


def test_an_announcer():
    "ECMA-48's name for 'ESC SP <final>'."
    assert announce(escape.S7C1T) == "\x1b F"
    assert announce(escape.S8C1T) == "\x1b G"


# ----------------------------------------------------------------------
# The ones that carry a payload rather than parameters.


def test_an_operating_system_command():
    assert osc(Osc.PALETTE_COLOR, "3", "#aabbcc") == "\x1b]4;3;#aabbcc\x1b\\"
    assert osc("0", "a title") == "\x1b]0;a title\x1b\\"


def test_a_code_with_no_payload():
    assert osc(Osc.RESET_PALETTE_COLOR) == "\x1b]104\x1b\\"


def test_an_empty_field_is_still_a_field():
    "A hyperlink with no parameters and no target closes the last one."
    assert osc(Osc.HYPERLINK, "", "") == "\x1b]8;;\x1b\\"


def test_the_bell_ends_an_osc_as_well():
    """
    Two spellings, and a terminal reads both. Enough programs send the
    bell that a terminal which refused it would look broken.
    """
    assert osc("11", "?", end=Terminator.BEL) == "\x1b]11;?\x07"
    assert osc("11", "?") == "\x1b]11;?\x1b\\"


def test_a_device_control_string():
    assert dcs("1$r0m") == "\x1bP1$r0m\x1b\\"


def test_asking_a_setting_back():
    """
    DECRQSS takes the name of the sequence that would set the thing,
    so it takes the same members `csi` does.
    """
    assert decrqss(escape.SGR) == "\x1bP$qm\x1b\\"
    assert decrqss(Csi.DECSCUSR) == "\x1bP$q q\x1b\\"
    assert decrqss(Csi.DECSCL) == '\x1bP$q"p\x1b\\'


def test_an_application_programming_command():
    "The kitty graphics protocol is the only one here that uses it."
    assert apc("Gi=31;OK") == "\x1b_Gi=31;OK\x1b\\"


def test_a_mode_says_its_own_marker():
    assert set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) == "\x1b[?1049h"
    assert reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) == "\x1b[?1049l"
    assert set_mode(AnsiMode.INSERT_REPLACE) == "\x1b[4h"
    assert reset_mode(AnsiMode.INSERT_REPLACE) == "\x1b[4l"


def test_several_modes_go_in_one_sequence():
    assert set_mode(PrivateMode.ORIGIN, PrivateMode.AUTOWRAP) == "\x1b[?6;7h"


def test_the_two_kinds_of_mode_cannot_share_a_sequence():
    """
    The marker belongs to the sequence and not to the parameter, so a
    sequence that held both would say the wrong thing about one of
    them.
    """
    with pytest.raises(ValueError):
        set_mode(PrivateMode.ORIGIN, AnsiMode.INSERT_REPLACE)


def test_a_bare_number_is_not_a_mode():
    """
    A number says nothing about the marker it takes, so a builder that
    accepted one would have to guess. "CSI 1049 h" and
    "CSI ? 1049 h" are different sequences and only one of them
    exists.

    A mode that `modes.py` does not name is written the long way,
    where the marker is said out loud.
    """
    with pytest.raises(ValueError):
        set_mode(1049)

    assert csi(escape.SM, 2026, private="?") == "\x1b[?2026h"


def test_no_mode_at_all_is_not_a_sequence():
    with pytest.raises(ValueError):
        set_mode()
