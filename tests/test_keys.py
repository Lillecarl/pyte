"""
Tests for the key data translation in pyte.keys.

`translate_key_data` converts raw key data (as produced by the terminal
feeding the pane) into the encoding that the pane expects, given its
kitty keyboard protocol flags.
"""

import pytest

from pyte.keys import (
    KeyCode,
    KeyEvent,
    Modifier,
    parse_key_data,
    translate_key_data,
    translate_key_event,
)

DISAMBIGUATE = 0b1
EVENT_TYPES = 0b10
ALTERNATE_KEYS = 0b100
REPORT_ALL = 0b1000
ASSOCIATED_TEXT = 0b10000


def test_flags_zero_legacy_passthrough():
    # Legacy data passes through byte-exact.
    assert translate_key_data("hello", flags=0) == "hello"
    assert translate_key_data("\x1ba", flags=0) == "\x1ba"
    assert translate_key_data("\x01", flags=0) == "\x01"
    assert translate_key_data("\x1b[1;5D", flags=0) == "\x1b[1;5D"
    assert translate_key_data("\x1b[2~", flags=0) == "\x1b[2~"
    assert translate_key_data("\x1bOP", flags=0) == "\x1bOP"


def test_the_number_of_a_tilde_key_is_kept():
    """
    "CSI 1 ~" is Home on a VT220, and it is what xterm sends.

    The number is the identity of the key in that form, so it always
    goes out. Every other form has 1 for its default, and the rule that
    leaves a default field empty took the 1 away here as well: a pane
    read "CSI ~", which names no key. Lillecarl/pymux#152.
    """
    assert translate_key_data("\x1b[1~", flags=0) == "\x1b[1~"
    assert translate_key_data("\x1b[1;5~", flags=0) == "\x1b[1;5~"
    assert translate_key_data("\x1b[1~", flags=DISAMBIGUATE) == "\x1b[1~"


def test_flags_zero_kitty_to_legacy():
    # Kitty sequences are translated to their legacy equivalents.
    assert translate_key_data("\x1b[97;5u", flags=0) == "\x01"
    assert translate_key_data("\x1b[13;5u", flags=0) == "\n"
    assert translate_key_data("\x1b[97;3u", flags=0) == "\x1ba"
    assert translate_key_data("\x1b[27u", flags=0) == "\x1b"
    assert translate_key_data("\x1b[97u", flags=0) == "a"


def test_flags_zero_opaque_sequences_pass_through():
    # Replies and unknown sequences are untouched.
    assert translate_key_data("\x1b[?1;2c", flags=0) == "\x1b[?1;2c"
    assert translate_key_data("\x1b[?u", flags=0) == "\x1b[?u"


def test_release_events_are_dropped():
    assert translate_key_data("\x1b[97;1:3u", flags=0) == ""
    assert translate_key_data("a\x1b[97;1:3ub", flags=0) == "ab"


def test_disambiguate_encodes_ctrl_and_alt():
    assert translate_key_data("\x01", flags=DISAMBIGUATE) == "\x1b[97;5u"
    assert translate_key_data("\x1ba", flags=DISAMBIGUATE) == "\x1b[97;3u"
    assert translate_key_data("\x1b", flags=DISAMBIGUATE) == "\x1b[27u"
    # ctrl+enter / ctrl+tab / ctrl+backspace.
    assert translate_key_data("\n", flags=DISAMBIGUATE) == "\x1b[106;5u"
    assert translate_key_data("\x1b[13;5u", flags=DISAMBIGUATE) == "\x1b[13;5u"


def test_disambiguate_keeps_text_and_plain_functional_keys_legacy():
    assert translate_key_data("a", flags=DISAMBIGUATE) == "a"
    assert translate_key_data("A", flags=DISAMBIGUATE) == "A"
    assert translate_key_data("\r", flags=DISAMBIGUATE) == "\r"
    assert translate_key_data("\t", flags=DISAMBIGUATE) == "\t"
    assert translate_key_data("\x7f", flags=DISAMBIGUATE) == "\x7f"
    assert translate_key_data("\x1b[D", flags=DISAMBIGUATE) == "\x1b[D"
    assert translate_key_data("\x1b[15~", flags=DISAMBIGUATE) == "\x1b[15~"


