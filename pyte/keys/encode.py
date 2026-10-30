"""
`KeyEvent`s into bytes, in the form the pane asked for. The forms follow
the encoder of kitty (`kitty/key_encoding.c`), and a `KeyProfile` picks
the answer where the terminals split on a legacy form.
"""

from __future__ import annotations

from .events import (
    CSI,
    DEFAULT_KEY_PROFILE,
    FIRST_FUNCTIONAL_KEY,
    MODIFIER_KEYS,
    SS3,
    EventType,
    FormatOtherKeys,
    FunctionalKey,
    KeyboardFlag,
    KeyCode,
    KeyEvent,
    KeyProfile,
    Modifier,
    ModifyOtherKeys,
    TildeKey,
)
from .legacy import (
    BACK_TAB,
    CONTROL_CODE_OF,
    CTRL_TAKES_OFF_A_LETTER,
    KEYPAD_TO_NORMAL,
    LOCK_MODIFIERS,
    MODIFIERS_NO_LEGACY_FORM_TAKES,
    MODIFIERS_THAT_MAKE_A_KEY_AMBIGUOUS,
    MODIFIERS_THE_LEGACY_ENCODING_DROPS,
    MODIFY_OTHER_KEYS_PROFILE,
    a_legacy_form_carries,
    ctrl_stays_on_the_unshifted_key,
    folded,
    has_a_control_code,
    legacy_mode,
    shifted_key_of,
)
from .parse import parse_key_data
from .unhearable import Unhearable, the_modifiers_a_pane_cannot_read

__all__ = ["translate_key_data", "translate_key_event"]


def _has_a_shifted_character(code: int, text: str) -> bool:
    """
    Whether shift on this key gives a character of its own.

    Shift on a letter gives the capital, and a terminal sends that
    character rather than saying "shift and a letter". Shift on Tab
    gives nothing, which is why shift+Tab is the example xterm uses
    for the level where all the modifiers apply. Space is the same: it
    writes itself with shift held, so shift+space is "CSI 27 ; 2 ; 32 ~",
    as Ghostty and WezTerm send it. Lillecarl/pymux#699.
    """
    if text:
        return text != chr(code)
    character = chr(code)
    return character.isprintable() and character.upper() != character


def _typed_code(code: int, mods: int, text: str, alternates: tuple[int | None, ...], caps_lock: bool) -> int:
    """
    The character the key types, which is what xterm writes in the
    escape form: its keysym, after shift and caps lock. alt+shift+minus
    is "CSI 27 ; 4 ; 95 ~", the underscore. Lillecarl/pymux#702.
    """
    if len(text) == 1:
        return ord(text)
    typed = code
    if mods & Modifier.SHIFT and alternates and alternates[0] is not None:
        typed = alternates[0]
    if caps_lock and chr(typed).isalpha():
        typed = ord(chr(typed).swapcase())
    return typed


def _wants_the_escape_form(level: int, code: int, typed: int, mods: int, text: str) -> bool:
    """
    Whether this key goes out as "CSI 27 ; mods ; code ~".

    The rule per level is xterm's, in its own words. At
    `ALT_AND_META`, "the usual shift- and control-modifiers work as
    expected, but other modifiers cause ordinary keys to be encoded as
    if they were function-keys".

    At `EVERY_MODIFIER` all of them apply. Shift alone counts on a key
    with no shifted character, which is the shift+Tab that xterm gives
    as its example, and on every key that types a character from 0x40
    to 0x7F: xterm's `IsControlInput` (`input.c`). So shift+a is
    "CSI 27 ; 2 ; 65 ~", which vim, the program that asks for this
    level, reads as "A"; shift+1 is "!".
    """
    if level >= ModifyOtherKeys.EVERY_KEY:
        return True
    if level == ModifyOtherKeys.EVERY_MODIFIER:
        if mods & (Modifier.CTRL | Modifier.ALT):
            return True
        if not mods & Modifier.SHIFT:
            return False
        if code == KeyCode.TAB:
            # The back tab, "CSI Z", which is what xterm sends, and not
            # the "CSI 27 ; 2 ; 9 ~" of its own manual. Lillecarl/pymux#693.
            return False
        # A key with no text, which is what super leaves, still has a
        # shifted one when the terminal named it: super+shift+1 is "!".
        return 0x40 <= typed <= 0x7F or not (typed != code or _has_a_shifted_character(code, text))
    if level == ModifyOtherKeys.ALT_AND_META:
        return bool(mods & Modifier.ALT) or _ctrl_or_shift_has_no_legacy_form(code, typed, mods)
    return False


