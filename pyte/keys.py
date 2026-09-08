"""
What a key is, in every mode a keyboard can be in.

A keyboard has three modes, and this module stands between two of
them at once: the mode the terminal of the person is in, and the mode
the program in the pane asked for.

| mode | shape | who asks for it |
| --- | --- | --- |
| legacy | control codes, `ESC` for alt, "CSI 1 ; mods X", SS3 | everybody |
| extended | "CSI 27 ; mods ; code ~", or "CSI code ; mods u" | xterm, vim |
| kitty | "CSI code:alt ; mods:event ; text u", and a flag stack | kitty, foot |

**Three readers and three writers, and never a table between them.**
`parse_key_data` reads bytes into `KeyEvent`s and `translate_key_data`
writes them out again in the form the pane holds. Nothing here turns
one mode into another directly: six arrows would become twelve the day
a fourth mode arrives, and the `KeyEvent` in the middle is what keeps
it at six functions.

Each mode is the legacy encoding plus a rule about which keys leave
it, and no byte sequence means two things, which is what makes one
event in the middle work. Lillecarl/pymux#172.

The process in a pane asks with "CSI > flags u", and `Screen` holds
the stack. What it gets:

- No flag at all: the legacy encoding. A CSI u sequence becomes its
  legacy equivalent, and everything else passes through verbatim.
- `KeyboardFlag.DISAMBIGUATE`: escape and the ctrl and alt
  combinations are written as CSI u. Text keys and a plain Enter, Tab
  or Backspace stay legacy, as the specification asks.
- `KeyboardFlag.REPORT_ALL_KEYS`: every key is written as CSI u.

Three parts of a key event need a terminal that speaks the protocol:
the event type (press, repeat or release), the other codes of the key
(the shifted key and the key of the base layout), and the text that
the key writes. What such a terminal sends passes through to a pane
that asked for it, and goes away for a pane that did not.

All three are served for a legacy terminal as well, as far as it can:

- The text of a printable key needs nothing. The character that the
  terminal sends is that text.
- A key release is made up. The legacy encoding says that a key went
  down and never that it came up, so a key answers with a press and a
  release at once. The pane reads every key going down and coming up;
  only the time between the two is lost. `translate_key_data` takes
  `synthesize=False` to leave that off.
- The shifted key of a letter is the letter. Which key gives an
  exclamation mark depends on the layout of the user, and that the
  legacy encoding does not carry, so such a key reports no other code.
  kitty reports none either for a key that has none.

The forms follow the encoder of kitty (`kitty/key_encoding.c`), so a
pane sees what a real kitty gives it.
"""
from enum import IntEnum, IntFlag
from typing import List, NamedTuple, Sequence, Tuple

__all__ = [
    "translate_key_data",
    "parse_key_data",
    "KeyEvent",
    "KeyCode",
    "FunctionalKey",
    "FIRST_FUNCTIONAL_KEY",
    "current_flags",
    "deliverable_flags",
    "pushed",
    "popped",
    "with_flags_set",
    "EventType",
    "FlagsMode",
    "KeyboardFlag",
    "Modifier",
    "MAX_FLAGS_STACK",
    "FLAGS_THAT_NEED_A_SOURCE",
]


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


#: What ctrl takes off a letter to make its control code: "a" is 97 and
#: ctrl+a is 1.
_CTRL_TAKES_OFF_A_LETTER = ord("a") - 1

#: The same for the four symbols that have a control code. "\\" is 92
#: and ctrl+backslash is 28.
_CTRL_TAKES_OFF_A_SYMBOL = ord("\\") - 28

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
_MODIFIERS_WITH_NO_LEGACY_FORM = (
    Modifier.CTRL
    | Modifier.ALT
    | Modifier.SUPER
    | Modifier.HYPER
    | Modifier.META
)


