"""
The kitty keyboard flag stack that a program pushes and pops with
"CSI > flags u", and which of its flags a pane can be given for the
terminal in front of it.
"""

from __future__ import annotations

from .events import FlagsMode, KeyboardFlag

__all__ = [
    "FLAGS_THAT_NEED_A_SOURCE",
    "MAX_FLAGS_STACK",
    "current_flags",
    "deliverable_flags",
    "popped",
    "pushed",
    "with_flags_set",
]


#: The most flag sets one screen keeps. The specification asks a
#: terminal to cap the stack, so a program cannot push without end.
MAX_FLAGS_STACK = 64


#: The flags that need a terminal which speaks the protocol. The event
#: type of a key needs a key release, and the other codes of a key need
#: the layout of the user; the legacy encoding carries neither by
#: itself. The other three flags are a form to write a key in, so any
#: terminal serves them.
FLAGS_THAT_NEED_A_SOURCE = KeyboardFlag.REPORT_EVENT_TYPES | KeyboardFlag.REPORT_ALTERNATE_KEYS


def current_flags(stack: tuple[int, ...]) -> int:
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


def pushed(stack: tuple[int, ...], flags: int) -> tuple[int, ...]:
    "Put one flag set on top. A full stack drops the oldest."
    grown = (*stack, flags)
    return grown[-MAX_FLAGS_STACK:] if len(grown) > MAX_FLAGS_STACK else grown


def popped(stack: tuple[int, ...], count: int) -> tuple[int, ...]:
    """
    Take flag sets off the top.

    Popping more than the stack holds, or popping an empty stack, ends
    with no flags at all, which the specification asks for.
    """
    if not stack:
        return stack
    return stack[: -max(1, count)]


def with_flags_set(stack: tuple[int, ...], flags: int, mode: int) -> tuple[int, ...] | None:
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