def test_disambiguate_kitty_input_round_trips():
    # Kitty-encoded input re-encodes to the same bytes.
    assert translate_key_data("\x1b[97;5u", flags=DISAMBIGUATE) == "\x1b[97;5u"
    assert translate_key_data("\x1b[97;3u", flags=DISAMBIGUATE) == "\x1b[97;3u"
    assert translate_key_data("\x1b[1;5D", flags=DISAMBIGUATE) == "\x1b[1;5D"


def test_report_all_keys_encodes_everything():
    assert translate_key_data("a", flags=REPORT_ALL) == "\x1b[97u"
    assert translate_key_data("\r", flags=REPORT_ALL) == "\x1b[13u"
    # An arrow keeps the short form: the number of the sequence is one,
    # and kitty leaves out a parameter that holds its default. Only the
    # SS3 form of application mode goes away.
    assert translate_key_data("\x1b[D", flags=REPORT_ALL) == "\x1b[D"
    assert (
        translate_key_data("\x1b[D", flags=REPORT_ALL, application_mode=True)
        == "\x1b[D"
    )
    assert translate_key_data("\x01", flags=REPORT_ALL) == "\x1b[97;5u"


def test_application_cursor_mode():
    # In application cursor mode, unmodified arrows use SS3.
    assert translate_key_data("\x1b[D", flags=0, application_mode=True) == "\x1bOD"
    assert translate_key_data("\x1bOD", flags=0) == "\x1b[D"
    assert translate_key_data("\x1bOD", flags=0, application_mode=True) == "\x1bOD"


def test_text_from_reported_text():
    # "shift+1 with text '!'" translates to '!' in legacy mode.
    assert translate_key_data("\x1b[49;2;33u", flags=0) == "!"
    assert translate_key_data("\x1b[97;2;65u", flags=DISAMBIGUATE) == "A"


def test_shift_only_kitty_input():
    # shift+a without reported text.
    assert translate_key_data("\x1b[97;2u", flags=0) == "A"


def test_mixed_data():
    # Text, control characters and sequences in one chunk.
    data = "a\x01b\x1b[97;5u c"
    assert translate_key_data(data, flags=0) == "a\x01b\x01 c"
    assert translate_key_data(data, flags=DISAMBIGUATE) == "a\x1b[97;5ub\x1b[97;5u c"


def test_trailing_escape():
    assert translate_key_data("\x1b", flags=0) == "\x1b"
    assert translate_key_data("\x1b", flags=DISAMBIGUATE) == "\x1b[27u"


def test_the_key_code_is_the_key_without_shift():
    """
    An upper case letter from a legacy terminal becomes the lower case
    key plus shift, because the protocol asks for the unshifted key.
    """
    assert translate_key_data("A", flags=REPORT_ALL) == "\x1b[97;2u"
    assert translate_key_data("Z", flags=REPORT_ALL) == "\x1b[122;2u"
    # A letter outside ASCII follows the same rule.
    assert translate_key_data("Ä", flags=REPORT_ALL) == "\x1b[228;2u"


def test_a_shifted_character_keeps_its_own_code():
    """
    Which key gives an exclamation mark depends on the layout, and the
    legacy encoding does not say. The character keeps its own code.
    """
    assert translate_key_data("!", flags=REPORT_ALL) == "\x1b[33u"
    assert translate_key_data(":", flags=REPORT_ALL) == "\x1b[58u"


def test_an_upper_case_letter_still_reaches_a_legacy_pane():
    "The shift goes back into the character on the way out."
    assert translate_key_data("A", flags=0) == "A"
    assert translate_key_data("A", flags=DISAMBIGUATE) == "A"
    assert translate_key_data("Ä", flags=0) == "Ä"


# ----------------------------------------------------------------------
# What only a terminal that speaks the protocol can send. pyte passes
# it on when the pane asked for it, and drops it when the pane did not.
# The forms follow the encoder of kitty (kitty/key_encoding.c).

RELEASE = "\x1b[98;5:3u"


def test_a_release_reaches_a_pane_that_asked_for_the_event_types():
    assert translate_key_data(RELEASE, flags=EVENT_TYPES) == "\x1b[98;5:3u"
    assert (
        translate_key_data(RELEASE, flags=EVENT_TYPES | DISAMBIGUATE) == "\x1b[98;5:3u"
    )


