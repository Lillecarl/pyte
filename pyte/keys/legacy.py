"""
What the legacy encoding can carry: the control codes, the modifiers it
drops, the keypad forms, and `folded`, which turns an event into the one
a legacy pane reads. The reader, the writer and the check of what a pane
cannot hear all start from these facts.
"""

from __future__ import annotations

from .events import (
    DEFAULT_KEY_PROFILE,
    FIRST_FUNCTIONAL_KEY,
    KEY_PROFILES,
    FunctionalKey,
    KeyboardFlag,
    KeyCode,
    KeyEvent,
    KeyProfile,
    Modifier,
    TildeKey,
)

__all__ = [
    "BACK_TAB",
    "CONTROL_CODE_OF",
    "CTRL_TAKES_OFF_A_LETTER",
    "CTRL_TAKES_OFF_A_SYMBOL",
    "KEYPAD_TO_NORMAL",
    "LETTER_FORM_CODE",
    "LOCK_MODIFIERS",
    "MODIFIERS_NO_LEGACY_FORM_TAKES",
    "MODIFIERS_THAT_MAKE_A_KEY_AMBIGUOUS",
    "MODIFIERS_THE_LEGACY_ENCODING_DROPS",
    "MODIFY_OTHER_KEYS_PROFILE",
    "a_legacy_form_carries",
    "carries_the_number",
    "ctrl_stays_on_the_unshifted_key",
    "folded",
    "has_a_control_code",
    "legacy_mode",
    "shifted_key_of",
]


#: What ctrl takes off a letter to make its control code: "a" is 97 and
#: ctrl+a is 1.
CTRL_TAKES_OFF_A_LETTER = ord("a") - 1


#: The same for the four symbols that have a control code. "\\" is 92
#: and ctrl+backslash is 28.
CTRL_TAKES_OFF_A_SYMBOL = ord("\\") - 28


#: The control code that ctrl gives a key that is not a letter.
#:
#: The VT220 put NUL, ESC to US and DEL on the row of digits as well,
#: and xterm and kitty keep it: kitty's `ctrled_key`
#: (`kitty/key_encoding.c`) is this table. A key that is not here has
#: no control code, so ctrl on it is lost. Lillecarl/pymux#686.
CONTROL_CODE_OF = {
    ord(" "): 0,
    ord("2"): 0,
    ord("@"): 0,
    ord("3"): 27,
    ord("["): 27,
    ord("4"): 28,
    ord("\\"): 28,
    ord("5"): 29,
    ord("]"): 29,
    ord("6"): 30,
    ord("^"): 30,
    ord("~"): 30,
    ord("7"): 31,
    ord("/"): 31,
    ord("_"): 31,
    ord("8"): 127,
    ord("?"): 127,
}


#: What shift and Tab send in the legacy encoding, after the escape.
#: CBT by its other name.
BACK_TAB = "[Z"


#: The modifiers a key cannot carry in the legacy encoding, so that a
#: key which has one has to leave it.
#:
#: kitty names the combinations that go out as escape codes when a pane
#: asks to disambiguate: "the Esc, alt+key, ctrl+key, ctrl+alt+key,
#: shift+alt+key keys". Its rule under that is the general one, and it
#: is the one to read: "all key events that do not generate text".
#:
#: Shift is not here, because shift on a letter is the capital and
#: that is text. Nor are the two locks, for the same reason, which
#: kitty says in the same place: "the Lock modifiers are not reported
#: for text producing keys, to keep them usable in legacy programs".
#: **Ambiguous is not the same as absent**, which the old name of this
#: said and cost a wrong rule. ctrl is a control code and alt is an
#: escape in front of the key, so the legacy encoding writes both. What
#: it cannot do is tell them apart from something else: ctrl+a is
#: ctrl+shift+a, and alt+a is an escape and an a.
MODIFIERS_THAT_MAKE_A_KEY_AMBIGUOUS = Modifier.CTRL | Modifier.ALT | Modifier.SUPER | Modifier.HYPER | Modifier.META


#: The modifiers the legacy encoding has no way to write at all.
#:
#: These three reach a pane only in a form that carries the number of a
#: key. Anywhere else they are dropped and the key arrives without
#: them, which is what a keyboard does as well.
MODIFIERS_THE_LEGACY_ENCODING_DROPS = Modifier.SUPER | Modifier.HYPER | Modifier.META