def _has_a_shifted_character(code: int, text: str) -> bool:
    """
    Whether shift on this key gives a character of its own.

    Shift on a letter gives the capital, and a terminal sends that
    character rather than saying "shift and a letter". Shift on Tab
    gives nothing, which is why shift+Tab is the example xterm uses
    for the level where all the modifiers apply.
    """
    if text:
        return True
    character = chr(code)
    return character.isprintable() and character.upper() != character


def _wants_the_escape_form(level: int, code: int, mods: int, text: str) -> bool:
    """
    Whether this key goes out as "CSI 27 ; mods ; code ~".

    The rule per level is xterm's, in its own words. At
    `ALT_AND_META`, "the usual shift- and control-modifiers work as
    expected, but other modifiers cause ordinary keys to be encoded as
    if they were function-keys".

    At `EVERY_MODIFIER` all of them apply, and shift is the one that
    needs care: a capital letter is a character and goes out as one,
    or a person typing into vim would get escape sequences instead of
    text. Shift counts on a key that has no shifted character, which
    is the shift+Tab that xterm gives as its example.
    """
    if level >= ModifyOtherKeys.EVERY_KEY:
        return True
    if level == ModifyOtherKeys.EVERY_MODIFIER:
        if mods & (Modifier.CTRL | Modifier.ALT):
            return True
        return bool(mods & Modifier.SHIFT) and not _has_a_shifted_character(
            code, text
        )
    if level == ModifyOtherKeys.ALT_AND_META:
        return bool(mods & Modifier.ALT)
    return False


def _legacy_mode(flags: int) -> bool:
    """
    Whether the pane is in what kitty calls the legacy mode.

    kitty reads it off three flags
    (`legacy_mode` in `encode_function_key`, `kitty/key_encoding.c`),
    and the forms that belong to it are the SS3 spelling of an arrow
    or of F1 to F4, and the back tab.
    """
    return not flags & (
        KeyboardFlag.DISAMBIGUATE
        | KeyboardFlag.REPORT_EVENT_TYPES
        | KeyboardFlag.REPORT_ALL_KEYS
    )


class FunctionalKey(IntEnum):
    """
    The number of a keypad key, in the Private Use Area.

    The protocol numbers every key that writes no character from
    `FIRST_FUNCTIONAL_KEY` up. Only the keypad is named here, because
    only the keypad has a normal key to fold onto. The names are the
    ones kitty uses (`functional_key_number_to_name_map` in
    `kitty/key_encoding.py`).
    """

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


class TildeKey(IntEnum):
    'The number of a key in the "CSI number ~" form.'

    INSERT = 2
    DELETE = 3
    PAGE_UP = 5
    PAGE_DOWN = 6


#: The first code point of the Private Use Area. A key numbered from
#: here up writes no character of its own.
FIRST_FUNCTIONAL_KEY = 0xE000

#: The bytes that introduce a control sequence.
CSI = "\x1b["

# Final bytes of the "CSI 1 ; modifier <letter>" functional key form.
_LETTER_FINALS = "ABCDEFHPQS"

#: The number a key of the letter form carries. It is always one: the
#: letter names the key, so the number has nothing to say.
_LETTER_FORM_CODE = 1


#: The most flag sets one screen keeps. The specification asks a
#: terminal to cap the stack, so a program cannot push without end.
MAX_FLAGS_STACK = 64

#: The flags that need a terminal which speaks the protocol. The event
#: type of a key needs a key release, and the other codes of a key need
#: the layout of the user; the legacy encoding carries neither by
#: itself. The other three flags are a form to write a key in, so any
#: terminal serves them.
FLAGS_THAT_NEED_A_SOURCE = (
    KeyboardFlag.REPORT_EVENT_TYPES | KeyboardFlag.REPORT_ALTERNATE_KEYS
)


def current_flags(stack: Tuple[int, ...]) -> int:
    "The flags in force: the top of the stack, or none."
    return stack[-1] if stack else 0


