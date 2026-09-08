"""
The two titles a program sets, and the stack it pushes them onto.

A terminal carries a window title and an icon label. "OSC 0", "OSC 1"
and "OSC 2" set them, "CSI 20 t" and "CSI 21 t" report them, and
"CSI 22 t" and "CSI 23 t" push and pop them. Four title modes
("CSI > Ps t") say whether the bytes are hexadecimal on the way in and
on the way out.

None of that touches the cells, so none of it is the screen's. A pane
draws no window and no icon; it holds these so that an embedder can
show what the program asked for, and so that a program that asks gets
its own title back.

Nothing here writes a sequence. `to_report` gives the text and the
screen sends it. `parameters.py` holds `TitleMode` and `TitlePart`,
the numbers that name a mode and a half of the pair.
Lillecarl/pymux#129.
"""

from typing import List, Set, Tuple

from .parameters import TitleMode, TitlePart

__all__ = ("Titles", "title_from_hex", "title_to_hex")


def title_from_hex(text: str) -> str | None:
    """
    The title that a hexadecimal one carries, or None for one that is
    not hexadecimal.

    The bytes are UTF-8, because that is what a pane reads everywhere
    else. An odd number of digits is not a title, and neither is a
    digit that is not one.
    """
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        return None
    return raw.decode("utf-8", "replace")


def title_to_hex(text: str) -> str:
    "A title as the two digits a byte that a hexadecimal query wants."
    return text.encode("utf-8").hex()


class Titles:
    """
    The window title, the icon label, the stack of both, and the modes
    that say how they are written.

    The four go together because every one of them reads the others: a
    push takes both titles, a pop writes one or both, and the modes
    decide how each one is read and reported. A reset takes all four
    away at once.
    """

    #: How many pushes a stack holds. xterm keeps ten and drops the
    #: oldest, so a program that pushes and never pops cannot grow it
    #: without end.
    STACK_LIMIT = 10

    __slots__ = ("window", "icon", "stack", "modes")

    def __init__(self) -> None:
        #: What "OSC 2" set, and what "CSI 21 t" reports.
        self.window = ""

        #: What "OSC 1" set, and what "CSI 20 t" reports.
        self.icon = ""

        #: What "CSI 22 t" pushed, oldest first. One stack holds both
        #: titles, as a pair.
        self.stack: List[Tuple[str, str]] = []

        #: The `TitleMode` members that are on.
        self.modes: Set[int] = set()

    def change_modes(self, params: Tuple[int, ...], on: bool) -> None:
        """
        SM_Title ("CSI > Ps t") and RM_Title ("CSI > Ps T").

        Each parameter names one mode, so one sequence can change
        several. A sequence that carries no parameter names mode zero,
        the way a missing number is a zero everywhere else.

        A number that no mode has is ignored. xterm does the same, and
        a program that asks for a mode nobody carries should not lose
        the modes it asked for in the same sequence.
        """
        for number in params or (0,):
            if number not in tuple(TitleMode):
                continue
            if on:
                self.modes.add(number)
            else:
                self.modes.discard(number)

    def _meant(self, param: str) -> str:
        """
        The title that a program means by `param`.

        "CSI > 0 t" says a program writes a title in hexadecimal. A
        program that turns the mode on and then sends something that is
        not hexadecimal gets the string as it stands: a title nobody can
        read is still better than no title at all.
        """
        if TitleMode.SET_HEX not in self.modes:
            return param
        decoded = title_from_hex(param)
        return param if decoded is None else decoded

    def to_report(self, title: str) -> str:
        """
        The title as "CSI 20 t" and "CSI 21 t" report it.

        "CSI > 1 t" says the terminal reports one in hexadecimal. That
        is how a title reaches a program that cannot read the bytes of
        it as text.

        The two UTF-8 modes are recorded and change nothing here. They
        pick between UTF-8 and Latin-1, and a pane reads and writes
        UTF-8 everywhere, so there is no second reading to pick.
        """
        if TitleMode.QUERY_HEX in self.modes:
            return title_to_hex(title)
        return title

    def set_window(self, param: str) -> None:
        '"OSC 0" and "OSC 2": the title of the window.'
        self.window = self._meant(param)

    def set_icon(self, param: str) -> None:
        '"OSC 0" and "OSC 1": the label of the icon.'
        self.icon = self._meant(param)

    def push(self) -> None:
        """
        "CSI 22 ; Ps t": remember the titles that are set now.

        One stack holds both of them, whichever title the parameter
        names. A pop then takes one entry off and writes back the
        title that its own parameter names, so a push of the icon
        label and a pop of the window title read the same entry.
        xterm answers this way, and the conformance suite reads it.
        """
        self.stack.append((self.icon, self.window))
        del self.stack[: -self.STACK_LIMIT]

    def pop(self, which: int) -> None:
        """
        "CSI 23 ; Ps t": bring back the titles that a push remembered.

        Zero brings back both, one the icon label and two the window
        title. An empty stack leaves both of them alone.
        """
        if not self.stack:
            return

        icon, window = self.stack.pop()
        if which in (TitlePart.BOTH, TitlePart.ICON):
            self.icon = icon
        if which in (TitlePart.BOTH, TitlePart.WINDOW):
            self.window = window