def _ctrl_or_shift_has_no_legacy_form(code: int, typed: int, mods: int) -> bool:
    """
    Whether ctrl or shift on this key has nothing to say in the legacy
    encoding, which is when level 1 writes the escape form.

    xterm's rule (`ModifyOtherKeys`, case `mokUser`, and
    `allowedCharModifiers`, `input.c`): Enter and Tab take the escape
    form with either, but shift+Tab is the back tab. Escape and Backspace
    never do: a control alias loses ctrl and shift before the test.
    Elsewhere ctrl takes it on a key with
    no control code, so ctrl+1 is "CSI 27 ; 5 ; 49 ~" and ctrl+a is still
    0x01, and shift alone never does: the character carries it.
    Lillecarl/pymux#701.
    """
    ctrl_or_shift = mods & (Modifier.CTRL | Modifier.SHIFT)
    if code == KeyCode.ENTER:
        return bool(ctrl_or_shift)
    if code == KeyCode.TAB:
        # Shift makes it the back tab, ctrl or not: xterm sends "CSI Z"
        # for ctrl+shift+Tab here. Lillecarl/pymux#693.
        return ctrl_or_shift == Modifier.CTRL
    if code in (KeyCode.ESCAPE, KeyCode.BACKSPACE):
        return False
    if not mods & Modifier.CTRL:
        return False
    # Nor where the key under the shifted one has a control code:
    # ctrl+shift+[ is ESC in xterm, as ctrl+[ is. Lillecarl/pymux#704.
    # Where shift made another key, xterm's own test decides, which is
    # `IsControlInput`, 0x40 to 0x7F: ctrl+shift+/ still takes the
    # escape form, because "?" is below it.
    if typed != code:
        return not any(0x40 <= key <= 0x7F and has_a_control_code(key) for key in (typed, code))
    return not has_a_control_code(ord(chr(typed).lower()) if chr(typed).isalpha() else typed)


def _serialize(
    code: int,
    mods_value: int,
    final: str,
    alternates: tuple[int | None, ...] = (),
    event: int = EventType.PRESS,
    text: str = "",
) -> str:
    """
    Write one key event in the escape code form of the protocol.

    The form is "CSI code:shifted:base ; mods:event ; text final". A
    field that holds its default stays empty, and a field at the end
    that holds its default is left out. A non-press event must write
    modifier 1, even when no modifier is active.

    **The number of a "~" key always goes out.** In every other form
    the number is 1 when there is nothing to say, so "CSI H" and
    "CSI 1 H" are one key. In the "~" form the number *is* the key: 1
    is Home, 2 is Insert, 3 is Delete, and "CSI ~" names none of them.
    kitty never meets this, because it pairs no "~" with the number 1
    (`serialize` in `kitty/key_encoding.c`, and Home is `S(1, 'H')`
    there). A pane does, because it reads what the terminal of the
    person sends, and xterm sends "CSI 1 ~" for Home.
    Lillecarl/pymux#152.
    """
    second = mods_value != 1 or event != EventType.PRESS
    third = bool(text)

    out = "\x1b["
    if code != 1 or final == "~" or alternates or second or third:
        out += str(code)
    if alternates:
        out += ":" + ":".join("" if slot is None else str(slot) for slot in alternates)
    if second or third:
        out += ";"
        if mods_value != 1 or event != EventType.PRESS:
            out += str(mods_value)
        if event != EventType.PRESS:
            out += ":%d" % event
    if third:
        out += ";" + ":".join(str(ord(char)) for char in text)
    return out + final


#: Keys that the legacy encoding writes as one control character. A
#: release of one of them has no legacy form, and kitty reports it only
#: when the pane asks for all keys as escape codes.
_CONTROL_CODES = (KeyCode.ENTER, KeyCode.TAB, KeyCode.BACKSPACE)


#: The keys kitty encodes as functional keys and not as text.
_CONTROL_KEYS = (*_CONTROL_CODES, KeyCode.ESCAPE)