def deliverable_flags(flags: int, source_flags: int, synthesize: bool) -> int:
    """
    The flags a pane really gets, of the ones it asked for.

    A pane asks the terminal what it does, and the answer has to hold.
    When the host makes up what its keyboard cannot send, every flag
    holds: a key release that never comes is invented, and the shifted
    key of a letter is known. Otherwise the answer drops what the
    keyboard cannot serve on its own.
    """
    if synthesize:
        return flags
    return flags & ~(FLAGS_THAT_NEED_A_SOURCE & ~source_flags)


def pushed(stack: Tuple[int, ...], flags: int) -> Tuple[int, ...]:
    "Put one flag set on top. A full stack drops the oldest."
    grown = stack + (flags,)
    return grown[-MAX_FLAGS_STACK:] if len(grown) > MAX_FLAGS_STACK else grown


def popped(stack: Tuple[int, ...], count: int) -> Tuple[int, ...]:
    """
    Take flag sets off the top.

    Popping more than the stack holds, or popping an empty stack, ends
    with no flags at all, which the specification asks for.
    """
    if not stack:
        return stack
    return stack[: -max(1, count)]


def with_flags_set(
    stack: Tuple[int, ...], flags: int, mode: int
) -> Tuple[int, ...] | None:
    """
    The stack that "CSI = flags ; mode u" leaves.

    `None` for a mode nobody defines, which the caller ignores. With no
    stack a set acts like a push, the way kitty does it.
    """
    current = current_flags(stack)
    if mode == FlagsMode.SET_EXACTLY:
        new = flags
    elif mode == FlagsMode.SET_THE_BITS:
        new = current | flags
    elif mode == FlagsMode.CLEAR_THE_BITS:
        new = current & ~flags
    else:
        return None
    return (stack[:-1] if stack else ()) + (new,)


class KeyEvent(NamedTuple):
    "One decoded key event, in the terms of the keyboard protocol."
    code: int  # unicode key code, or the number of the CSI form
    mods: int  # shift/alt/ctrl bitmask (without the +1 offset)
    final: str  # "u", "~" or one of _LETTER_FINALS
    text: str = ""  # reported text, if the terminal sent it
    #: The other codes of the key: the shifted key, then the key of the
    #: base layout. Only a terminal that speaks the protocol sends
    #: them, and it leaves a slot empty when it has nothing for it, so
    #: a slot holds None. Nothing reconstructs these from legacy data:
    #: which key gives a character depends on the layout of the user.
    alternates: Tuple[int | None, ...] = ()
    #: Press, repeat or release. Legacy data holds presses only.
    event: int = EventType.PRESS


# Parse result items: KeyEvent, or a str to pass through verbatim
# (opaque sequences like device attribute replies).
_Item = KeyEvent | str


def _split_slots(part: str) -> List[int | None]:
    """
    Split one parameter into its subparameters, keeping the empty ones.

    "97:65" gives [97, 65] and "97::99" gives [97, None, 99]. An empty
    slot means the default of that slot, and the position carries the
    meaning, so it may not collapse.
    """
    return [int(x) if x else None for x in part.split(":")]


def _first(slots: Sequence[int | None], default: int) -> int:
    "The first slot of a parameter, or the default when it is empty."
    if slots and slots[0] is not None:
        return slots[0]
    return default


def _trimmed(slots: Sequence[int | None]) -> Tuple[int | None, ...]:
    "The slots without the empty ones at the end. They mean nothing."
    kept = list(slots)
    while kept and kept[-1] is None:
        kept.pop()
    return tuple(kept)


