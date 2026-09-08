"""
The extended keyboard mode, which xterm calls modifyOtherKeys.

A program has two ways to ask for more than the legacy encoding. The
kitty keyboard protocol is one, and this is the older one that far
more programs use: vim, neovim, emacs and kakoune all ask for it.

`CSI > 4 ; Pv m` sets it (XTMODKEYS resource 4) and `CSI ? 4 m` asks
what it is (XTQMODKEYS). A key that leaves the legacy encoding goes
out as `CSI 27 ; mods ; code ~`, and the third parameter is the value
of the key without its modifiers.

The levels are xterm's, and so are the examples:
`xterm-snapshots/ctlseqs.ms`, under "Alt and Meta Keys".
Lillecarl/pymux#169.
"""
import pyte
from pyte.keys import (
    FormatOtherKeys,
    KeyModifierResource,
    ModifyOtherKeys,
)


def a_screen():
    "A screen, and the list of everything it replies."
    replies = []
    screen = pyte.Screen(20, 5, write_process_input=replies.append)
    return screen, pyte.Stream(screen), replies


def test_nothing_leaves_the_legacy_encoding_to_begin_with():
    screen, _, _ = a_screen()
    assert screen.modify_other_keys == ModifyOtherKeys.OFF
    assert screen.encode_key("\x01") == "\x01"


def test_a_program_asks_with_xtmodkeys():
    screen, stream, _ = a_screen()

    stream.feed("\x1b[>4;2m")

    assert screen.modify_other_keys == ModifyOtherKeys.EVERY_MODIFIER
    assert screen.encode_key("\x01") == "\x1b[27;5;97~"


def test_alt_and_meta_is_the_first_level():
    """
    "the usual shift- and control-modifiers work as expected, but
    other modifiers cause ordinary keys to be encoded as if they were
    function-keys. For example, alt-Tab sends CSI 27 ; 3 ; 9 ~"
    """
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;1m")

    assert screen.encode_key("\x1b\t") == "\x1b[27;3;9~"
    assert screen.encode_key("\x01") == "\x01"
    assert screen.encode_key("A") == "A"


def test_every_modifier_is_the_second_level():
    """
    "all of the modifiers apply. For example, shift-Tab sends
    CSI 27 ; 2 ; 9 ~ rather than CSI Z"
    """
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m")

    assert screen.encode_key("\x1b[9;2u") == "\x1b[27;2;9~"
    assert screen.encode_key("\x01") == "\x1b[27;5;97~"


def test_a_capital_letter_is_still_a_capital_letter():
    """
    Shift on a letter gives a character, and a terminal sends the
    character. Otherwise a person typing into vim, which asks for this
    level, would put escape sequences in the buffer.
    """
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m")

    assert screen.encode_key("A") == "A"
    assert screen.encode_key("a") == "a"


def test_every_key_is_the_third_level():
    '"unmodified keys also are sent as escape sequences. space sends CSI 27 ; 1 ; 32 ~"'
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;3m")

    assert screen.encode_key(" ") == "\x1b[27;1;32~"
    assert screen.encode_key("a") == "\x1b[27;1;97~"


def test_the_arrows_are_not_other_keys():
    "A cursor key has its own resource, and this one does not touch it."
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;3m")

    assert screen.encode_key("\x1b[A") == "\x1b[A"
    assert screen.encode_key("\x1b[1;5A") == "\x1b[1;5A"


def test_a_resource_alone_puts_that_one_back():
    "A program that is finishing sends `CSI > 4 m`."
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m")
    stream.feed("\x1b[>4m")

    assert screen.modify_other_keys == ModifyOtherKeys.OFF
    assert screen.encode_key("\x01") == "\x01"


def test_a_parameter_that_is_left_out_reads_as_zero():
    """
    xterm puts every resource back when XTMODKEYS carries no
    parameter at all, and `CSI > 0 m` puts back modifyKeyboard alone.

    **This screen cannot tell the two apart.** The CSI parser turns an
    empty parameter into a zero, so both arrive as the number zero and
    the narrower reading wins. Nothing sends `CSI > m`, and a program
    that did would find modifyKeyboard reset and nothing else.
    Lillecarl/pymux#178.
    """
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>0;2m")
    stream.feed("\x1b[>4;2m")

    stream.feed("\x1b[>m")

    assert KeyModifierResource.KEYBOARD not in screen.key_modifier_options
    assert screen.modify_other_keys == ModifyOtherKeys.EVERY_MODIFIER


def test_a_reset_puts_it_back():
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m")

    stream.feed("\x1bc")

    assert screen.modify_other_keys == ModifyOtherKeys.OFF


def test_it_survives_the_alternate_screen():
    """
    xterm holds this as a resource of the terminal and not as state of
    a screen, so a program that switches screens keeps what it set.
    The kitty flag stack is the other way, and that is why the two are
    kept apart.
    """
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m")

    stream.feed("\x1b[?1049h")
    assert screen.modify_other_keys == ModifyOtherKeys.EVERY_MODIFIER
    stream.feed("\x1b[?1049l")
    assert screen.modify_other_keys == ModifyOtherKeys.EVERY_MODIFIER


def test_a_program_can_ask_what_it_is_set_to():
    """
    The answer is an XTMODKEYS control, so a program can send it back
    to restore the state. That is xterm's reason for the shape.
    """
    screen, stream, replies = a_screen()
    stream.feed("\x1b[>4;2m")

    stream.feed("\x1b[?4m")

    assert replies == ["\x1b[>4;2m"]