#: What each keypad key sends once a pane turns the application keypad
#: on: the final byte of an SS3 sequence.
#:
#: The table is xterm's, read out of `kypd_num` and `kypd_apl` in its
#: `input.c`. Both are indexed by the keysym less `XK_KP_Space`, so
#: the pair says what one key sends in each of the two modes:
#: "*+,-./0123456789" and "=" against "jklmnopqrstuvwxy" and "X".
#:
#: Tab and Enter are in the same pair, at "I" and "M".
#:
#: **A legacy keyboard cannot reach this.** Such a terminal folds the
#: keypad onto the main keyboard before it sends anything, so nothing
#: downstream can tell a keypad 0 from the 0 above the letters. It
#: works because pymux asks every terminal to disambiguate, and a
#: terminal that does stops folding. Lillecarl/pymux#175.
_KEYPAD_APPLICATION = {
    **{FunctionalKey.KP_0 + n: chr(ord("p") + n) for n in range(10)},
    FunctionalKey.KP_MULTIPLY: "j",
    FunctionalKey.KP_ADD: "k",
    FunctionalKey.KP_SEPARATOR: "l",
    FunctionalKey.KP_SUBTRACT: "m",
    FunctionalKey.KP_DECIMAL: "n",
    FunctionalKey.KP_DIVIDE: "o",
    FunctionalKey.KP_EQUAL: "X",
    FunctionalKey.KP_ENTER: "M",
}


#: The character each keypad key types, xterm's `kypd_num`: the digit,
#: the operator, CR for Enter, and a comma for the separator.
_KEYPAD_CHARACTER = {
    **{key: chr(code) for key, (code, final) in KEYPAD_TO_NORMAL.items() if final == "u"},
    FunctionalKey.KP_SEPARATOR: ",",
}


def _xterm_keypad_form(
    event: KeyEvent, flags: int, application_keypad: bool, num_lock: bool, modify_other_keys: int, bare: bool = False
) -> str | None:
    """
    What a keypad key sends in the modes that are xterm's own, DECKPAM
    and modifyOtherKeys, or None to fold it as the legacy encoding does.

    xterm's `Input()` (`input.c`) takes a keypad key before it looks at
    modifyOtherKeys, so that never reaches one. With DECKPAM on and num
    lock off, the key is its SS3 form, with the modifiers in it: shift on
    keypad plus is "SS3 2 k". Num lock turns DECKPAM off for a key that
    types a character (`real_NumLock`), and then, as at any level of
    modifyOtherKeys, the key is that character and nothing else.
    Lillecarl/pymux#700.

    Only a pane in the legacy mode: one that pushed a kitty flag reads
    the number of the key.
    """
    if not legacy_mode(flags) or event.final != "u" or event.event == EventType.RELEASE:
        return None
    final = _KEYPAD_APPLICATION.get(event.code)
    if final is None:
        return None
    if application_keypad and not num_lock:
        mods = event.mods & (Modifier.SHIFT | Modifier.ALT | Modifier.CTRL)
        return SS3 + ("%d" % (mods + 1) if mods or bare else "") + final
    if application_keypad or modify_other_keys:
        return _KEYPAD_CHARACTER[event.code]
    return None


def _sends_its_text(flags: int, mods: int, text: str, kind: int) -> bool:
    """
    Whether a key goes out as the text it writes, and nothing else.

    kitty's rule (`send_text_standalone` in `encode_glfw_key_event`,
    `kitty/key_encoding.c`): a key that writes text sends that text
    unless the pane asked for every key as an escape code, whatever
    else it asked for. So a repeat, a shifted key with its alternates,
    and a keypad digit with num lock reach a pane that disambiguates as
    "a", "A" and "0". Lillecarl/pymux#690.

    kitty has no text for a key with ctrl or alt held, so it never
    meets that case. A terminal that sends some keeps the escape code.

    The caller asks for any pane that pushed a flag: the rule does not
    look at DISAMBIGUATE, and Ghostty and WezTerm keep it too, so a
    repeated "a" is "a" to a pane that pushed only the event types.
    Lillecarl/pymux#695.
    """
    if flags & KeyboardFlag.REPORT_ALL_KEYS or kind == EventType.RELEASE:
        return False
    if not text or ord(text[0]) < 0x20 or text[0] == "\x7f":
        return False
    return not mods & MODIFIERS_THAT_MAKE_A_KEY_AMBIGUOUS