#: The two locks, which a pane that pushed no flag at all never reads.
#:
#: They are a state of the keyboard and not a key held down, and the
#: legacy encoding has no field for them: xterm writes no lock into
#: "CSI 1 ; mods D", and kitty takes both off before it encodes, "if
#: (!key_encoding_flags) mods &= ~GLFW_LOCK_MASK" (`convert_glfw_mods`,
#: `kitty/key_encoding.c`). A pane that pushed any flag reads them,
#: as it does from kitty. A keyboard that reports them sets one of
#: them on every key while it is on, and Hyprland turns num lock on
#: at login for a keyboard that has no key for it: every arrow then
#: reached bash as "CSI 1 ; 129 D". Lillecarl/pymux#684.
LOCK_MODIFIERS = Modifier.CAPS_LOCK | Modifier.NUM_LOCK


def legacy_mode(flags: int) -> bool:
    """
    Whether the pane is in what kitty calls the legacy mode.

    kitty reads it off three flags
    (`legacy_mode` in `encode_function_key`, `kitty/key_encoding.c`),
    and the forms that belong to it are the SS3 spelling of an arrow
    or of F1 to F4, and the back tab.
    """
    return not flags & (KeyboardFlag.DISAMBIGUATE | KeyboardFlag.REPORT_EVENT_TYPES | KeyboardFlag.REPORT_ALL_KEYS)


#: F13 to F24 in the "CSI number ~" form, the numbers rxvt gives them.
#: WezTerm sends these to a legacy pane, and nobody else does.
_RXVT_FUNCTION_KEY = dict(
    zip(
        range(FunctionalKey.F13, FunctionalKey.F24 + 1),
        (25, 26, 28, 29, 31, 32, 33, 34, 42, 43, 44, 45),
        strict=True,
    )
)


#: modifyOtherKeys is xterm's own mode, so xterm answers under it.
MODIFY_OTHER_KEYS_PROFILE = KEY_PROFILES["xterm"]


#: The number a key of the letter form carries. It is always one: the
#: letter names the key, so the number has nothing to say.
LETTER_FORM_CODE = 1


#: What kitty's legacy form of a text key cannot carry once a pane
#: pushed a flag and the locks count.
MODIFIERS_NO_LEGACY_FORM_TAKES = LOCK_MODIFIERS | MODIFIERS_THE_LEGACY_ENCODING_DROPS


#: The normal key of each keypad key, as `(code, final)`.
#:
#: A terminal folds the keypad onto the main keyboard while it speaks
#: the legacy encoding, and stops folding it as soon as anything asks
#: it to disambiguate. kitty does it in `convert_kp_key_to_normal_key`,
#: under `if (!ev.disambiguate && !ev.report_text ...)`
#: (`kitty/key_encoding.c`). So a pane that asked for nothing reads a
#: keypad key only if this end folds it back.
#:
#: `KP_SEPARATOR` and `KP_BEGIN` are not here, for the same reason they
#: are not in kitty's function: neither has a normal key.
KEYPAD_TO_NORMAL = {
    **{FunctionalKey.KP_0 + n: (ord("0") + n, "u") for n in range(10)},
    FunctionalKey.KP_DECIMAL: (ord("."), "u"),
    FunctionalKey.KP_DIVIDE: (ord("/"), "u"),
    FunctionalKey.KP_MULTIPLY: (ord("*"), "u"),
    FunctionalKey.KP_SUBTRACT: (ord("-"), "u"),
    FunctionalKey.KP_ADD: (ord("+"), "u"),
    FunctionalKey.KP_ENTER: (KeyCode.ENTER, "u"),
    FunctionalKey.KP_EQUAL: (ord("="), "u"),
    FunctionalKey.KP_LEFT: (LETTER_FORM_CODE, "D"),
    FunctionalKey.KP_RIGHT: (LETTER_FORM_CODE, "C"),
    FunctionalKey.KP_UP: (LETTER_FORM_CODE, "A"),
    FunctionalKey.KP_DOWN: (LETTER_FORM_CODE, "B"),
    FunctionalKey.KP_HOME: (LETTER_FORM_CODE, "H"),
    FunctionalKey.KP_END: (LETTER_FORM_CODE, "F"),
    FunctionalKey.KP_PAGE_UP: (TildeKey.PAGE_UP, "~"),
    FunctionalKey.KP_PAGE_DOWN: (TildeKey.PAGE_DOWN, "~"),
    FunctionalKey.KP_INSERT: (TildeKey.INSERT, "~"),
    FunctionalKey.KP_DELETE: (TildeKey.DELETE, "~"),
}