def _control_or_text_event(char: str) -> KeyEvent:
    """
    Decode a non-escape character into a key event.

    The key code of the protocol is the key without shift, so an upper
    case letter becomes the lower case one plus the shift modifier.
    The spec says it in these words: "the codepoint used is always the
    lower-case (or more technically, un-shifted) version of the key".

    Only letters take that treatment. Which key gives an exclamation
    mark depends on the layout of the user, and the legacy encoding
    does not carry the layout, so a guess there would be a wrong
    answer on most keyboards. Such a character keeps its own code.
    """
    code = ord(char)
    if char == "\r":
        return KeyEvent(KeyCode.ENTER, 0, "u")
    if char == "\t":
        return KeyEvent(KeyCode.TAB, 0, "u")
    if char == "\x7f":
        return KeyEvent(KeyCode.BACKSPACE, 0, "u")
    if 1 <= code <= 26:  # ctrl+a .. ctrl+z (and \n = ctrl+j)
        return KeyEvent(code + _CTRL_TAKES_OFF_A_LETTER, Modifier.CTRL, "u")
    if code == 0:  # ctrl+@
        return KeyEvent(ord("@"), Modifier.CTRL, "u")
    if 28 <= code <= 31:  # ctrl+\ ^ _
        return KeyEvent(code + _CTRL_TAKES_OFF_A_SYMBOL, Modifier.CTRL, "u")
    # A printable character is the text of its own key event. A pane
    # that asks for the text of a key gets it that way, also from a
    # terminal that speaks the legacy encoding only.
    lower = char.lower()
    if char.isupper() and lower != char and len(lower) == 1:
        # The shifted key of a letter is the letter, so a pane that
        # asks for the other codes of a key gets that one. The key of
        # the base layout stays empty: kitty leaves it out for a
        # layout where it is the key itself, which is every Latin one.
        return KeyEvent(ord(lower), Modifier.SHIFT, "u", char, (code,))
    if char.isprintable():
        return KeyEvent(code, 0, "u", char)
    return KeyEvent(code, 0, "u")


#: The number in the first parameter of a key in the modifyOtherKeys
#: form. It names the form and not a key: the key is in the third
#: parameter. xterm chose the code of the Escape key for it.
MODIFY_OTHER_KEYS = 27


def _is_modify_other_keys(
    final: str, keys: Sequence[int | None], rows: Sequence[Sequence[int | None]]
) -> bool:
    """
    Whether this is a key in xterm's modifyOtherKeys form.

    The form is "CSI 27 ; mods ; code ~", and the third parameter is
    the value of the key without its modifiers: alt+Tab is
    "CSI 27 ; 3 ; 9 ~", and shift+Tab is "CSI 27 ; 2 ; 9 ~"
    (`xterm-snapshots/ctlseqs.ms`, under "Alt and Meta Keys").

    Three things have to hold at once, and nothing else has that
    shape. A key of the "~" form is numbered by the table of the
    VT220, which stops well short of 27. The kitty protocol numbers a
    key by its code point in the "u" form and never in the "~" one.
    """
    return (
        final == "~"
        and len(rows) == 3
        and _first(keys, 0) == MODIFY_OTHER_KEYS
        and bool(rows[2])
        and rows[2][0] is not None
    )


