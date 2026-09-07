"""
A disassembler for escape sequences.

`DebugScreen` is not a screen. It is a sink with the name of every event
the parser dispatches, and each call writes one JSON line instead of
changing anything. `DebugEvent` reads such a line back and replays it
onto a real screen.

    >>> import io
    >>> from pyte.streams import Stream
    >>> with io.StringIO() as buf:
    ...     stream = Stream(DebugScreen(to=buf))
    ...     stream.feed("\\x1b[1;24r\\x1b[4l")
    ...     print(buf.getvalue())
    ...
    ... # doctest: +NORMALIZE_WHITESPACE
    ["set_margins", [1, 24], {}]
    ["reset_mode", [4], {}]

`pyte.dis` and `python -m pyte` are the command line around it.

**This is a recording at a different grain from `ptyhost-record`.** That
one keeps the bytes a program wrote, which is what a pane really saw and
which cannot be shrunk: drop a byte and the rest of the stream means
something else. A list of events can be shrunk, because each line stands
on its own. That is what a minimiser for a recorded fault would need.

It came from upstream pyte, where it lived in `screens.py` beside three
screens that this package no longer has.
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, NamedTuple

from .streams import Stream

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from typing import TextIO

__all__ = ["DebugEvent", "DebugScreen"]


class DebugEvent(NamedTuple):
    """
    One call that the parser made, as it travels in a file.

    .. warning::

       This is developer API with no backward compatibility guarantees.
       Use at your own risk!
    """

    name: str
    args: Any
    kwargs: Any

    @staticmethod
    def from_string(line: str) -> DebugEvent:
        return DebugEvent(*json.loads(line))

    def __str__(self) -> str:
        return json.dumps(self)

    def __call__(self, screen: Any) -> Any:
        "Do this event on a given `screen`."
        return getattr(screen, self.name)(*self.args, **self.kwargs)


class DebugScreen:
    """
    A screen that writes down what it was asked to do.

    :param to: where the lines go.
    :param only: the events to write, or nothing for all of them.

    .. warning::

       This is developer API with no backward compatibility guarantees.
       Use at your own risk!
    """

    def __init__(self, to: TextIO | None = None, only: Sequence[str] = ()) -> None:
        if to is None:
            import sys

            to = sys.stderr
        self.to = to
        self.only = only

    def only_wrapper(self, attr: str) -> Callable[..., None]:
        def wrapper(*args: Any, **kwargs: Any) -> None:
            self.to.write(str(DebugEvent(attr, args, kwargs)))
            self.to.write(str(os.linesep))

        return wrapper

    def __getattribute__(self, attr: str) -> Callable[..., None]:
        if attr not in Stream.events:
            return super().__getattribute__(attr)  # type: ignore[no-any-return]
        elif not self.only or attr in self.only:
            return self.only_wrapper(attr)
        else:
            return lambda *args, **kwargs: None
