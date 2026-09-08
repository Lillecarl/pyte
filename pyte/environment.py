"""
What a program run on this screen sees in its environment.

A program has two ways to learn what a terminal can do. It can ask,
which `screen.report_capabilities` answers, or it can read the
environment and the terminfo database, which is what everything built
on ncurses does. This says what the second way should find.

Three things are wrong in an environment that a program inherits
unchanged:

- `TERM` names the terminal the whole application runs in, and not the
  screen this program draws on. A pane of pymux and a widget in a
  Textual layout are both screens of their own.
- The variables that name a terminal by brand say the same lie in a
  louder voice. A file manager that finds `KITTY_WINDOW_ID` draws its
  previews with the unicode placeholders of kitty, which this screen
  does not draw; the same program, asked properly, uses the plain kitty
  placements that it does draw.
- `COLORTERM` decides whether a program writes a colour or the palette
  entry beside it.

`prepare` fixes all three. It is the whole of Lillecarl/pymux#125.

**This module is not the pure layer.** It reads `os` and looks at a
directory, because the entry that describes this screen is a file and
the answer depends on whether it is there. Nothing that parses or holds
a cell imports it, and `tests/test_the_layers.py` says so.
"""

import os
from typing import MutableMapping

from .terminfo import PARENT, TERMINAL_NAME

__all__ = [
    "DEFAULT_DATABASE",
    "FALLBACK_NAME",
    "TERMINAL_IDENTITY_VARIABLES",
    "database",
    "prepare",
    "scrub_terminal_identity",
    "terminal_name",
]

#: Where the compiled entry lives.
#:
#: The build compiles it into the package, beside this file, so that
#: every user of pyte finds it with nothing to configure. A caller that
#: keeps the database somewhere else passes its own directory.
DEFAULT_DATABASE = os.path.join(os.path.dirname(__file__), "terminfo-database")

#: What a program is told when the entry is not there.
#:
#: It is the entry that ours inherits from, so a program that reads it
#: is right about everything except what this screen adds.
#:
#: **Naming an entry that is not installed is worse than naming xterm.**
#: A program that cannot find its own terminal in the database has no
#: capabilities at all, and prints nothing rather than too little.
FALLBACK_NAME = PARENT

#: The variables that name the terminal that a program runs in. Each
#: one is read by at least one program to pick a graphics or a keyboard
#: protocol.
TERMINAL_IDENTITY_VARIABLES = (
    # The generic pair. Every terminal below may set it as well.
    "TERM_PROGRAM",
    "TERM_PROGRAM_VERSION",
    # kitty.
    "KITTY_WINDOW_ID",
    "KITTY_PID",
    "KITTY_INSTALLATION_DIR",
    "KITTY_PUBLIC_KEY",
    # Konsole.
    "KONSOLE_VERSION",
    "KONSOLE_DBUS_SERVICE",
    "KONSOLE_DBUS_SESSION",
    "KONSOLE_DBUS_WINDOW",
    "KONSOLE_PROFILE_NAME",
    # iTerm2.
    "ITERM_SESSION_ID",
    "ITERM_PROFILE",
    # WezTerm.
    "WEZTERM_EXECUTABLE",
    "WEZTERM_EXECUTABLE_DIR",
    "WEZTERM_PANE",
    "WEZTERM_UNIX_SOCKET",
    # Ghostty.
    "GHOSTTY_RESOURCES_DIR",
    "GHOSTTY_BIN_DIR",
    # Windows Terminal.
    "WT_SESSION",
    "WT_PROFILE_ID",
    # Warp.
    "WARP_HONOR_PS1",
    # Visual Studio Code.
    "VSCODE_INJECTION",
    # Tabby.
    "TABBY_CONFIG_DIRECTORY",
    # VTE based terminals (GNOME Terminal, Tilix, ...).
    "VTE_VERSION",
    # Alacritty.
    "ALACRITTY_WINDOW_ID",
    "ALACRITTY_SOCKET",
    "ALACRITTY_LOG",
    # Terminology.
    "TERMINOLOGY",
    # Contour.
    "CONTOUR_PROFILE",
)


def scrub_terminal_identity(environment: MutableMapping[str, str]) -> None:
    """
    Remove the variables that name the outer terminal, in place.

    A remote control socket of the outer terminal is left alone. It
    names a service, not the terminal that a program draws in, and a
    program that uses one still reaches the right window.
    """
    for name in TERMINAL_IDENTITY_VARIABLES:
        environment.pop(name, None)


def database(directory: str = DEFAULT_DATABASE) -> str | None:
    """
    The directory that holds the compiled entry, or None.

    ncurses stores an entry under the first letter of its name, or
    under the hexadecimal of that letter when the database was built to
    hash. Both are looked for, because either can turn up.
    """
    first = TERMINAL_NAME[0]
    for holder in (first, "%02x" % ord(first)):
        if os.path.exists(os.path.join(directory, holder, TERMINAL_NAME)):
            return directory
    return None


def terminal_name(directory: str = DEFAULT_DATABASE) -> str:
    """
    The name to put in `TERM` for a program on this screen.

    It is a function and not a constant, because the answer says
    whether the entry is really there.
    """
    return TERMINAL_NAME if database(directory) else FALLBACK_NAME


def prepare(
    environment: MutableMapping[str, str], directory: str = DEFAULT_DATABASE
) -> None:
    """
    Say, in place, that this program runs on this screen.

    Call it in the child, between the fork and the exec. The mapping is
    `os.environ` there, and every change to it reaches the program and
    nothing else.
    """
    scrub_terminal_identity(environment)

    found = database(directory)
    environment["TERM"] = terminal_name(directory)
    if found is not None:
        # ncurses reads `TERMINFO_DIRS` as a list, and an empty entry
        # in it means the place the system keeps. The trailing colon
        # therefore says "ours first, then everything that was there
        # before".
        already = environment.get("TERMINFO_DIRS")
        environment["TERMINFO_DIRS"] = "%s:%s" % (found, already or "")

    # This screen takes 24 bit colour, whatever the terminal that draws
    # it takes. It keeps the colour that a program writes, and whoever
    # renders it does so as deeply as their own terminal allows.
    #
    # Saying so matters. Without it a program falls back to the 256
    # colours of `TERM` and picks the nearest index itself, which it
    # then writes as that index: a colour of a theme ends up as the
    # palette entry beside it, and nothing downstream can tell what the
    # program meant. (A dark background becomes plain black that way.)
    # The value that the application was started with says nothing
    # about this screen, so it is not inherited either.
    environment["COLORTERM"] = "truecolor"