def _parse_csi(data: str, start: int) -> Tuple[_Item, int]:
    "Parse a CSI sequence at data[start] ('ESC [')."
    i = start + 2
    params = ""
    while i < len(data):
        char = data[i]
        if "\x40" <= char <= "\x7e":
            break
        params += char
        i += 1
    else:
        # Incomplete sequence. Pass the remainder through untouched.
        return data[start:], len(data) - start

    final = data[i]
    raw = data[start : i + 1]

    # Private markers ("<=>?"): protocol control or a reply, not a key
    # event. Pass through verbatim.
    if params[:1] in ("<", "=", ">", "?"):
        return raw, i + 1 - start

    # The full form of a key event is
    # "CSI code:shifted:base ; mods:event ; text final".
    rows = [_split_slots(part) for part in params.split(";")] if params else []
    keys = rows[0] if rows else []
    modifiers = rows[1] if len(rows) > 1 else []
    mods = max(0, _first(modifiers, 1) - 1)
    event = modifiers[1] if len(modifiers) > 1 and modifiers[1] else EventType.PRESS
    alternates = _trimmed(keys[1:])

    if _is_modify_other_keys(final, keys, rows):
        # xterm's modifyOtherKeys. The key is in the third parameter
        # and the first one names the form, so reading this as a key of
        # the "~" form gives the wrong key: ctrl+a, alt+a and
        # ctrl+enter all became "CSI 27 ; mods ~", which is none of
        # them. Lillecarl/pymux#171.
        return (
            KeyEvent(_first(rows[2], 0), mods, "u", "", (), event),
            i + 1 - start,
        )

    if final in ("u", "~") or final in _LETTER_FINALS:
        # A key of the letter form carries no code of its own: the
        # first parameter is the one of the sequence, and it is one.
        code = _first(keys, 1 if final in _LETTER_FINALS else 0)
        text = (
            "".join(chr(n) for n in rows[2] if n) if len(rows) > 2 else ""
        )
        return (
            KeyEvent(code, mods, final, text, alternates, event),
            i + 1 - start,
        )

    # Any other CSI sequence: not a key event.
    return raw, i + 1 - start


def _parse_ss3(data: str, start: int) -> Tuple[_Item, int]:
    "Parse an SS3 sequence at data[start] ('ESC O')."
    if start + 2 >= len(data):
        return data[start:], len(data) - start
    char = data[start + 2]
    if char in _LETTER_FINALS:
        return KeyEvent(1, 0, char), 3
    return data[start : start + 3], 3


def parse_key_data(data: str) -> List[_Item]:
    """
    Decode raw key data into key events and verbatim pass-throughs.

    This is the reader of every mode a keyboard can be in: the legacy
    encoding, the "CSI code ; mods u" form that fixterms named and
    kitty extended, and xterm's "CSI 27 ; mods ; code ~". A caller
    gets `KeyEvent`s and the strings that are not keys, and writes
    them out again in whatever form it owes.

    Two callers, and they owe different things. `translate_key_data`
    below writes bytes for a pane. pymux writes a prompt_toolkit key
    press, because a binding has to be able to name it.
    """
    items: List[_Item] = []
    i = 0
    length = len(data)
    while i < length:
        char = data[i]
        if char != "\x1b":
            items.append(_control_or_text_event(char))
            i += 1
        elif i + 1 >= length:
            # Trailing escape: the Escape key.
            items.append(KeyEvent(27, 0, "u"))
            break
        else:
            nxt = data[i + 1]
            if nxt == "[":
                item, consumed = _parse_csi(data, i)
            elif nxt == "O":
                item, consumed = _parse_ss3(data, i)
            else:
                # alt+char in the legacy encoding.
                inner = _control_or_text_event(nxt)
                items.append(
                    KeyEvent(inner.code, inner.mods | Modifier.ALT, "u")
                )
                i += 2
                continue
            items.append(item)
            i += consumed
    return items


