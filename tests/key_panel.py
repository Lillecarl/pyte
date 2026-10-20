"""
The key panel: what three other terminals send for a key, and the vote.

pyte is not a judge. It is the thing on trial, and the vote is taken
among encoders that other people wrote:

- kitty, in C, through its python extension (`kitty_keys.py`);
- Ghostty, in Zig, through libghostty-vt (`key-judges/ghostty_keys.c`);
- WezTerm, in Rust, through termwiz and wezterm-input-types
  (`key-judges/wezterm`);
- xterm, in C, the program itself, with keys pressed into it on an X
  display (`xterm_keys.py`). It speaks no kitty protocol, so it votes
  only for a pane that pushed no flag, and there it is the authority on
  modifyOtherKeys and DECKPAM, which are its own.

`ptterm/tests/panel.py` does the same for a screen, and the verdicts
are the same three, with one more:

- "agree": every judge that answers sends what pyte sends.
- "pyte-wrong": the judges that answer agree with each other, and not
  with pyte.
- "pyte-alone": the judges disagree with each other, and none of them
  sends what pyte sends. pyte made its answer up.
- "split": some judge sends what pyte sends, and another does not. The
  difference is a choice between terminals, not a bug.
- "lone": one judge answers, and differs. One terminal is an opinion,
  not a vote; `test_keys_against_kitty.py` holds kitty's alone.

A judge that cannot be asked **abstains**: kitty has no modifyOtherKeys
and no DECKPAM, Ghostty has one level of modifyOtherKeys and no hyper or
meta, and WezTerm reads a modifier key from a raw event this program
does not have. An abstention is not a vote either way.

`PYTE_GHOSTTY_KEYS` and `PYTE_WEZTERM_KEYS` name the two programs, and
`xterm_keys.py` says what xterm needs.
"""

from __future__ import annotations

import atexit
import os
import subprocess
from collections.abc import Iterable, Sequence
from typing import NamedTuple

from kitty_keys import kitty_encodes, kitty_keys_are_available, typed
from xterm_keys import xterm_keys

__all__ = [
    "JUDGES",
    "Request",
    "Vote",
    "ask",
    "judges_are_available",
    "verdict",
]

#: The judges, in the order a vote lists them.
JUDGES = ("kitty", "ghostty", "wezterm", "xterm")

_PROGRAMS = {"ghostty": "PYTE_GHOSTTY_KEYS", "wezterm": "PYTE_WEZTERM_KEYS"}

#: How many lines go out before the answers are read. A pipe holds 64
#: KiB, and both a request and an answer stay well under 100 bytes.
_BATCH = 256


class Request(NamedTuple):
    "One key in one mode, in the terms every judge reads."

    key: str  # kitty's name, or the character in quotes
    code: int
    shifted: int
    mods: int
    action: str
    flags: int
    cursor_key_mode: bool
    other_keys: int = 0  # the level of xterm's modifyOtherKeys
    keypad: bool = False  # DECKPAM

    def line(self) -> str:
        "The request as the two programs read it."
        text_key = self.key.startswith("'")
        character = typed(self.code, self.shifted, self.mods)
        return "%s %d %s %d %d %d %d %d %d" % (
            "CHAR" if text_key else self.key,
            self.mods,
            self.action,
            self.flags,
            self.cursor_key_mode,
            ord(character) if character else 0,
            self.code if text_key else 0,
            self.other_keys,
            self.keypad,
        )


class _Program:
    "A judge that answers one line with another."

    def __init__(self, path: str) -> None:
        self._process = subprocess.Popen(
            [path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="ascii"
        )
        atexit.register(self._process.kill)

    def ask(self, lines: Sequence[str]) -> list[str | None]:
        answers: list[str | None] = []
        stdin, stdout = self._process.stdin, self._process.stdout
        assert stdin is not None and stdout is not None
        for start in range(0, len(lines), _BATCH):
            batch = lines[start : start + _BATCH]
            stdin.write("".join(line + "\n" for line in batch))
            stdin.flush()
            for _ in batch:
                answer = stdout.readline().rstrip("\n")
                if not answer:
                    raise RuntimeError("a key judge stopped answering")
                answers.append(None if answer == "?" else bytes.fromhex(answer[1:]).decode("utf-8", "surrogateescape"))
        return answers


_programs: dict[str, _Program] = {}


def judges_are_available() -> bool:
    "True when kitty loads, both programs are named and xterm is there."
    if not kitty_keys_are_available() or xterm_keys() is None:
        return False
    for judge, variable in _PROGRAMS.items():
        path = os.environ.get(variable)
        if not path:
            return False
        if judge not in _programs:
            _programs[judge] = _Program(path)
    return True


def _kitty(request: Request) -> str | None:
    if request.other_keys or request.keypad:
        return None
    return kitty_encodes(
        request.code, request.shifted, request.mods, request.action, request.flags, request.cursor_key_mode
    )


def _xterm(request: Request) -> str | None:
    if request.flags:
        return None
    if request.action == "release":
        # The legacy encoding has no release, and xterm sends nothing.
        return ""
    xterm = xterm_keys()
    assert xterm is not None
    own = chr(request.code) if request.key.startswith("'") else ""
    # X repeats a key by pressing it again, so a repeat is a press.
    return xterm.press(
        "CHAR" if own else request.key,
        own,
        request.mods,
        request.cursor_key_mode,
        request.other_keys,
        request.keypad,
    )


def ask(requests: Iterable[Request]) -> list[dict[str, str | None]]:
    "What each judge sends for each request: bytes as a str, or None."
    requests = list(requests)
    lines = [request.line() for request in requests]
    answers = {judge: program.ask(lines) for judge, program in _programs.items()}
    return [
        {
            "kitty": _kitty(request),
            **{judge: answers[judge][i] for judge in _programs},
            "xterm": _xterm(request),
        }
        for i, request in enumerate(requests)
    ]


class Vote(NamedTuple):
    "Which judges side with pyte, which do not, and the verdict."

    verdict: str
    with_pyte: tuple[str, ...]
    against: tuple[str, ...]


def verdict(pyte: str, answers: dict[str, str | None]) -> Vote:
    voters = {judge: answer for judge, answer in answers.items() if answer is not None}
    with_pyte = tuple(judge for judge in JUDGES if judge in voters and voters[judge] == pyte)
    against = tuple(judge for judge in JUDGES if judge in voters and voters[judge] != pyte)
    if not against:
        return Vote("agree", with_pyte, against)
    if with_pyte:
        return Vote("split", with_pyte, against)
    if len(against) == 1:
        return Vote("lone", with_pyte, against)
    if len({voters[judge] for judge in against}) == 1:
        return Vote("pyte-wrong", with_pyte, against)
    return Vote("pyte-alone", with_pyte, against)
