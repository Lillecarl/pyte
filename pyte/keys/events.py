"""
What a key event is: the modifiers, the key codes, the flags a program
asks for, and whose legacy answer a pane gets (`KeyProfile`). Every
reader and every writer of key bytes meets in `KeyEvent`.
"""

from __future__ import annotations

from enum import IntEnum, IntFlag
from typing import NamedTuple

__all__ = [
    "CSI",
    "DEFAULT_KEY_PROFILE",
    "FIRST_FUNCTIONAL_KEY",
    "KEY_PROFILES",
    "MODIFIER_KEYS",
    "SS3",
    "EventType",
    "FlagsMode",
    "FormatOtherKeys",
    "FunctionalKey",
    "KeyCode",
    "KeyEvent",
    "KeyModifierResource",
    "KeyProfile",
    "KeyboardFlag",
    "Modifier",
    "ModifyOtherKeys",
    "TildeKey",
]


# Why the two flag sets below hand their arithmetic back to `int`.
#
# `Flag.__and__` calls `_get_value` on both operands and builds a
# member for the answer. Measured on one key press: 1,359 bytecode
# instructions, 11% of the whole key stage, and none of it decides
# anything -- every answer here is tested for truth or used as a
# number.
#
# One `&` costs 449ns between two members, and **686ns with an int on
# one side**, because `int.__and__` answers NotImplemented and python
# dispatches to the member a second time. Against int's own operators
# it is 52ns.
#
# **So testing against `.value` would be slower, not faster**, unless
# every site and every flags value went int in the same move. Handing
# the operators back cannot be half done, and no call site changes.
#
# What it gives up: `a | b` is an int, not a member, so it reprs as a
# number. Nothing reads a name off a combination -- `key_spelling.py`
# takes `.name` off one member at a time. Lillecarl/pymux#359.


class Modifier(IntFlag):
    """
    The modifier keys held down with a key.

    The value in a CSI u sequence is one plus the sum of these bits, so
    a sequence with no modifier carries a one and not a zero.

    The first three are the ones the legacy encoding can write. The
    rest it cannot, which is why a key that carries one of them has to
    leave that encoding: kitty's rule is that "all key events that do
    not generate text" go out as an escape code
    (`docs/keyboard-protocol.rst`, under the disambiguate flag).

    **The two locks are not in that group.** kitty says so in the same
    place: "the Lock modifiers are not reported for text producing
    keys, to keep them usable in legacy programs". Caps lock on a
    letter gives the capital, and that is text.
    """

    SHIFT = 1
    ALT = 2
    CTRL = 4
    SUPER = 8
    HYPER = 16
    META = 32
    CAPS_LOCK = 64
    NUM_LOCK = 128

    # The comment above says why. Lillecarl/pymux#359.
    __and__ = __rand__ = int.__and__
    __or__ = __ror__ = int.__or__
    __xor__ = __rxor__ = int.__xor__
    __invert__ = int.__invert__


class KeyboardFlag(IntFlag):
    """
    What a program asks the keyboard protocol for.

    A program pushes a set of these with "CSI > flags u", and
    `Screen.kitty_keyboard_flags` holds the set in force.
    """

    DISAMBIGUATE = 0b1
    REPORT_EVENT_TYPES = 0b10
    REPORT_ALTERNATE_KEYS = 0b100
    REPORT_ALL_KEYS = 0b1000
    REPORT_ASSOCIATED_TEXT = 0b10000

    # The comment above `Modifier` says why. Lillecarl/pymux#359.
    __and__ = __rand__ = int.__and__
    __or__ = __ror__ = int.__or__
    __xor__ = __rxor__ = int.__xor__
    __invert__ = int.__invert__


class EventType(IntEnum):
    "What a key did. The value is the one the protocol writes."

    PRESS = 1
    REPEAT = 2
    RELEASE = 3


class FlagsMode(IntEnum):
    'What "CSI = flags ; mode u" does with the flags it carries.'

    SET_EXACTLY = 1
    SET_THE_BITS = 2
    CLEAR_THE_BITS = 3


class KeyModifierResource(IntEnum):
    """
    The resources XTMODKEYS sets, as "CSI > Pp ; Pv m" numbers them.

    Each says how much modifier information a group of keys carries.
    Only `OTHER_KEYS` is acted on here; the rest are named so that a
    reader of a sequence knows what it asked for, and so that
    XTQMODKEYS can answer about a resource nobody has set.

    Five is missing on purpose. xterm keeps it for input through the
    `string` action. (`xterm-snapshots/ctlseqs.ms`, XTMODKEYS.)
    """

    KEYBOARD = 0
    CURSOR_KEYS = 1
    FUNCTION_KEYS = 2
    KEYPAD_KEYS = 3
    OTHER_KEYS = 4
    MODIFIER_KEYS = 6
    SPECIAL_KEYS = 7


