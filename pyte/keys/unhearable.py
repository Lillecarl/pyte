"""
What a pane cannot read of a key. A key whose modifiers its encoding
loses is refused with `Unhearable`, rather than sent as another key.
"""

from __future__ import annotations

from .events import DEFAULT_KEY_PROFILE, KeyCode, KeyEvent, KeyProfile, Modifier, ModifyOtherKeys
from .legacy import (
    MODIFIERS_THE_LEGACY_ENCODING_DROPS,
    MODIFY_OTHER_KEYS_PROFILE,
    carries_the_number,
    ctrl_stays_on_the_unshifted_key,
    folded,
    has_a_control_code,
    shifted_key_of,
)

__all__ = ["Unhearable", "the_modifiers_a_pane_cannot_read"]


class Unhearable(ValueError):
    "A key that a pane in this mode has no way to read."

    def __init__(self, event: KeyEvent, lost: int, encoded: str) -> None:
        self.event = event
        self.lost = lost
        #: What the pane reads instead. Empty for a key with no form.
        self.encoded = encoded
        super().__init__(
            "This pane cannot read the key %r." % (event,)
            if not encoded
            else "This pane reads %r instead of the key %r." % (encoded, event)
        )


def the_modifiers_a_pane_cannot_read(
    event: KeyEvent,
    flags: int,
    profile: KeyProfile = DEFAULT_KEY_PROFILE,
    modify_other_keys: int = ModifyOtherKeys.OFF,
) -> int:
    """
    The bits of `event.mods` this pane has no form for, and zero when
    the key fits whole.

    **The encoder's own accounting, not a second opinion**: each branch
    below is a branch of `_encode_event`, and drift between the two is
    a key sent wrong in silence. A key with no form at all is not here,
    because `translate_key_event` answers with nothing for one.
    """
    if carries_the_number(flags):
        return 0

    lost = event.mods & MODIFIERS_THE_LEGACY_ENCODING_DROPS
    if event.final != "u":
        # The CSI forms write the modifiers in, which is why a legacy
        # pane reads ctrl+shift+Insert whole.
        return lost

    if event.code == KeyCode.TAB and event.mods & Modifier.SHIFT:
        # Back tab is "CSI Z" and carries no ctrl, as in kitty.
        # Lillecarl/pymux#174.
        return lost | (event.mods & Modifier.CTRL)
    # The key shift makes, which the encoder writes under ctrl or alt.
    # Lillecarl/pymux#691.
    shifted = shifted_key_of(event)
    if modify_other_keys:
        profile = MODIFY_OTHER_KEYS_PROFILE
    if event.mods & Modifier.CTRL:
        if shifted is not None and ctrl_stays_on_the_unshifted_key(event.code, shifted, event.mods, profile):
            lost |= Modifier.SHIFT
            code = event.code
        elif shifted is not None:
            code = shifted
        else:
            # ctrl+a and ctrl+shift+a are one control code.
            # Lillecarl/pymux#168.
            lost |= event.mods & Modifier.SHIFT
            legacy_event = folded(event, flags, profile)
            code = event.code if legacy_event is None else legacy_event.code
        if not has_a_control_code(code):
            # ctrl+1 is "1". Lillecarl/pymux#686.
            lost |= Modifier.CTRL
        return lost
    if event.mods & Modifier.ALT and shifted is not None:
        return lost
    if event.mods & Modifier.SHIFT and not chr(event.code).isalpha():
        # Shift is carried by the capital, and "1" has none. A keyboard
        # answers with the text it reports; a name has no text.
        return lost | Modifier.SHIFT
    return lost