def _encode_event(
    event: KeyEvent,
    flags: int,
    application_mode: bool,
    modify_other_keys: int = ModifyOtherKeys.OFF,
    application_keypad: bool = False,
    format_other_keys: int = FormatOtherKeys.TILDE,
    backarrow_sends_backspace: bool = False,
    profile: KeyProfile = DEFAULT_KEY_PROFILE,
) -> str:
    "Encode a key event for a pane with the given protocol flags."
    if modify_other_keys:
        profile = MODIFY_OTHER_KEYS_PROFILE
    # The legacy forms write no lock, but caps lock still picks the
    # character a letter types, which the extended mode writes.
    caps_lock = bool(event.mods & Modifier.CAPS_LOCK)
    num_lock = bool(event.mods & Modifier.NUM_LOCK)
    # At level 3 xterm writes the modifier field for a key held with only
    # a lock or super, which it counts and does not name: caps lock on
    # Delete is "CSI 3 ; 1 ~", and on keypad + under DECKPAM "SS3 1 k".
    # Lillecarl/pymux#700.
    bare = (
        modify_other_keys == ModifyOtherKeys.EVERY_KEY
        and not flags
        and bool(event.mods & MODIFIERS_NO_LEGACY_FORM_TAKES)
        and not event.mods & (Modifier.SHIFT | Modifier.ALT | Modifier.CTRL)
    )
    if not flags and event.mods & LOCK_MODIFIERS:
        event = event._replace(mods=event.mods & ~LOCK_MODIFIERS)
    if not flags and not profile.writes_super and event.mods & MODIFIERS_THE_LEGACY_ENCODING_DROPS:
        event = event._replace(mods=event.mods & ~MODIFIERS_THE_LEGACY_ENCODING_DROPS)
    if application_keypad or modify_other_keys:
        keypad = _xterm_keypad_form(event, flags, application_keypad, num_lock, modify_other_keys, bare)
        if keypad is not None:
            return keypad
    plain = folded(event, flags, profile)
    if plain is None:
        return ""
    if plain.final == "u" and plain.code in MODIFIER_KEYS and not flags & KeyboardFlag.REPORT_ALL_KEYS:
        return ""
    code, mods, final, text, alternates, kind = plain
    mods_value = mods + 1

    # Only a pane that asked for the event types can read a release. A
    # repeat without that flag is a press: that is what the key did.
    if kind == EventType.RELEASE and not flags & KeyboardFlag.REPORT_EVENT_TYPES:
        return ""
    if not flags & KeyboardFlag.REPORT_EVENT_TYPES:
        kind = EventType.PRESS
    # A lock is no modifier here: kitty asks `!(mods & ~LOCK_MASK)`
    # in `encode_function_key`, so caps lock does not make the release
    # of Enter reach a pane that pushed only the event types.
    if kind == EventType.RELEASE and not mods & ~LOCK_MODIFIERS and code in _CONTROL_CODES:
        if not flags & KeyboardFlag.REPORT_ALL_KEYS:
            return ""
    # The repeat of a plain Enter, Tab or Backspace is its byte, as the
    # press is: kitty writes both before it looks at the event type.
    # Lillecarl/pymux#690.
    if (
        kind == EventType.REPEAT
        and final == "u"
        and code in _CONTROL_CODES
        and not mods & ~LOCK_MODIFIERS
        and not flags & KeyboardFlag.REPORT_ALL_KEYS
    ):
        kind = EventType.PRESS
    shifted = shifted_key_of(plain)
    if not flags & KeyboardFlag.REPORT_ALTERNATE_KEYS or final != "u":
        # kitty sends the other codes of a key for the "u" form only.
        alternates = ()
    embedded = text if flags & KeyboardFlag.REPORT_ASSOCIATED_TEXT else ""

    if flags and _sends_its_text(flags, mods, text, kind):
        return text

    if final == "u":
        if flags and code not in _CONTROL_KEYS and not a_legacy_form_carries(code, mods, shifted):
            # A pane that pushed any flag reads the locks as modifiers, so
            # num lock and alt on keypad 1 is "CSI 57400 ; 131 u" in kitty,
            # Ghostty and WezTerm alike. Lillecarl/pymux#695.
            return _serialize(event.code, mods_value, "u", alternates, kind, embedded)
        ambiguous = (
            bool(mods & MODIFIERS_THAT_MAKE_A_KEY_AMBIGUOUS)
            or code == KeyCode.ESCAPE
            # Enter, Tab and Backspace write no text, so shift has no
            # character to hide in: kitty writes shift+Enter as "CSI 13 ;
            # 2 u" once a pane disambiguates (`encode_function_key`).
            # Lillecarl/pymux#689.
            or (code in _CONTROL_CODES and bool(mods & ~LOCK_MODIFIERS))
        )
        # Outside the legacy mode a modified Enter, Tab, Backspace or
        # Escape has no legacy form either: kitty's `encode_function_key`
        # takes `legacy_functional_key_encoding_with_modifiers` only in
        # it, so shift+Enter to a pane that pushed the event types alone
        # is "CSI 13 ; 2 u". Lillecarl/pymux#695.
        modified_control_key = not legacy_mode(flags) and code in _CONTROL_KEYS and bool(mods & ~LOCK_MODIFIERS)
        # A functional key still here belongs to a pane that reads the
        # number of a key: `folded` took it away from every other one.
        # It goes out as an escape code whatever else is asked for,
        # because `chr` of it is a character no keyboard has.
        no_legacy_form = code >= FIRST_FUNCTIONAL_KEY
        # Back tab is the one key with a modifier that the legacy
        # encoding writes, and it belongs to the legacy mode alone. A
        # pane that asked for more reads the number of the key, the
        # way it does for every other modified key.
        back_tab = code == KeyCode.TAB and bool(mods & Modifier.SHIFT)
        if (
            flags & KeyboardFlag.REPORT_ALL_KEYS
            or (flags & KeyboardFlag.DISAMBIGUATE and ambiguous)
            or modified_control_key
            or no_legacy_form
            or (back_tab and not legacy_mode(flags))
            or kind != EventType.PRESS
            or alternates
            or embedded
        ):
            return _serialize(code, mods_value, "u", alternates, kind, embedded)

        # The extended mode, which a pane asks for with XTMODKEYS and
        # not with the flag stack. A pane in one of the kitty modes
        # never gets here, because every branch above answers first.
        # Lillecarl/pymux#169.
        escape_code = code
        if code == KeyCode.BACKSPACE and modify_other_keys >= ModifyOtherKeys.EVERY_MODIFIER:
            # xterm's back-arrow toggle (`IsBackarrowToggle`, `input.c`):
            # ctrl flips which of BS and DEL the key writes, and is no
            # modifier to the level-2 test. So ctrl+Backspace stays BS, and
            # ctrl+shift+Backspace is "CSI 27 ; 6 ; 8 ~". Lillecarl/pymux#703.
            ctrl = bool(mods & Modifier.CTRL)
            escape_code = 0x7F if (not backarrow_sends_backspace) != ctrl else 0x08
            wants_it = modify_other_keys == ModifyOtherKeys.EVERY_KEY or bool(mods & ~(Modifier.CTRL | LOCK_MODIFIERS))
        else:
            escape_code = _typed_code(code, mods, text, plain.alternates, caps_lock)
            wants_it = _wants_the_escape_form(modify_other_keys, code, escape_code, mods, text)
        if wants_it:
            if format_other_keys == FormatOtherKeys.CSI_U:
                return "%s%d;%du" % (CSI, escape_code, mods_value)
            return "%s27;%d;%d~" % (CSI, mods_value, escape_code)

        # Legacy form.
        if back_tab:
            # The one key whose alt form takes a second escape,
            # because "CSI Z" already begins with one. kitty writes it
            # the same way, in
            # `legacy_functional_key_encoding_with_modifiers`. Ctrl
            # has no legacy form here and is lost, as it is there.
            # Lillecarl/pymux#174.
            prefix = "\x1b\x1b" if mods & Modifier.ALT else "\x1b"
            return prefix + BACK_TAB
        if code == KeyCode.BACKSPACE and backarrow_sends_backspace:
            # DECBKM: "Backarrow key sends backspace". Without it the
            # key sends a delete, which is what a fresh pty reports as
            # the erase character. Lillecarl/pymux#184.
            prefix = "\x1b" if mods & Modifier.ALT else ""
            return prefix + ("\x7f" if mods & Modifier.CTRL else "\x08")
        if text and not mods & (Modifier.CTRL | Modifier.ALT):
            # The reported text accounts for shift and the layout.
            return text
        if mods & (Modifier.CTRL | Modifier.ALT) and shifted is not None:
            # The shifted key is the key, and shift is spent on it:
            # alt+shift+1 is "ESC !", and ctrl+shift+minus is ctrl on an
            # underscore. kitty's `encode_printable_ascii_key_legacy`.
            # Lillecarl/pymux#691.
            if not ctrl_stays_on_the_unshifted_key(code, shifted, mods, profile):
                code = shifted
            mods &= ~Modifier.SHIFT
        if mods & (Modifier.CTRL | Modifier.ALT):
            result = "\x1b" if mods & Modifier.ALT else ""
            if mods & Modifier.CTRL:
                if code == KeyCode.ENTER:
                    # A CR, as kitty, xterm and WezTerm send. Ghostty's
                    # "CSI 27 ; 5 ; 13 ~" prints junk in a shell, and an LF
                    # is no terminal's. Lillecarl/pymux#694.
                    result += "\r"
                elif code == KeyCode.TAB:
                    result += "\t"
                elif code == KeyCode.BACKSPACE:
                    result += "\x08"
                elif ord("a") <= code <= ord("z"):
                    result += chr(code - CTRL_TAKES_OFF_A_LETTER)
                elif code in CONTROL_CODE_OF:
                    result += chr(CONTROL_CODE_OF[code])
                elif code == KeyCode.ESCAPE:
                    result += "\x1b"
                else:
                    result += chr(code)
            else:
                char = chr(code)
                if mods & Modifier.SHIFT and char.isalpha():
                    char = char.upper()
                result += char
            return result
        # A key with no text of its own, which is what super leaves: shift
        # takes the shifted key and caps lock turns a letter over, as
        # xterm and Ghostty write super+shift+[ as "{" and super+a under
        # caps lock as "A". Lillecarl/pymux#693.
        char = chr(shifted) if mods & Modifier.SHIFT and shifted is not None else chr(code)
        if mods & Modifier.SHIFT and shifted is None and char.isalpha():
            char = char.upper()
        if caps_lock and char.isalpha():
            char = char.swapcase()
        return char

    if final == "R" and (not legacy_mode(flags) or (flags and mods)):
        # A pane that speaks the protocol reads F3 as a number, because
        # kitty's own decoder refuses the letter: "CSI R" and "CSI 1;5R"
        # both raise there, and "CSI 13~" and "CSI 13;5~" come back as
        # F3. Lillecarl/pymux#242. Any flag is enough for a modified
        # one: kitty, Ghostty and WezTerm send "CSI 13 ; 2 ~" to a pane
        # that pushed only the other keys. Lillecarl/pymux#695.
        code, final = TildeKey.F3, "~"

    if bare and mods == 0:
        return "%s%d;1%s" % (CSI, code, final)

    if final == "~":
        return _serialize(code, mods_value, "~", (), kind, embedded)

    # Functional keys with a letter final byte.
    if mods == 0 and kind == EventType.PRESS and not embedded:
        # The SS3 form belongs to a pane that pushed no flag at all.
        if legacy_mode(flags):
            # DECCKM moves Home, End and keypad Begin with the arrows:
            # kitty's `encode_function_key` lists all seven, and xterm
            # does the same. Lillecarl/pymux#687.
            if application_mode and final in "ABCDEFH":
                return "\x1bO" + final
            if final in "PQRS":
                return "\x1bO" + final
        return "\x1b[" + final
    return _serialize(code, mods_value, final, (), kind, embedded)