class ModifyOtherKeys(IntEnum):
    """
    How much of the keyboard leaves the legacy encoding.

    This is XTMODKEYS resource 4, and the form a key leaves in is
    "CSI 27 ; mods ; code ~". xterm names the levels
    (`ctlseqs.ms`, under "Alt and Meta Keys"):

    - `OFF`: nothing leaves.
    - `ALT_AND_META`: shift and ctrl work as usual, and alt or meta
      make an ordinary key go out as if it were a function key.
      "alt-Tab sends CSI 27 ; 3 ; 9 ~".
    - `EVERY_MODIFIER`: all of the modifiers apply. "shift-Tab sends
      CSI 27 ; 2 ; 9 ~ rather than CSI Z".
    - `EVERY_KEY`: a key with no modifier at all goes out as well.
      "space sends CSI 27 ; 1 ; 32 ~".
    """

    OFF = 0
    ALT_AND_META = 1
    EVERY_MODIFIER = 2
    EVERY_KEY = 3


class FormatOtherKeys(IntEnum):
    """
    Which of its two forms the extended mode writes a key in.

    XTFMTKEYS resource 4, the mirror of the XTMODKEYS one. xterm says
    what the two are (`ctlseqs.ms`, under "Alt and Meta Keys"):

    > The formatOtherKeys resource tells xterm to change the format of
    > the escape sequences sent when modifyOtherKeys applies. When
    > modifyOtherKeys is set to 1, for example alt-Tab sends
    > CSI 9 ; 3 u (changing the order of parameters).

    So one feature with two spellings, and this picks the spelling.
    `TILDE` is what a terminal writes unless a program asks otherwise.

    xterm names the drawback of the other one itself: "applications may
    confuse it with CSI u (restore-cursor)". `Screen` tells those apart
    by the marker, which `tests/test_save_restore_cursor.py` holds.
    """

    TILDE = 0
    CSI_U = 1


class KeyCode(IntEnum):
    """
    The code of a key that writes one control character.

    The protocol numbers a key by the character it writes without any
    modifier, so these four carry their C0 code and not a number of
    their own.
    """

    TAB = 9
    ENTER = 13
    ESCAPE = 27
    BACKSPACE = 127


class FunctionalKey(IntEnum):
    """
    The number of a keypad key, in the Private Use Area.

    The protocol numbers every key that writes no character from
    `FIRST_FUNCTIONAL_KEY` up. Three groups are named here: the keypad,
    which has a normal key to fold onto, the modifier and lock keys,
    which only a pane that asked for every key reads, and the keys a
    `KeyProfile` may give a legacy form. The names
    are the ones kitty uses (`functional_key_number_to_name_map` in
    `kitty/key_encoding.py`).
    """

    CAPS_LOCK = 57358
    SCROLL_LOCK = 57359
    NUM_LOCK = 57360
    MENU = 57363
    F13 = 57376
    F24 = 57387

    KP_0 = 57399
    KP_1 = 57400
    KP_2 = 57401
    KP_3 = 57402
    KP_4 = 57403
    KP_5 = 57404
    KP_6 = 57405
    KP_7 = 57406
    KP_8 = 57407
    KP_9 = 57408
    KP_DECIMAL = 57409
    KP_DIVIDE = 57410
    KP_MULTIPLY = 57411
    KP_SUBTRACT = 57412
    KP_ADD = 57413
    KP_ENTER = 57414
    KP_EQUAL = 57415
    KP_SEPARATOR = 57416
    KP_LEFT = 57417
    KP_RIGHT = 57418
    KP_UP = 57419
    KP_DOWN = 57420
    KP_PAGE_UP = 57421
    KP_PAGE_DOWN = 57422
    KP_HOME = 57423
    KP_END = 57424
    KP_INSERT = 57425
    KP_DELETE = 57426
    KP_BEGIN = 57427
    LEFT_SHIFT = 57441
    LEFT_CONTROL = 57442
    LEFT_ALT = 57443
    LEFT_SUPER = 57444
    LEFT_HYPER = 57445
    LEFT_META = 57446
    RIGHT_SHIFT = 57447
    RIGHT_CONTROL = 57448
    RIGHT_ALT = 57449
    RIGHT_SUPER = 57450
    RIGHT_HYPER = 57451
    RIGHT_META = 57452
    ISO_LEVEL3_SHIFT = 57453
    ISO_LEVEL5_SHIFT = 57454


#: The keys a pane reads only once it asked for every key as an escape
#: code: kitty's `is_modifier_key` (`kitty/keys.c`). A program that
#: pushed DISAMBIGUATE to tell Escape from alt does not want an event
#: each time shift goes down. Lillecarl/pymux#688.
MODIFIER_KEYS = frozenset(
    (
        FunctionalKey.CAPS_LOCK,
        FunctionalKey.SCROLL_LOCK,
        FunctionalKey.NUM_LOCK,
        *range(FunctionalKey.LEFT_SHIFT, FunctionalKey.ISO_LEVEL5_SHIFT + 1),
    )
)