def folded(event: KeyEvent, flags: int, profile: KeyProfile = DEFAULT_KEY_PROFILE) -> KeyEvent | None:
    """
    The key event as a pane in the legacy encoding reads it.

    The event as it stands, for a pane that asked for a form which can
    carry the number of a key. `None` for a key that the legacy
    encoding cannot write at all.

    The protocol numbers every key that writes no character from
    `FIRST_FUNCTIONAL_KEY` up, so `chr(code)` on one of them gives a
    character no keyboard has and no program wants. A keypad key folds
    onto its normal key. Every other one -- a lock key, a modifier key,
    a media key, F13 upwards -- has no legacy form, so a pane that
    speaks the legacy encoding does not hear it. Lillecarl/pymux#166.

    **This is a choice, and the terminals split on it.** Ghostty sends
    nothing too. kitty sends "CSI 57376 u" for F13, and WezTerm the
    rxvt form "CSI 25 ~". A program that knows neither prints "7376u",
    the symptom of Lillecarl/pymux#684, so the rxvt form is the one a
    `KeyProfile` may choose. Lillecarl/pymux#692.
    """
    if event.final == "u" and event.code == FunctionalKey.MENU and legacy_mode(flags) and (flags or profile.menu):
        # kitty's legacy mode, which is wider than the legacy encoding:
        # "CSI 29 ~" to a pane that pushed only the text, as xterm's F16.
        return event._replace(code=TildeKey.MENU, final="~")
    if carries_the_number(flags):
        return event
    if event.final != "u" or event.code < FIRST_FUNCTIONAL_KEY:
        return event
    normal = KEYPAD_TO_NORMAL.get(event.code)
    if normal is None:
        if flags:
            # A pane that pushed any flag reads the number, as kitty, Ghostty
            # and WezTerm all send it: none of them drops a key once the
            # pane speaks the protocol at all. Lillecarl/pymux#695.
            return event
        if profile.rxvt_function_keys and event.code in _RXVT_FUNCTION_KEY:
            return event._replace(code=_RXVT_FUNCTION_KEY[event.code], final="~")
        return None
    code, final = normal
    return event._replace(code=code, final=final)


def shifted_key_of(event: KeyEvent) -> int | None:
    """
    The key that shift makes of this one, when the terminal said which.

    Only a key with shift held and a shifted key of its own, and never
    a letter under ctrl: ctrl+shift+a is the control code of a, which
    is what kitty writes too (Lillecarl/pymux#168).
    """
    if not event.mods & Modifier.SHIFT or not event.alternates or event.alternates[0] is None:
        return None
    shifted = event.alternates[0]
    if shifted == event.code:
        return None
    if event.mods & Modifier.CTRL and ord("a") <= event.code <= ord("z"):
        return None
    return shifted


def has_a_control_code(code: int) -> bool:
    "Whether ctrl on this key writes a control code in the legacy encoding."
    return (
        ord("a") <= code <= ord("z")
        or code in CONTROL_CODE_OF
        or code in (KeyCode.ENTER, KeyCode.TAB, KeyCode.BACKSPACE, KeyCode.ESCAPE)
    )


def a_legacy_form_carries(code: int, mods: int, shifted: int | None) -> bool:
    """
    Whether a text key has a legacy form under these modifiers, for a
    pane that pushed a flag and so counts the locks.

    kitty's `encode_printable_ascii_key_legacy`: shift is spent on a key
    that has a shifted one, and what is left has to be shift alone, alt,
    ctrl, or ctrl and alt. Space keeps ctrl+shift and alt+shift as well.
    """
    if mods & MODIFIERS_NO_LEGACY_FORM_TAKES:
        return False
    if shifted is not None:
        mods &= ~Modifier.SHIFT
    if not mods & Modifier.SHIFT or mods == Modifier.SHIFT:
        return True
    return code == ord(" ") and mods in (Modifier.CTRL | Modifier.SHIFT, Modifier.ALT | Modifier.SHIFT)


def ctrl_stays_on_the_unshifted_key(code: int, shifted: int, mods: int, profile: KeyProfile) -> bool:
    """
    Whether ctrl+shift writes the control code of the key itself.

    xterm and WezTerm do where the shifted key has none: ctrl+shift+[ is
    ESC there, and "{" in kitty. ctrl+shift+; is ":" in all three.
    Lillecarl/pymux#704.
    """
    return (
        profile.ctrl_on_the_unshifted_key
        and bool(mods & Modifier.CTRL)
        and not has_a_control_code(shifted)
        and has_a_control_code(code)
    )


def carries_the_number(flags: int) -> bool:
    "Every modifier fits when it does: the form has a field for them."
    return bool(
        flags & (KeyboardFlag.DISAMBIGUATE | KeyboardFlag.REPORT_ALL_KEYS | KeyboardFlag.REPORT_ASSOCIATED_TEXT)
    )