def translate_key_data(
    data: str,
    flags: int,
    application_mode: bool = False,
    source_flags: int = 0,
    synthesize: bool = True,
    modify_other_keys: int = ModifyOtherKeys.OFF,
    application_keypad: bool = False,
    format_other_keys: int = FormatOtherKeys.TILDE,
    backarrow_sends_backspace: bool = False,
    report=None,
    profile: KeyProfile = DEFAULT_KEY_PROFILE,
) -> str:
    """
    Translate raw key data into the encoding for a pane with the given
    keyboard protocol flags.

    `report` is called as `report(event, lost, encoded)` for each key
    this pane reads as something else or not at all, and never for one
    that arrives whole. **A key really pressed still degrades**, which
    is what a keyboard does; this is the only way anything finds out.
    Nothing is worked out when nobody is asking.

    `application_keypad` is DECKPAM, the other half of what terminfo's
    `smkx` turns on. With it a keypad key sends an SS3 form instead of
    a digit, so a program can tell the keypad from the row of numbers
    above the letters.

    `modify_other_keys` is the other way a pane asks for more than the
    legacy encoding: XTMODKEYS resource 4, which xterm has and the
    flag stack does not replace. A pane that pushed any kitty flag
    never reaches it, because those answer first.

    `source_flags` says what the terminal that sends the keys reports,
    in the same flags. A terminal that reports the event types sends a
    release of its own, and the release passes through.

    `synthesize` says what to do when that terminal reports no event
    type and the pane asked for one. With it, a key answers with a
    press and a release at once: the pane then reads every key it went
    down and came up, and only the time between the two is lost. That
    is what a pane asked for, and no terminal can do better than the
    keyboard it has. Without it, the pane hears that it has no event
    types (see `Screen.deliverable_kitty_keyboard_flags`) and
    reads presses only.

    `profile` says which terminal a legacy pane gets the answer of,
    where the terminals split: `KeyProfile`.
    """
    # The release of a key that the terminal never reports coming up.
    double = bool(
        synthesize and flags & KeyboardFlag.REPORT_EVENT_TYPES and not source_flags & KeyboardFlag.REPORT_EVENT_TYPES
    )

    parts = []
    for item in parse_key_data(data):
        if not isinstance(item, KeyEvent):
            parts.append(item)
            continue
        encoded = translate_key_event(
            item,
            flags,
            application_mode,
            double,
            modify_other_keys,
            application_keypad,
            format_other_keys,
            backarrow_sends_backspace,
            profile=profile,
        )
        if report is not None and item.event == EventType.PRESS:
            # Not a release. A pane that did not ask for the event types
            # is meant not to read one, and every press sends one, so
            # reporting those would be a line per keystroke.
            lost = the_modifiers_a_pane_cannot_read(item, flags, profile, modify_other_keys)
            if lost or not encoded:
                report(item, lost, encoded)
        parts.append(encoded)
    return "".join(parts)