def _serialize(
    code: int,
    mods_value: int,
    final: str,
    alternates: Tuple[int | None, ...] = (),
    event: int = EventType.PRESS,
    text: str = "",
) -> str:
    """
    Write one key event in the escape code form of the protocol.

    The form is "CSI code:shifted:base ; mods:event ; text final". A
    field that holds its default stays empty, and a field at the end
    that holds its default is left out. This follows the encoder of
    kitty, so that a pane sees what a real kitty gives it.

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
        out += ":" + ":".join(
            "" if slot is None else str(slot) for slot in alternates
        )
    if second or third:
        out += ";"
        if mods_value != 1:
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
_KEYPAD_TO_NORMAL = {
    **{
        FunctionalKey.KP_0 + n: (ord("0") + n, "u") for n in range(10)
    },
    FunctionalKey.KP_DECIMAL: (ord("."), "u"),
    FunctionalKey.KP_DIVIDE: (ord("/"), "u"),
    FunctionalKey.KP_MULTIPLY: (ord("*"), "u"),
    FunctionalKey.KP_SUBTRACT: (ord("-"), "u"),
    FunctionalKey.KP_ADD: (ord("+"), "u"),
    FunctionalKey.KP_ENTER: (KeyCode.ENTER, "u"),
    FunctionalKey.KP_EQUAL: (ord("="), "u"),
    FunctionalKey.KP_LEFT: (_LETTER_FORM_CODE, "D"),
    FunctionalKey.KP_RIGHT: (_LETTER_FORM_CODE, "C"),
    FunctionalKey.KP_UP: (_LETTER_FORM_CODE, "A"),
    FunctionalKey.KP_DOWN: (_LETTER_FORM_CODE, "B"),
    FunctionalKey.KP_HOME: (_LETTER_FORM_CODE, "H"),
    FunctionalKey.KP_END: (_LETTER_FORM_CODE, "F"),
    FunctionalKey.KP_PAGE_UP: (TildeKey.PAGE_UP, "~"),
    FunctionalKey.KP_PAGE_DOWN: (TildeKey.PAGE_DOWN, "~"),
    FunctionalKey.KP_INSERT: (TildeKey.INSERT, "~"),
    FunctionalKey.KP_DELETE: (TildeKey.DELETE, "~"),
}


#: The bytes that introduce a single shift three. The application
#: keypad and the application cursor keys both write one.
SS3 = "\x1bO"

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
    **{
        FunctionalKey.KP_0 + n: chr(ord("p") + n) for n in range(10)
    },
    FunctionalKey.KP_MULTIPLY: "j",
    FunctionalKey.KP_ADD: "k",
    FunctionalKey.KP_SEPARATOR: "l",
    FunctionalKey.KP_SUBTRACT: "m",
    FunctionalKey.KP_DECIMAL: "n",
    FunctionalKey.KP_DIVIDE: "o",
    FunctionalKey.KP_EQUAL: "X",
    FunctionalKey.KP_ENTER: "M",
}


def _application_keypad_form(event: KeyEvent, flags: int) -> str | None:
    """
    What this key sends to a pane that turned the application keypad
    on, or None when the mode does not reach it.

    It belongs to the legacy mode, the way the SS3 form of an arrow
    does: a pane that pushed a kitty flag reads the number of the key.
    A modifier takes it out too, because xterm gives a modified keypad
    key to `modifyKeypadKeys` and this screen has no such resource.
    """
    if not _legacy_mode(flags):
        return None
    if event.mods or event.event != EventType.PRESS or event.final != "u":
        return None
    final = _KEYPAD_APPLICATION.get(event.code)
    return None if final is None else SS3 + final


def _folded(event: KeyEvent, flags: int) -> KeyEvent | None:
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
    speaks the legacy encoding does not hear it. kitty does the same.
    Lillecarl/pymux#166.
    """
    carries_the_number = flags & (
        KeyboardFlag.DISAMBIGUATE
        | KeyboardFlag.REPORT_ALL_KEYS
        | KeyboardFlag.REPORT_ASSOCIATED_TEXT
    )
    if carries_the_number:
        return event
    if event.final != "u" or event.code < FIRST_FUNCTIONAL_KEY:
        return event
    normal = _KEYPAD_TO_NORMAL.get(event.code)
    if normal is None:
        return None
    code, final = normal
    return event._replace(code=code, final=final)