def test_a_release_stops_at_a_pane_that_did_not_ask():
    "Nothing in the legacy encoding says that a key came back up."
    assert translate_key_data(RELEASE, flags=0) == ""
    assert translate_key_data(RELEASE, flags=DISAMBIGUATE) == ""
    assert translate_key_data(RELEASE, flags=REPORT_ALL) == ""


def test_a_release_of_a_text_key_writes_modifier_one():
    "The event type needs a modifier field, even when none is active."
    assert translate_key_data("\x1b[97;1:3u", flags=EVENT_TYPES) == "\x1b[97;1:3u"


def test_a_release_of_enter_needs_all_keys_as_escape_codes():
    """
    Enter, Tab and Backspace have a legacy form of one character, and
    kitty reports the release of one of them only when the pane asks
    for every key as an escape code.
    """
    for code in (13, 9, 127):
        release = "\x1b[%d;1:3u" % code
        assert translate_key_data(release, flags=EVENT_TYPES) == ""
        assert translate_key_data(release, flags=EVENT_TYPES | REPORT_ALL) == release


def test_a_repeat_without_the_flag_is_a_press():
    "That is what the key did, and the legacy encoding says no more."
    assert translate_key_data("\x1b[97;1:2u", flags=0) == "a"
    assert translate_key_data("\x1b[97;1:2u", flags=EVENT_TYPES) == "\x1b[97;1:2u"


def test_the_other_codes_of_a_key_reach_a_pane_that_asked():
    "The shifted key and the key of the base layout."
    assert translate_key_data("\x1b[97:65;2u", flags=ALTERNATE_KEYS) == "\x1b[97:65;2u"
    assert (
        translate_key_data("\x1b[97::99;2u", flags=ALTERNATE_KEYS) == "\x1b[97::99;2u"
    )
    # Without the flag they go away, and the key itself stays.
    assert translate_key_data("\x1b[97:65;2u", flags=REPORT_ALL) == "\x1b[97;2u"


def test_the_text_of_a_key_reaches_a_pane_that_asked():
    """
    The text of a printable key needs no modern terminal: the character
    that a legacy terminal sends is the text of that key event.
    """
    assert translate_key_data("A", flags=REPORT_ALL | ASSOCIATED_TEXT) == (
        "\x1b[97;2;65u"
    )
    assert translate_key_data("a", flags=ASSOCIATED_TEXT) == "\x1b[97;;97u"
    # A key that writes no text carries none.
    assert translate_key_data("\r", flags=REPORT_ALL | ASSOCIATED_TEXT) == ("\x1b[13u")
    assert translate_key_data("\x01", flags=REPORT_ALL | ASSOCIATED_TEXT) == (
        "\x1b[97;5u"
    )


# ----------------------------------------------------------------------
# What a legacy keyboard cannot send, made up. A pane that asked for
# the event types reads every key going down and coming up; only the
# time between the two is lost.


def test_a_legacy_key_answers_with_a_press_and_a_release():
    assert translate_key_data("a", flags=EVENT_TYPES) == "a\x1b[97;1:3u"
    assert translate_key_data("a", flags=EVENT_TYPES | DISAMBIGUATE) == "a\x1b[97;1:3u"
    assert translate_key_data("\x01", flags=EVENT_TYPES) == "\x01\x1b[97;5:3u"
    assert translate_key_data("A", flags=EVENT_TYPES) == "A\x1b[97;2:3u"


def test_a_made_up_release_keeps_the_form_of_the_key():
    "An arrow comes up in the form of an arrow, not of a text key."
    assert translate_key_data("\x1b[D", flags=EVENT_TYPES) == "\x1b[D\x1b[1;1:3D"
    assert translate_key_data("\x1b[2~", flags=EVENT_TYPES) == ("\x1b[2~\x1b[2;1:3~")


def test_enter_gets_no_made_up_release_either():
    """
    Enter, Tab and Backspace have no release in the protocol unless the
    pane asks for every key as an escape code. The rule that drops a
    real one drops a made up one.
    """
    assert translate_key_data("\r", flags=EVENT_TYPES) == "\r"
    assert translate_key_data("\t", flags=EVENT_TYPES) == "\t"
    assert translate_key_data("\r", flags=EVENT_TYPES | REPORT_ALL) == (
        "\x1b[13u\x1b[13;1:3u"
    )