class TildeKey(IntEnum):
    'The number of a key in the "CSI number ~" form.'

    INSERT = 2
    DELETE = 3
    PAGE_UP = 5
    PAGE_DOWN = 6
    #: The function row, in the numbering rxvt uses. kitty sends only
    #: F3 this way, because "CSI R" is the cursor position report and a
    #: pane reading its own input cannot tell the two apart; it leaves
    #: F1, F2 and F4 their letters (`csi_number_for_name` and
    #: `tilde_trailers` in `kitty/key_encoding.py`).
    #:
    #: rxvt-unicode sends all four, so all four are read. They fold onto
    #: the letter form, so nothing here writes them back: what a pane
    #: gets is what kitty and every terminfo entry name.
    #: Lillecarl/pymux#242, Lillecarl/pymux#243.
    F1 = 11
    F2 = 12
    F3 = 13
    F4 = 14
    MENU = 29


class KeyProfile(NamedTuple):
    """
    What a pane in the legacy encoding reads where the terminals split.

    A pane in kitty sends what kitty sends, and a pane in WezTerm what
    WezTerm sends, so pymux sends what the terminal of the client that
    pressed the key would. Each field is one split the key panel found
    (`tests/test_keys_against_the_key_panel.py` holds the vote).

    **Only a legacy form is a choice.** Where a terminal answers a
    pane that asked for nothing with "CSI u" or "CSI 27 ; m ; k ~", the
    program prints it: kitty's "CSI 57376 u" for F13 is the symptom of
    Lillecarl/pymux#684. No profile copies those, so Ghostty's and kitty's
    profiles drop the key where the terminal itself writes junk.

    **Nor is a key that terminfo names.** A program reads its keys
    through the TERM of the pane, which is pyte's entry and not the
    terminal's: kitty's ctrl+F3 is "CSI 13 ; 5 ~" because xterm-kitty
    says so, and pyte's entry says "CSI 1 ; 5 R". Lillecarl/pymux#706.
    """

    #: super, hyper and meta written into a CSI form, "CSI 3 ; 9 ~". The
    #: legacy encoding has no field for them on a key that types text.
    writes_super: bool
    #: Menu is "CSI 29 ~", which kitty and xterm send. Without it Menu
    #: is a key the legacy encoding cannot write.
    menu: bool
    #: F13 to F24 take `_RXVT_FUNCTION_KEY`. Lillecarl/pymux#692.
    rxvt_function_keys: bool
    #: ctrl+shift on a key whose shifted key has no control code takes
    #: the code of the unshifted key: ctrl+shift+[ is ESC, not "{".
    #: Lillecarl/pymux#704.
    ctrl_on_the_unshifted_key: bool


#: The profile of each terminal on the key panel. Ghostty writes
#: ctrl+shift+[ as "CSI 123 ; 5 u", so it takes kitty's "{".
KEY_PROFILES = {
    "kitty": KeyProfile(writes_super=True, menu=True, rxvt_function_keys=False, ctrl_on_the_unshifted_key=False),
    "ghostty": KeyProfile(writes_super=True, menu=False, rxvt_function_keys=False, ctrl_on_the_unshifted_key=False),
    "wezterm": KeyProfile(writes_super=False, menu=False, rxvt_function_keys=True, ctrl_on_the_unshifted_key=True),
    "xterm": KeyProfile(writes_super=False, menu=True, rxvt_function_keys=False, ctrl_on_the_unshifted_key=True),
}


#: The profile of a terminal pymux cannot name.
DEFAULT_KEY_PROFILE = KEY_PROFILES["kitty"]


#: The first code point of the Private Use Area. A key numbered from
#: here up writes no character of its own.
FIRST_FUNCTIONAL_KEY = 0xE000


#: The bytes that introduce a control sequence.
CSI = "\x1b["


class KeyEvent(NamedTuple):
    "One decoded key event, in the terms of the keyboard protocol."

    code: int  # unicode key code, or the number of the CSI form
    mods: int  # shift/alt/ctrl bitmask (without the +1 offset)
    final: str  # "u", "~" or one of _SS3_FINALS
    text: str = ""  # reported text, if the terminal sent it
    #: The other codes of the key: the shifted key, then the key of the
    #: base layout. Only a terminal that speaks the protocol sends
    #: them, and it leaves a slot empty when it has nothing for it, so
    #: a slot holds None. Nothing reconstructs these from legacy data:
    #: which key gives a character depends on the layout of the user.
    alternates: tuple[int | None, ...] = ()
    #: Press, repeat or release. Legacy data holds presses only.
    event: int = EventType.PRESS


#: The bytes that introduce a single shift three. The application
#: keypad and the application cursor keys both write one.
SS3 = "\x1bO"