def test_a_resource_nobody_set_answers_zero():
    """
    xterm starts some of them at other numbers, because it really does
    encode a cursor key that way. This screen does not.
    """
    screen, stream, replies = a_screen()

    stream.feed("\x1b[?%dm" % KeyModifierResource.CURSOR_KEYS)

    assert replies == ["\x1b[>1;0m"]


def test_a_resource_this_screen_ignores_is_still_remembered():
    """
    A resource that is remembered and not acted on is honest. One that
    is forgotten makes a program believe it failed to set it.
    """
    screen, stream, replies = a_screen()

    stream.feed("\x1b[>2;3m")
    stream.feed("\x1b[?2m")

    assert replies == ["\x1b[>2;3m"]


def test_the_kitty_flags_win():
    """
    A program asks for one mode or the other. A terminal that had both
    would have to say which wins, and the flag stack does: every
    branch of the encoder answers before the extended one.
    """
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m")
    stream.feed("\x1b[>1u")  # disambiguate

    assert screen.encode_key("\x01") == "\x1b[97;5u"


def test_a_pane_the_host_holds_back_stays_in_the_legacy_encoding():
    """
    The escape hatch, for a program that misbehaves under the extended
    encodings. The pane hears it: it answers what it really does, and
    not what it asked for, so a program that queries is told the
    truth. Lillecarl/pymux#173.
    """
    screen, stream, replies = a_screen()
    stream.feed("\x1b[>4;2m")
    assert screen.encode_key("\x01") == "\x1b[27;5;97~"

    screen.extended_keys_allowed = False

    assert screen.modify_other_keys == ModifyOtherKeys.OFF
    assert screen.encode_key("\x01") == "\x01"
    replies.clear()
    stream.feed("\x1b[?4m")
    assert replies == ["\x1b[>4;0m"]


def test_the_kitty_flags_go_with_it():
    "One hatch, and both ways in are behind it."
    screen, stream, replies = a_screen()
    stream.feed("\x1b[>1u")
    assert screen.encode_key("\x01") == "\x1b[97;5u"

    screen.extended_keys_allowed = False

    assert screen.deliverable_kitty_keyboard_flags == 0
    assert screen.encode_key("\x01") == "\x01"
    replies.clear()
    stream.feed("\x1b[?u")
    assert replies == ["\x1b[?0u"]


def test_what_the_pane_asked_for_is_not_forgotten():
    "The hatch closes and the pane has what it set, still."
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m")

    screen.extended_keys_allowed = False
    screen.extended_keys_allowed = True

    assert screen.modify_other_keys == ModifyOtherKeys.EVERY_MODIFIER


# ----------------------------------------------------------------------
# Which of the two forms it writes. XTFMTKEYS, resource 4.


def test_the_tilde_form_is_the_one_a_terminal_writes():
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m")

    assert screen.format_other_keys == FormatOtherKeys.TILDE
    assert screen.encode_key("\x01") == "\x1b[27;5;97~"


def test_a_program_can_ask_for_the_csi_u_form():
    """
    xterm's own example: "when modifyOtherKeys is set to 1, for
    example alt-Tab sends CSI 9 ; 3 u (changing the order of
    parameters)". Lillecarl/pymux#183.
    """
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;1m")

    stream.feed("\x1b[>4;1f")

    assert screen.format_other_keys == FormatOtherKeys.CSI_U
    assert screen.encode_key("\x1b\t") == "\x1b[9;3u"


def test_the_form_can_be_put_back():
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m\x1b[>4;1f")

    stream.feed("\x1b[>4;0f")

    assert screen.encode_key("\x01") == "\x1b[27;5;97~"


def test_xtfmtkeys_does_not_move_the_cursor():
    """
    Its final byte is the one HVP has, and the private marker is the
    whole difference. Reading it as a position moved the cursor to row
    four, and every character the program drew after it landed in the
    wrong place. Lillecarl/pymux#183.
    """
    screen, stream, _ = a_screen()
    stream.feed("\x1b[3;3H")
    where = (screen.pt_cursor_position.x, screen.pt_cursor_position.y)

    stream.feed("\x1b[>4;1f")

    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == where


def test_the_query_does_not_clear_a_tab_stop():
    "Its final byte is TBC's, and again the marker is the difference."
    screen, stream, replies = a_screen()
    stops = set(screen.tabstops)

    stream.feed("\x1b[?4g")

    assert set(screen.tabstops) == stops
    assert replies == ["\x1b[>4;0f"]


def test_the_query_answers_what_the_screen_really_writes():
    screen, stream, replies = a_screen()
    stream.feed("\x1b[>4;1f")

    stream.feed("\x1b[?4g")

    assert replies == ["\x1b[>4;1f"]


def test_a_pane_the_host_holds_back_writes_neither_form():
    "A form nothing writes is not a form."
    screen, stream, _ = a_screen()
    stream.feed("\x1b[>4;2m\x1b[>4;1f")

    screen.extended_keys_allowed = False

    assert screen.format_other_keys == FormatOtherKeys.TILDE
    assert screen.encode_key("\x01") == "\x01"


def test_the_private_marker_is_not_sgr():
    """
    "CSI > Ps m" and "CSI ? Ps m" both end in the final byte of SGR.
    Reading either as SGR turns the underline on, and everything the
    program draws after it carries a line it never asked for.
    """
    screen, stream, _ = a_screen()

    stream.feed("\x1b[>4;2m")
    stream.feed("\x1b[?4m")
    stream.feed("x")

    assert not screen.page.data_buffer[0][0].appearance.rendition.underline