def test_a_keyboard_that_sends_its_own_release_is_left_alone():
    "Two releases for one key would be worse than none."
    assert translate_key_data("a", flags=EVENT_TYPES, source_flags=0b11111) == "a"
    assert (
        translate_key_data("\x1b[97;1:3u", flags=EVENT_TYPES, source_flags=0b11111)
        == "\x1b[97;1:3u"
    )


def test_nothing_is_made_up_without_the_switch():
    "The host can ask for presses only. The pane then hears that."
    assert translate_key_data("a", flags=EVENT_TYPES, synthesize=False) == "a"
    assert translate_key_data("\x01", flags=EVENT_TYPES, synthesize=False) == "\x01"


def test_a_pane_that_asked_for_no_event_type_reads_no_release():
    assert translate_key_data("a", flags=0) == "a"
    assert translate_key_data("a", flags=DISAMBIGUATE) == "a"
    assert translate_key_data("a", flags=REPORT_ALL) == "\x1b[97u"


def test_the_shifted_key_of_a_letter_is_the_letter():
    """
    A pane that asks for the other codes of a key gets that one from a
    legacy keyboard as well. The key of the base layout stays out: it
    is the key itself on every Latin layout, and kitty leaves it out
    there too.
    """
    assert translate_key_data("A", flags=ALTERNATE_KEYS | REPORT_ALL) == (
        "\x1b[97:65;2u"
    )
    assert translate_key_data("Ä", flags=ALTERNATE_KEYS | REPORT_ALL) == (
        "\x1b[228:196;2u"
    )


def test_a_key_with_no_shifted_key_of_its_own_reports_none():
    "Which key gives an exclamation mark is a question of the layout."
    assert translate_key_data("!", flags=ALTERNATE_KEYS | REPORT_ALL) == ("\x1b[33u")
    assert translate_key_data("a", flags=ALTERNATE_KEYS | REPORT_ALL) == ("\x1b[97u")


def test_the_shifted_key_waits_for_a_pane_that_asked():
    assert translate_key_data("A", flags=REPORT_ALL) == "\x1b[97;2u"
    assert translate_key_data("A", flags=0) == "A"


def test_the_ss3_form_belongs_to_a_pane_that_pushed_no_flag():
    """
    kitty sends the SS3 form of an arrow or of F1 only in what it calls
    the legacy mode: no disambiguate, no event types, no report of all
    keys. A pane that pushed one of those reads the CSI form.
    """
    assert translate_key_data("\x1bOD", flags=0, application_mode=True) == "\x1bOD"
    assert translate_key_data("\x1bOP", flags=0) == "\x1bOP"
    for flags in (DISAMBIGUATE, EVENT_TYPES, REPORT_ALL):
        assert (
            translate_key_data("\x1bOD", flags=flags, application_mode=True)[:3]
            == "\x1b[D"[:3]
        )
        assert translate_key_data("\x1bOP", flags=flags)[:3] == "\x1b[P"


#: One row per key: the name, what a terminal in the legacy encoding
#: sends, and what the same terminal sends once something asked it to
#: disambiguate.
#:
#: The keypad is the interesting part. A terminal folds it onto the
#: main keyboard while it speaks the legacy encoding, and stops as soon
#: as anything asks it to disambiguate. So a pane that asked for
#: nothing reads a keypad key only if this end folds it back.
WHAT_A_KEYBOARD_SENDS = [
    ("escape", "\x1b", "\x1b[27u"),
    ("ctrl+a", "\x01", "\x1b[97;5u"),
    ("alt+a", "\x1ba", "\x1b[97;3u"),
    ("ctrl+i", "\t", "\x1b[105;5u"),
    ("keypad 0", "0", "\x1b[57399u"),
    ("keypad 9", "9", "\x1b[57408u"),
    ("keypad .", ".", "\x1b[57409u"),
    ("keypad /", "/", "\x1b[57410u"),
    ("keypad *", "*", "\x1b[57411u"),
    ("keypad -", "-", "\x1b[57412u"),
    ("keypad +", "+", "\x1b[57413u"),
    ("keypad enter", "\r", "\x1b[57414u"),
    ("keypad =", "=", "\x1b[57415u"),
    ("keypad left", "\x1b[D", "\x1b[57417u"),
    ("keypad up", "\x1b[A", "\x1b[57419u"),
    ("keypad page up", "\x1b[5~", "\x1b[57421u"),
    ("keypad home", "\x1b[H", "\x1b[57423u"),
    ("keypad insert", "\x1b[2~", "\x1b[57425u"),
    ("keypad delete", "\x1b[3~", "\x1b[57426u"),
]

