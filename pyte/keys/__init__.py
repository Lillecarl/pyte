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
pane sees what a real kitty gives it. Where the terminals split on a
legacy form, a `KeyProfile` says whose answer a pane gets.
"""

from __future__ import annotations
