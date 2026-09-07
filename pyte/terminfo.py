"""
The terminfo entry that describes this screen.

A program has two ways to learn what a terminal can do. It can ask,
which `screen.report_capabilities` answers, or it can read the
database of the machine it runs on, which is what every program built
on ncurses does.

This holds the table for both ways, and writes the entry for the
second one. One source, two readers: the database and the wire cannot
say different things. `screen.report_capabilities` reads `CAPABILITIES`
here, and so does `terminfo_source`.

Compile it with:

    python -m pyte.terminfo | tic -x -o <directory> -

The entry names `xterm-256color` as its parent, because that is what a
pane emulates apart from the capabilities below. `tic` copies the
parent in, so what comes out stands on its own.

Lillecarl/pymux#129.
"""
import sys
from typing import Dict

from .colors import PALETTE

__all__ = [
    "CAPABILITIES",
    "PARENT",
    "TERMINAL_ALIAS",
    "TERMINAL_NAME",
    "terminfo_source",
]

#: The entry that a pane emulates apart from what it adds. `tic`
#: copies it in, so the result needs nothing else at run time.
PARENT = "xterm-256color"

#: The name of the terminfo entry that describes this screen. A program
#: reads it with the "TN" capability, and it is what belongs in `TERM`.
#:
#: **It names the screen and not an embedder.** It was "pymux" while
#: this code lived inside the multiplexer, and that was already wrong:
#: what the entry describes is what the screen below draws, which is the
#: same whether pymux arranged the pane, a prompt_toolkit widget holds
#: it, or a Textual one does.
#:
#: **"256color" is deliberately not in this name**, and the pictures of
#: a real terminal are what says so.
#:
#: tmux and screen both put it in theirs, and the habit comes from when
#: 8, 16, 88 and 256 were the axis a terminal varied on. A lot of
#: software still reads the substring out of `TERM` rather than opening
#: the database. That cuts both ways, and in a pane it cuts the wrong
#: way: **a screen takes 24 bit colour**, and a program that reads
#: "256color" picks the nearest index of the palette itself and writes
#: that index. The colour a program meant is then lost before the pane
#: ever sees it. `pymux/main.py` sets `COLORTERM=truecolor` for exactly
#: that reason, and a name that says 256 argues with it.
#:
#: Measured: with "pyte-256color" in `TERM`, `checks.pymux-pictures`
#: found about 5700 pixels of difference on the colour fixture in both
#: foot and kitty, and on two recordings of real programs. With "pyte"
#: there is none. xterm shows nothing either way, because it cannot
#: draw a colour of its own anyway.
#:
#: The name that does mean direct colour is `xterm-direct`, and it is
#: not one to take: it sets `colors#0x1000000` and **redefines `setaf`
#: and `setab` so the argument is a packed colour and not a place in
#: the palette**. Every program that uses the palette draws the wrong
#: thing under it.
#:
#: So the palette is claimed where a claim belongs, in the entry: the
#: parent is `xterm-256color`, and `RGB` and `Tc` in `CAPABILITIES` say
#: the rest. `TERMINAL_ALIAS` is the spelling with the suffix, which
#: `tic` links to the same entry, so a program that looks the long name
#: up still finds it.
TERMINAL_NAME = "pyte"
TERMINAL_ALIAS = "pyte-256color"

#: What a pane can do, in the form that XTGETTCAP answers.
#:
#: A program asks over the wire instead of reading a database, which is
#: the only way it can learn what a pane can do: `TERM` names an entry
#: that may not be installed where the program runs, and over ssh it
#: is the only way at all.
#:
#: `True` is a capability that a terminal either has or does not. A
#: string is a value, and one that holds "%" travels as the source
#: text, the way terminfo writes it.
#:
#: Nothing goes in here that a pane does not really do. A capability
#: that is claimed and not served is worse than one that is missing:
#: the program stops asking and draws what it cannot draw.
CAPABILITIES: Dict[str, object] = {
    # The name of the entry.
    "TN": TERMINAL_NAME,
    "name": TERMINAL_NAME,
    # Automatic margins, and the wrap that waits in the last column.
    "am": True,
    "xenl": True,
    # An erased cell takes the background that is set.
    "bce": True,
    # 24 bit colour, under both names that a program looks for.
    "RGB": True,
    "Tc": True,
    # The shape and the colour of an underline.
    "Su": True,
    "Smulx": r"\E[4:%p1%dm",
    "Setulc": r"\E[58:2:%p1%{65536}%/%d:%p1%{256}%/%{255}%&%d:%p1%{255}%&%d%;m",
    # The keyboard protocol of kitty.
    "fullkbd": True,
    # The clipboard, which a pane may write.
    "Ms": r"\E]52;%p1%s;%p2%s\E\\",
    # A number is a number here, so that one table can answer a
    # query and describe an entry of terminfo.
    # The size of the palette, under both names. A program reads this
    # to learn where the special colours start, so it must be the size
    # of the table that answers "OSC 4".
    "colors": len(PALETTE),
    "Co": len(PALETTE),
    "pairs": 32767,
}

#: The names of `CAPABILITIES` that describe the query and not the
#: terminal. "TN" and "name" answer with the name of the entry, and
#: "Co" is what termcap calls "colors".
NOT_IN_THE_ENTRY = frozenset(["TN", "name", "Co"])


def terminfo_source(name: str = TERMINAL_NAME, parent: str = PARENT) -> str:
    """
    The entry, as `tic` reads it.

    A capability that is only there or not takes its name alone, a
    number takes "#" and a string takes "=". That is the whole syntax
    that this needs.
    """
    booleans = []
    numbers = []
    strings = []
    for capability, value in sorted(CAPABILITIES.items()):
        if capability in NOT_IN_THE_ENTRY:
            continue
        if value is True:
            booleans.append("%s," % capability)
        elif isinstance(value, int):
            numbers.append("%s#%d," % (capability, value))
        else:
            strings.append("%s=%s," % (capability, value))

    # The first field is the name, the ones after it are aliases that
    # `tic` links to the same entry, and the last is the description a
    # person reads. So `TERM=pyte` finds this as well.
    lines = ["%s|%s|the pyte terminal emulator," % (name, TERMINAL_ALIAS)]
    lines.extend("\t" + line for line in booleans + numbers + strings)
    lines.append("\tuse=%s," % parent)
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.write(terminfo_source())


if __name__ == "__main__":
    main()