#: Keys that the protocol numbers and the legacy encoding cannot write.
#: A terminal reports one only when something asked it to.
KEYS_WITH_NO_LEGACY_FORM = [
    ("caps lock", "\x1b[57358u"),
    ("menu", "\x1b[57363u"),
    ("f13", "\x1b[57376u"),
    ("keypad separator", "\x1b[57416u"),
    ("play", "\x1b[57428u"),
    ("left shift", "\x1b[57441u"),
    ("right super", "\x1b[57450u"),
]


def test_a_pane_reads_the_same_key_from_either_keyboard():
    """
    A terminal that speaks the protocol is a terminal that speaks the
    legacy encoding, plus more. So a pane that asked for nothing must
    read one key the same way from both, or asking the terminal of the
    person for the protocol would change what every program reads.

    Lillecarl/pymux#166.
    """
    for name, legacy, protocol in WHAT_A_KEYBOARD_SENDS:
        assert translate_key_data(protocol, flags=0) == translate_key_data(
            legacy, flags=0
        ), name


def test_a_key_the_legacy_encoding_cannot_write_reaches_no_such_pane():
    """
    The protocol numbers these in the Private Use Area, and `chr` of
    one of them is a character no keyboard has. A pane that asked for
    nothing hears nothing, which is what kitty does as well.
    """
    for name, protocol in KEYS_WITH_NO_LEGACY_FORM:
        assert translate_key_data(protocol, flags=0) == "", name


def test_a_pane_that_asked_reads_the_number_of_the_key():
    "The fold is for the legacy encoding. It must not hide a key."
    assert translate_key_data("\x1b[57399u", flags=DISAMBIGUATE) == ("\x1b[57399u")
    assert translate_key_data("\x1b[57441u", flags=DISAMBIGUATE) == ("\x1b[57441u")
    assert translate_key_data("\x1b[57376u", flags=REPORT_ALL) == "\x1b[57376u"
    assert translate_key_data("\x1b[57399u", flags=ASSOCIATED_TEXT) == ("\x1b[57399u")


#: A key in xterm's modifyOtherKeys form, and the bytes a pane that
#: asked for nothing has to read for it.
#:
#: The third parameter is the value of the key without its modifiers.
#: xterm gives two examples: alt+Tab is "CSI 27 ; 3 ; 9 ~" and
#: shift+Tab is "CSI 27 ; 2 ; 9 ~" (`ctlseqs.ms`, under "Alt and Meta
#: Keys"). Level 3 sends an unmodified key as well.
MODIFY_OTHER_KEYS = [
    ("ctrl+a", "\x1b[27;5;97~", "\x01"),
    ("alt+a", "\x1b[27;3;97~", "\x1ba"),
    ("ctrl+shift+a", "\x1b[27;6;97~", "\x01"),
    ("ctrl+enter", "\x1b[27;5;13~", "\n"),
    ("shift+enter", "\x1b[27;2;13~", "\r"),
    ("alt+tab", "\x1b[27;3;9~", "\x1b\t"),
    ("space, at level 3", "\x1b[27;1;32~", " "),
]


def test_a_key_in_the_modify_other_keys_form_is_the_key_it_names():
    """
    The key is in the third parameter and the first one names the
    form. Reading the first as the key gave the wrong one: ctrl+a,
    alt+a and ctrl+enter all came out as "CSI 27 ; mods ~", which
    names none of them and no other key either. Lillecarl/pymux#171.
    """
    for name, sequence, legacy in MODIFY_OTHER_KEYS:
        assert translate_key_data(sequence, flags=0) == legacy, name


def test_a_pane_that_asked_reads_the_same_key_in_its_own_form():
    "One key event in the middle, and each end writes its own form."
    assert translate_key_data("\x1b[27;5;97~", flags=DISAMBIGUATE) == ("\x1b[97;5u")
    assert translate_key_data("\x1b[27;3;9~", flags=REPORT_ALL) == "\x1b[9;3u"