def translate_key_event(
    event: KeyEvent,
    flags: int,
    application_mode: bool = False,
    double: bool = False,
    modify_other_keys: int = ModifyOtherKeys.OFF,
    application_keypad: bool = False,
    format_other_keys: int = FormatOtherKeys.TILDE,
    backarrow_sends_backspace: bool = False,
    exactly: bool = False,
    profile: KeyProfile = DEFAULT_KEY_PROFILE,
) -> str:
    """
    The bytes one key event sends to a pane with these protocol flags.

    `translate_key_data` for a caller holding the event and no bytes.
    Going through the legacy form so that it can be parsed back loses
    whatever that form cannot carry.

    `double` belongs here and not to the caller, or a key sent by name
    would stop sending the release a pane asked for.

    **What this cannot write, it writes without**: super+a reaches a
    legacy pane as "a", which is what a keyboard delivers there. A
    caller that may not lose any of it asks with `exactly`.
    """
    if exactly:
        lost = the_modifiers_a_pane_cannot_read(event, flags, profile, modify_other_keys)
        encoded = translate_key_event(
            event,
            flags,
            application_mode,
            double,
            modify_other_keys,
            application_keypad,
            format_other_keys,
            backarrow_sends_backspace,
            profile=profile,
        )
        if lost or not encoded:
            raise Unhearable(event, lost, encoded)
        return encoded

    encoded = _encode_event(
        event,
        flags,
        application_mode,
        modify_other_keys,
        application_keypad,
        format_other_keys,
        backarrow_sends_backspace,
        profile,
    )
    if double and event.event == EventType.PRESS:
        encoded += _encode_event(event._replace(event=EventType.RELEASE), flags, application_mode, profile=profile)
    return encoded