def _encode_event(
    event: KeyEvent,
    flags: int,
    application_mode: bool,
    modify_other_keys: int = ModifyOtherKeys.OFF,
    application_keypad: bool = False,
    format_other_keys: int = FormatOtherKeys.TILDE,
    backarrow_sends_backspace: bool = False,
) -> str:
    "Encode a key event for a pane with the given protocol flags."
    if application_keypad:
        keypad = _application_keypad_form(event, flags)
        if keypad is not None:
            return keypad
    plain = _folded(event, flags)
    if plain is None:
        return ""
    code, mods, final, text, alternates, kind = plain
    mods_value = mods + 1

    # Only a pane that asked for the event types can read a release. A
    # repeat without that flag is a press: that is what the key did.
    if kind == EventType.RELEASE and not flags & KeyboardFlag.REPORT_EVENT_TYPES:
        return ""
    if not flags & KeyboardFlag.REPORT_EVENT_TYPES:
        kind = EventType.PRESS
    if kind == EventType.RELEASE and mods == 0 and code in _CONTROL_CODES:
        if not flags & KeyboardFlag.REPORT_ALL_KEYS:
            return ""
    if not flags & KeyboardFlag.REPORT_ALTERNATE_KEYS or final != "u":
        # kitty sends the other codes of a key for the "u" form only.
        alternates = ()
    embedded = text if flags & KeyboardFlag.REPORT_ASSOCIATED_TEXT else ""

    if final == "u":
        ambiguous = (
            bool(mods & _MODIFIERS_WITH_NO_LEGACY_FORM)
            or code == KeyCode.ESCAPE
        )
        # A functional key still here belongs to a pane that reads the
        # number of a key: `_folded` took it away from every other one.
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
            or no_legacy_form
            or (back_tab and not _legacy_mode(flags))
            or kind != EventType.PRESS
            or alternates
            or embedded
        ):
            return _serialize(
                code, mods_value, "u", alternates, kind, embedded
            )

        # The extended mode, which a pane asks for with XTMODKEYS and
        # not with the flag stack. A pane in one of the kitty modes
        # never gets here, because every branch above answers first.
        # Lillecarl/pymux#169.
        if _wants_the_escape_form(modify_other_keys, code, mods, text):
            if format_other_keys == FormatOtherKeys.CSI_U:
                return "%s%d;%du" % (CSI, code, mods_value)
            return "%s27;%d;%d~" % (CSI, mods_value, code)

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
        if mods & (Modifier.CTRL | Modifier.ALT):
            result = "\x1b" if mods & Modifier.ALT else ""
            if mods & Modifier.CTRL:
                if code == KeyCode.ENTER:
                    result += "\n"
                elif code == KeyCode.TAB:
                    result += "\t"
                elif code == KeyCode.BACKSPACE:
                    result += "\x08"
                elif ord("a") <= code <= ord("z"):
                    result += chr(code - _CTRL_TAKES_OFF_A_LETTER)
                elif code == ord("@"):
                    result += "\x00"
                elif ord("\\") <= code <= ord("_"):
                    result += chr(code - _CTRL_TAKES_OFF_A_SYMBOL)
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
        char = chr(code)
        if mods & Modifier.SHIFT and char.isalpha():
            char = char.upper()
        return char

    if final == "~":
        return _serialize(code, mods_value, "~", (), kind, embedded)

    # Functional keys with a letter final byte.
    if mods == 0 and kind == EventType.PRESS and not embedded:
        # The SS3 form belongs to a pane that pushed no flag at all.
        if _legacy_mode(flags):
            if application_mode and final in "ABCD":
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
) -> str:
    """
    Translate raw key data into the encoding for a pane with the given
    keyboard protocol flags.

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
    """
    # The release of a key that the terminal never reports coming up.
    double = bool(
        synthesize
        and flags & KeyboardFlag.REPORT_EVENT_TYPES
        and not source_flags & KeyboardFlag.REPORT_EVENT_TYPES
    )

    parts = []
    for item in parse_key_data(data):
        if not isinstance(item, KeyEvent):
            parts.append(item)
            continue
        parts.append(
            _encode_event(
                item,
                flags,
                application_mode,
                modify_other_keys,
                application_keypad,
                format_other_keys,
                backarrow_sends_backspace,
            )
        )
        if double and item.event == EventType.PRESS:
            parts.append(
                _encode_event(
                    item._replace(event=EventType.RELEASE), flags, application_mode
                )
            )
    return "".join(parts)