def test_a_real_tilde_key_is_not_a_modify_other_keys_key():
    """
    The "~" form numbers a key from the table of the VT220, which
    stops well short of 27, so nothing else has this shape. These are
    the keys that would be lost if it did.
    """
    assert translate_key_data("\x1b[3~", flags=0) == "\x1b[3~"
    assert translate_key_data("\x1b[15;5~", flags=0) == "\x1b[15;5~"
    assert translate_key_data("\x1b[2;3~", flags=0) == "\x1b[2;3~"
    # Three parameters, and the first is not 27.
    assert translate_key_data("\x1b[15;5;97~", flags=0) == "\x1b[15;5~"


def test_shift_and_tab_is_the_back_tab_in_the_legacy_encoding():
    """
    The legacy encoding has a sequence for this one key with a
    modifier, and it is what a shell and a readline prompt read to
    cycle a completion backwards. Without it the shift was dropped and
    the pane read a plain Tab. Lillecarl/pymux#174.
    """
    assert translate_key_data("\x1b[9;2u", flags=0) == "\x1b[Z"
    assert translate_key_data("\x1b[27;2;9~", flags=0) == "\x1b[Z"
    # Ctrl has no legacy form on this key, and kitty loses it too.
    assert translate_key_data("\x1b[9;6u", flags=0) == "\x1b[Z"


def test_alt_and_the_back_tab_take_a_second_escape():
    """
    It is the only key whose alt form doubles the escape, because
    "CSI Z" already begins with one. kitty writes it the same way.
    """
    assert translate_key_data("\x1b[9;4u", flags=0) == "\x1b\x1b[Z"


def test_the_back_tab_belongs_to_the_legacy_mode_alone():
    """
    A pane that asked for more reads the number of the key.

    The event types are in here because kitty counts them in its
    legacy mode as well. A pane that asked for those and nothing else
    reads a press and a release, so the release is left off to keep
    the case about the form and not about the synthesis.
    """
    for flags in (DISAMBIGUATE, REPORT_ALL):
        assert translate_key_data("\x1b[9;2u", flags=flags) == "\x1b[9;2u"
    assert (
        translate_key_data("\x1b[9;2u", flags=EVENT_TYPES, synthesize=False)
        == "\x1b[9;2u"
    )


def test_a_back_tab_from_a_legacy_keyboard_reaches_the_pane_in_its_form():
    """
    `CSI Z` is shift and tab, and a pane that asked for the protocol
    reads it as one.

    It used to pass through to every pane, because the parser could not
    read the form the encoder writes. The encoder has always meant
    otherwise: its back tab branch sends `CSI 9;2u` to a pane that is
    not in the legacy mode. Lillecarl/pymux#174, Lillecarl/pymux#237.
    """
    assert translate_key_data("\x1b[Z", flags=0) == "\x1b[Z"
    for flags in (DISAMBIGUATE, REPORT_ALL):
        assert translate_key_data("\x1b[Z", flags=flags) == "\x1b[9;2u"


def test_f3_takes_the_tilde_form_for_a_pane_that_speaks_the_protocol():
    """
    F3 is the one key of the function row that kitty numbers instead of
    naming with a letter, because "CSI R" is the cursor position report.

    Its own encoder says so: `encode_key_event` writes "CSI 13~" for F3
    and keeps "CSI P", "CSI Q" and "CSI S" for F1, F2 and F4. Its
    decoder says the same in the other direction, and raises
    `KeyError: 'R'` on what pyte used to write here.
    Lillecarl/pymux#242.
    """
    assert translate_key_data("\x1bOR", flags=DISAMBIGUATE) == "\x1b[13~"
    assert translate_key_data("\x1b[13;5~", flags=DISAMBIGUATE) == "\x1b[13;5~"
    assert translate_key_data("\x1bOP", flags=DISAMBIGUATE) == "\x1b[P"


def test_f3_keeps_its_letter_for_a_legacy_pane():
    """
    Eight terminfo entries against one. xterm, xterm-256color, foot,
    wezterm, ghostty, alacritty, vte-256color and tmux-256color all
    give `kf3=\\EOR` and `kf27=\\E[1;5R`; kitty alone gives
    `kf27=\\E[13;5~`. screen names no modified F3 at all, and the Linux
    console is its own scheme (`kf3=\\E[[C`, `kf15=\\E[28~`).

    pyte's own entry names `xterm-256color` as its parent, so it
    publishes the first pair, and the bytes have to be the ones the
    entry promises.
    """
    assert translate_key_data("\x1b[13~", flags=0) == "\x1bOR"
    assert translate_key_data("\x1b[13;5~", flags=0) == "\x1b[1;5R"


