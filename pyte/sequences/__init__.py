"""
The bytes that name a sequence, and the sequences built from them.

`escape.py` and `control.py` came from upstream and name what a VT100
and a VT220 send. This package names the rest -- what a VT400 and a
VT500 added, what xterm added after them, and what kitty added after
that -- and writes and reads whole sequences, so that a caller says
what it means instead of a hand-typed string. Lillecarl/pymux#165.

One module per family, each holding its names beside the code that
writes them:

- `escapes`: "ESC <final>", "ESC # <final>" and "ESC SP <final>".
- `csi`: "CSI <params> <final>", and the modes.
- `strings`: the sequences that carry text, OSC, DCS and APC.

`streams.Stream` reads the names from one table, so the names decide
nothing. `Screen.encode_key` stays the one writer of a pane's keys,
and a test that judges it holds the bytes it expects as a literal.
"""

from __future__ import annotations
