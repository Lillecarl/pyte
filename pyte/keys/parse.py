"""
Key bytes into `KeyEvent`s: control codes, SS3, CSI u, the CSI 27 form
of modifyOtherKeys, and the kitty form with its alternates and text.
"""

from __future__ import annotations

from collections.abc import Sequence

from .events import EventType, KeyCode, KeyEvent, Modifier, TildeKey
from .legacy import BACK_TAB, CTRL_TAKES_OFF_A_LETTER, CTRL_TAKES_OFF_A_SYMBOL, LETTER_FORM_CODE

__all__ = ["MODIFY_OTHER_KEYS", "parse_key_data"]


# Final bytes of the "CSI 1 ; modifier <letter>" functional key form.
#
# "R" is not one of them: "CSI R" is the cursor position report, and a
# pane reading its own input cannot tell the two apart. So F3 takes
# `TildeKey.F3` for a pane that speaks the protocol, and a legacy pane
# reads the SS3 form or the report-shaped "CSI 1;5R" that every
# terminfo entry naming a modified F3 gives, except kitty's.
_LETTER_FINALS = "ABCDEFHPQS"


#: Final bytes of the "SS3 <letter>" form, which F3 does have. The
#: cursor report is a CSI sequence, so "ESC O R" is unambiguous.
_SS3_FINALS = _LETTER_FINALS + "R"


#: The letter each key of the function row takes, by the number rxvt
#: gives it. One key has one event, so a sequence read in the tilde
#: numbering comes out spelled the way the rest of the row is.
#: Lillecarl/pymux#243.
_FUNCTION_ROW_LETTER = {
    TildeKey.F1: "P",
    TildeKey.F2: "Q",
    TildeKey.F3: "R",
    TildeKey.F4: "S",
}


# Parse result items: KeyEvent, or a str to pass through verbatim
# (opaque sequences like device attribute replies).
_Item = KeyEvent | str


def _split_slots(part: str) -> list[int | None]:
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


def _trimmed(slots: Sequence[int | None]) -> tuple[int | None, ...]:
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
        return KeyEvent(code + CTRL_TAKES_OFF_A_LETTER, Modifier.CTRL, "u")
    if code == 0:  # ctrl+@
        return KeyEvent(ord("@"), Modifier.CTRL, "u")
    if 28 <= code <= 31:  # ctrl+\ ^ _
        return KeyEvent(code + CTRL_TAKES_OFF_A_SYMBOL, Modifier.CTRL, "u")
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


def _is_modify_other_keys(final: str, keys: Sequence[int | None], rows: Sequence[Sequence[int | None]]) -> bool:
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


def _parse_csi(data: str, start: int) -> tuple[_Item, int]:
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

    if not params and raw.endswith(BACK_TAB):
        # "CSI Z" is shift and tab, and it is the one key the legacy
        # encoding writes with a modifier inside it. `_encode_event`
        # writes this form, so without reading it back pyte could not
        # read its own output: a back tab reached a pane that speaks
        # the protocol as three bytes of nothing.
        return (
            KeyEvent(KeyCode.TAB, Modifier.SHIFT, "u", "", (), EventType.PRESS),
            i + 1 - start,
        )

    if final in ("u", "~") or final in _LETTER_FINALS:
        # A key of the letter form carries no code of its own: the
        # first parameter is the one of the sequence, and it is one.
        code = _first(keys, 1 if final in _LETTER_FINALS else 0)
        if final == "~" and code in _FUNCTION_ROW_LETTER:
            # The function row, in the form rxvt sends it and kitty
            # sends F3 in. One key has one event, so each takes the
            # spelling of the rest of the row. "CSI 13 u" is Enter and
            # stays Enter: the number is shared and the final byte is
            # not.
            code, final = LETTER_FORM_CODE, _FUNCTION_ROW_LETTER[code]
        text = "".join(chr(n) for n in rows[2] if n) if len(rows) > 2 else ""
        return (
            KeyEvent(code, mods, final, text, alternates, event),
            i + 1 - start,
        )

    # Any other CSI sequence: not a key event.
    return raw, i + 1 - start


def _parse_ss3(data: str, start: int) -> tuple[_Item, int]:
    "Parse an SS3 sequence at data[start] ('ESC O')."
    if start + 2 >= len(data):
        return data[start:], len(data) - start
    char = data[start + 2]
    if char in _SS3_FINALS:
        return KeyEvent(1, 0, char), 3
    return data[start : start + 3], 3


def parse_key_data(data: str) -> list[_Item]:
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
    items: list[_Item] = []
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
                items.append(KeyEvent(inner.code, inner.mods | Modifier.ALT, "u"))
                i += 2
                continue
            items.append(item)
            i += consumed
    return items