def test_ctrl_and_f3_reaches_a_legacy_pane_as_a_cursor_report():
    """
    The one key pyte writes and cannot read back.

    "CSI 1;5R" is ctrl+F3 to every entry that names one but kitty's,
    and a report of row 1, column 5 to every program that just asked
    where the cursor is. The bytes alone do not tell them apart, so the
    parser keeps the report: a reply a program waits for costs more
    than a key it rarely presses.
    """
    written = translate_key_event(KeyEvent(1, Modifier.CTRL, "R"), flags=0)

    assert written == "\x1b[1;5R"
    assert parse_key_data(written) == [written]


def test_f3_is_one_event_in_both_of_its_forms():
    "Enter shares the number and not the final byte, and stays Enter."
    assert parse_key_data("\x1b[13~") == [KeyEvent(1, 0, "R")]
    assert parse_key_data("\x1bOR") == [KeyEvent(1, 0, "R")]
    assert parse_key_data("\x1b[13;5~") == [KeyEvent(1, Modifier.CTRL, "R")]
    assert parse_key_data("\x1b[13u") == [KeyEvent(KeyCode.ENTER, 0, "u")]


def _every_key_worth_writing():
    "One event of every shape the encoder can write."
    for code in (ord("a"), ord("1"), KeyCode.ENTER, KeyCode.TAB, KeyCode.ESCAPE):
        for mods in (0, Modifier.CTRL, Modifier.SHIFT, Modifier.ALT):
            yield KeyEvent(code, mods, "u")
    for code in (2, 3, 5, 6, 15, 17, 24):
        for mods in (0, Modifier.CTRL, Modifier.CTRL | Modifier.SHIFT):
            yield KeyEvent(code, mods, "~")
    for final in "ABCDEFHPQRS":
        for mods in (0, Modifier.CTRL, Modifier.SHIFT):
            yield KeyEvent(1, mods, final)
    yield KeyEvent(KeyCode.TAB, Modifier.SHIFT, "u")


@pytest.mark.parametrize("event", list(_every_key_worth_writing()))
@pytest.mark.parametrize("flags", [0, DISAMBIGUATE])
def test_the_parser_reads_back_what_the_encoder_writes(event, flags):
    """
    **pyte has to be able to read its own output.**

    It could not, twice. The encoder writes back tab as "CSI Z" and F3
    as "ESC O R", and the parser read neither: "Z" is not a final byte
    of the letter form, and "R" is left out of it because "CSI R" is
    the cursor position report. So a back tab reaching a pane that
    speaks the protocol became three bytes of nothing, and nothing said
    so, because F3 was read through prompt_toolkit's table on the way
    in and never through this one.
    """
    if event.final == "R" and event.mods and not flags:
        # ctrl+F3 to a legacy pane is "CSI 1;5R", the cursor position
        # report byte for byte, and the parser keeps the report. It is
        # the one hole left in this walk, and
        # `test_ctrl_and_f3_reaches_a_legacy_pane_as_a_cursor_report`
        # is where it is written down. Lillecarl/pymux#242.
        return

    encoded = translate_key_event(event, flags=flags)
    if not encoded:
        return

    read_back = [item for item in parse_key_data(encoded) if isinstance(item, KeyEvent)]
    assert read_back, "nothing read %r back" % (encoded,)


def test_a_plain_tab_is_not_a_back_tab():
    assert translate_key_data("\t", flags=0) == "\t"
    assert translate_key_data("\x1b[9;5u", flags=0) == "\t"
    assert translate_key_data("\x1b[9;3u", flags=0) == "\x1b\t"


def test_a_folded_keypad_key_follows_the_cursor_key_mode():
    "The fold gives a normal key, and a normal arrow reads DECCKM."
    assert translate_key_data("\x1b[57419u", flags=0, application_mode=True) == "\x1bOA"
    assert translate_key_data("\x1b[57419u", flags=0) == "\x1b[A"
