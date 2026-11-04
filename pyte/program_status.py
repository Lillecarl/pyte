"""
The Program Status Protocol, "OSC 7501": what a program says it is
doing, held per terminal as records.

A program reports `idle`, `working`, `done`, `blocked` or `error`, and
the terminal keeps one record per id. Nothing here writes a sequence
but the answer to the feature query, and nothing goes back to the
program from a record. Spec revision 0.4, 2026-10-10:
https://www.superlogical.com/rex/docs/build/program-status.
Lillecarl/pymux#927.
"""

from __future__ import annotations

import base64
import re
from enum import StrEnum
from typing import ClassVar, NamedTuple

from .keep import Keep

__all__ = [
    "MAX_RECORDS",
    "QUERY",
    "REPLY",
    "BlockedKind",
    "ProgramState",
    "ProgramStatuses",
    "Report",
    "beneath",
    "parse_report",
    "valid_id",
]


class ProgramState(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    DONE = "done"
    BLOCKED = "blocked"
    ERROR = "error"
    #: Not a state: takes the record and every record under it away.
    CLEAR = "clear"


class BlockedKind(StrEnum):
    PERMISSION = "permission"
    QUESTION = "question"
    AUTH = "auth"


#: The feature query, and the answer: the states and kinds taken here.
QUERY = "?"
REPLY = "?:states=%s:kinds=%s" % (
    ",".join(state for state in ProgramState if state is not ProgramState.CLEAR),
    ",".join(BlockedKind),
)

#: The spec's cap. A report past it drops the record updated longest ago.
MAX_RECORDS = 256

#: The states that the process exiting, or a new prompt, takes away.
_PASSING = frozenset([ProgramState.WORKING, ProgramState.BLOCKED])

#: Most urgent first: what one word for a pane says, when it says one.
URGENCY = (ProgramState.BLOCKED, ProgramState.ERROR, ProgramState.WORKING, ProgramState.DONE, ProgramState.IDLE)

_MAX_PAYLOAD = 4096
_MAX_KEY = 16
_KEY = re.compile(r"[a-z]+\Z")
_VALUE = re.compile(r"[A-Za-z0-9_.,+/=-]*\Z")
_SEGMENT = re.compile(r"[A-Za-z0-9_.+-]{1,32}\Z")
_MAX_ID = 128
_MAX_DEPTH = 8
_APP = _SEGMENT
#: (encoded, decoded) bytes.
_TEXT_LIMITS = {"msg": (2732, 2048), "title": (256, 192)}
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f]")


class Report(NamedTuple):
    """
    One report, checked. `id` is "" for the root record. `title` and
    `msg` are kept as the base64 that came, and as the text it says.

    A NamedTuple and not a frozen dataclass: a hot upgrade freezes and
    thaws the records (`pyte.freeze`), and a thaw sets each field of an
    object it builds, which a frozen dataclass refuses.
    """

    state: ProgramState
    id: str = ""
    kind: BlockedKind | None = None
    progress: int | None = None
    app: str | None = None
    title: str | None = None
    msg: str | None = None
    title_text: str | None = None
    msg_text: str | None = None

    def payload(self, id: str | None = None) -> str:
        "The report as a program writes it, under `id` when given."
        id = self.id if id is None else id
        pairs = ["state=%s" % self.state]
        for key, value in (
            ("id", id or None),
            ("kind", self.kind),
            ("progress", self.progress),
            ("app", self.app),
            ("title", self.title),
            ("msg", self.msg),
        ):
            if value is not None:
                pairs.append("%s=%s" % (key, value))
        return ":".join(pairs)


def valid_id(value: str) -> bool:
    segments = value.split("/")
    return len(value) <= _MAX_ID and len(segments) <= _MAX_DEPTH and all(_SEGMENT.match(s) for s in segments)


def _text(key: str, value: str) -> str | None:
    "The text a base64 value says, or None when the report must go."
    encoded, decoded = _TEXT_LIMITS[key]
    if len(value) > encoded:
        return None
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
        text = raw.decode("utf-8")
    # binascii.Error is a ValueError.
    except ValueError:
        return None
    if len(raw) > decoded or _CONTROL.search(text):
        return None
    return text


def parse_report(payload: str) -> Report | None:
    """
    The report `payload` carries, or None when the spec has it ignored
    or discarded whole. The feature query is not a report.
    """
    if len(payload) > _MAX_PAYLOAD:
        return None
    pairs: dict[str, str] = {}
    for pair in payload.split(":"):
        key, sign, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        if len(key) > _MAX_KEY:
            return None
        if not sign or not _KEY.match(key) or not _VALUE.match(value):
            continue
        pairs[key] = value

    try:
        state = ProgramState(pairs.get("state", ""))
    except ValueError:
        return None

    id = pairs.get("id", "")
    if "id" in pairs and not valid_id(id):
        return None

    texts: dict[str, str] = {}
    for key in _TEXT_LIMITS:
        if key in pairs:
            text = _text(key, pairs[key])
            if text is None:
                return None
            texts[key] = text

    kind = None
    if state is ProgramState.BLOCKED and pairs.get("kind") in set(BlockedKind):
        kind = BlockedKind(pairs["kind"])
    progress = None
    if state in _PASSING and pairs.get("progress", "").isdigit() and int(pairs["progress"]) <= 100:
        progress = int(pairs["progress"])
    app = pairs.get("app")
    if app is not None and not _APP.match(app):
        app = None

    return Report(
        state=state,
        id=id,
        kind=kind,
        progress=progress,
        app=app,
        title=pairs.get("title"),
        msg=pairs.get("msg"),
        title_text=texts.get("title"),
        msg_text=texts.get("msg"),
    )


def beneath(id: str, parent: str) -> bool:
    "Whether `id` is `parent` or beneath it. Everything is beneath the root."
    return not parent or id == parent or id.startswith(parent + "/")


class ProgramStatuses:
    """
    The records of one terminal, updated longest ago first.

    They belong to the terminal and not to a screen: the alternate
    screen leaves them, a full reset takes them, a soft reset does not.
    `version` counts changes, so a reader can tell it has to look again.
    """

    __slots__ = ("records", "version")

    KEEP: ClassVar[dict[str, Keep]] = {
        "records": Keep.SAVED,
        "version": Keep.SAVED,
    }

    def __init__(self) -> None:
        self.records: dict[str, Report] = {}
        self.version = 0

    def take(self, report: Report) -> None:
        if report.state is ProgramState.CLEAR:
            self._drop(lambda id, record: beneath(id, report.id))
            return
        self.records.pop(report.id, None)
        while len(self.records) >= MAX_RECORDS:
            del self.records[next(iter(self.records))]
        self.records[report.id] = report
        self.version += 1

    def passed(self) -> None:
        "The process exited, or a shell prompt began: work in progress is over."
        self._drop(lambda id, record: record.state in _PASSING)

    def clear(self) -> None:
        self._drop(lambda id, record: True)

    def replace(self, reports: list[Report]) -> None:
        "Hold `reports` and nothing else, as another terminal's copy holds them."
        kept = [report for report in reports if report.state is not ProgramState.CLEAR]
        self.records = {report.id: report for report in kept[-MAX_RECORDS:]}
        self.version += 1

    def app_of(self, id: str) -> str | None:
        "The record's `app`, or the nearest ancestor's."
        while True:
            record = self.records.get(id)
            if record is not None and record.app is not None:
                return record.app
            if not id:
                return None
            id = id.rpartition("/")[0]

    def most_urgent(self) -> Report | None:
        "The record a single word for this terminal names."
        return min(self.records.values(), key=lambda record: URGENCY.index(record.state), default=None)

    def _drop(self, which) -> None:
        gone = [id for id, record in self.records.items() if which(id, record)]
        for id in gone:
            del self.records[id]
        if gone:
            self.version += 1
