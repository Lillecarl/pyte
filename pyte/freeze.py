"""
A screen as plain data, and back.

`freeze` walks an object's `KEEP` (`pyte.keep`) and turns every saved
field into JSON-shaped values; `thaw` writes them into a fresh object.
A hot upgrade carries a screen to a new build this way
(Lillecarl/pymux#399), so nothing here is pickled: a new build reads
the values, never the old build's classes.

**Containers are tagged, scalars are not.** A list, tuple, set and dict
all become JSON arrays, so each one says which it was. An object, a
named tuple and an enum carry the dotted name of their class, and only
`pyte` classes are named: a thaw builds nothing else.

**What two fields share stays shared.** A mutable value gets an id the
first time the walk meets it, and a reference after that. The parked
state of the alternate screen holds the first page's buffer, and a
thaw that made two buffers would let them drift apart.

**Cells are apart from the rest.** A buffer is a reference into
`Frozen.buffers`, one entry per row, and an appearance is an index
into `Frozen.appearances`. The rows are most of a screen, so an
embedder stores them as rows of its own, and their encoding is short:
`[column, char, appearance, kind]`.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from enum import Enum
from typing import Any, NamedTuple

from .cells import (
    _CHAR_CACHE,
    _PROTECTED_CHAR_CACHE,
    PLAIN_APPEARANCE,
    UNWRITTEN,
    Appearance,
    Cell,
    ErasedCell,
    ProtectedCell,
    WrittenCell,
    appearance_of,
)
from .keep import Keep
from .page import Row

__all__ = ["Frozen", "freeze", "thaw"]

#: A cell's kind in a frozen row. A protected cell adds its marks to
#: `PROTECTED`, so the marks travel in the same number.
PLAIN, WRITTEN, ERASED, PROTECTED = 0, 1, 2, 3

_KINDS: dict[type, int] = {Cell: PLAIN, WrittenCell: WRITTEN, ErasedCell: ERASED}

#: A frozen row: its number, whether a wrap made it, and its cells.
FrozenRow = list


class Frozen(NamedTuple):
    """
    One frozen object, and the rows and appearances it points into.

    A first freeze holds everything. A later freeze by the same
    `Freezer` holds what changed since the one before it, and `merge`
    lays it over that one.
    """

    root: Any
    #: Rows by the id of their buffer, as a string so JSON keeps it:
    #: `[number, wrapped, cells]`. Every row of a buffer in `whole`, and
    #: the rows written since the freeze before for any other.
    buffers: dict[str, list[FrozenRow]]
    #: The appearances new since the freeze before, each one
    #: `[rendition, hyperlink, hyperlink_id]`. A cell's index counts
    #: from the first freeze.
    appearances: list[Any]
    #: The buffers given whole, which replace what the freeze before said.
    whole: list[str]
    #: Rows gone since the freeze before, by buffer.
    removed: dict[str, list[int]]


def saved_fields(cls: type) -> list[str]:
    "The fields a class saves, along its MRO, the nearest declaration winning."
    keep: dict[str, Keep] = {}
    for one in reversed(cls.__mro__):
        keep.update(one.__dict__.get("KEEP", {}))
    return [name for name, fate in keep.items() if fate == Keep.SAVED]


def _name(cls: type) -> str:
    return "%s.%s" % (cls.__module__, cls.__qualname__)


def _class(name: str) -> type:
    module, _, qualname = name.rpartition(".")
    if module != "pyte" and not module.startswith("pyte."):
        raise ValueError("a frozen screen names %s, which is not pyte's" % name)
    # Only a module the screen already loaded: a thaw imports nothing.
    return getattr(sys.modules[module], qualname)


def freeze(root: object) -> Frozen:
    "Everything `root` saves, and everything that reaches, as plain data."
    return Freezer().freeze(root)


def merge(base: Frozen, later: Frozen) -> Frozen:
    "What `base` holds once a later freeze by the same `Freezer` is laid over it."
    buffers = {}
    for number in later.whole:
        buffers[number] = later.buffers[number]
    for number, rows in base.buffers.items():
        if number in buffers:
            continue
        by_row = {row[0]: row for row in rows}
        for gone in later.removed.get(number, ()):
            by_row.pop(gone, None)
        for row in later.buffers.get(number, ()):
            by_row[row[0]] = row
        buffers[number] = [by_row[row] for row in sorted(by_row)]
    for number, rows in later.buffers.items():
        buffers.setdefault(number, rows)
    return Frozen(later.root, buffers, [*base.appearances, *later.appearances], sorted(buffers), {})


class Freezer:
    """
    Freezes one object, and then again with only the rows that changed.

    The rows are most of a screen and a program writes few of them at
    a time, so a second freeze costs what was written since the first,
    not the depth of the history. That is what bounds the pause of an
    upgrade: the first freeze runs while the server still serves, and
    only the second runs in the pause. Lillecarl/pymux#399.

    The root says what changed through two methods: `write_mark()`,
    which names this moment, and `changes_since(mark)`, which gives
    `(buffer, rows)` for each buffer written since, or `None` when it
    cannot say and every buffer goes again. A root without them is
    frozen whole every time.
    """

    def __init__(self) -> None:
        self.mark: Any = None
        # Holds every object the freezer gave an id, so no id is reused.
        self.held: list[object] = []
        self.buffer_ids: dict[int, str] = {}
        self.rows_frozen: dict[str, set[int]] = {}
        self.appearance_index: dict[int, int] = {}

    def freeze(self, root: object) -> Frozen:
        changes = None
        if self.mark is not None and hasattr(root, "changes_since"):
            changes = root.changes_since(self.mark)  # type: ignore[attr-defined]
        mark = root.write_mark() if hasattr(root, "write_mark") else None  # type: ignore[attr-defined]
        walk = _Walk(self, None if changes is None else {id(buffer): rows for buffer, rows in changes})
        frozen = walk.run(root)
        self.mark = mark
        return frozen

    def buffer_id(self, buffer: object) -> tuple[str, bool]:
        "The stable id of a buffer, and whether an earlier freeze gave it."
        known = self.buffer_ids.get(id(buffer))
        if known is not None:
            return known, True
        self.held.append(buffer)
        new = self.buffer_ids[id(buffer)] = str(len(self.buffer_ids))
        return new, False


class _Walk:
    "One freeze: the state whole, and the rows the freezer has not seen."

    def __init__(self, freezer: Freezer, changes: dict[int, list[int]] | None) -> None:
        self.freezer = freezer
        #: Rows written since the freeze before, by `id(buffer)`, or
        #: `None` for every buffer whole.
        self.changes = changes
        self.ids: dict[int, int] = {}
        self.held: list[object] = []
        self.buffers: dict[str, list[FrozenRow]] = {}
        self.whole: list[str] = []
        self.removed: dict[str, list[int]] = {}
        self.appearances: list[Any] = []

    def run(self, root: object) -> Frozen:
        return Frozen(self.value(root), self.buffers, self.appearances, self.whole, self.removed)

    def _id(self, value: object) -> tuple[int, bool]:
        "The id of a mutable value, and whether the walk met it before."
        known = self.ids.get(id(value))
        if known is not None:
            return known, True
        new = self.ids[id(value)] = len(self.ids)
        self.held.append(value)
        return new, False

    def value(self, value: Any) -> Any:
        kind = type(value)
        if value is None or kind in (bool, int, float, str):
            return value
        if isinstance(value, Enum):
            return {"enum": _name(kind), "value": value.value}
        if isinstance(value, tuple):
            if hasattr(kind, "_fields"):
                return {"namedtuple": _name(kind), "fields": [self.value(item) for item in value]}
            return {"tuple": [self.value(item) for item in value]}
        if kind is bytes:
            return {"bytes": value.hex()}
        if kind is defaultdict and value.default_factory is Row:
            return {"buffer": self.buffer(value)}

        number, seen = self._id(value)
        if seen:
            return {"ref": number}
        if kind is list:
            return {"list": [self.value(item) for item in value], "id": number}
        if kind in (set, frozenset):
            return {kind.__name__: [self.value(item) for item in sorted(value, key=repr)], "id": number}
        if kind is dict:
            return {"dict": [[self.value(key), self.value(item)] for key, item in value.items()], "id": number}
        if not any("KEEP" in cls.__dict__ for cls in kind.__mro__):
            raise TypeError("cannot freeze %s: it declares no KEEP" % _name(kind))
        fields = saved_fields(kind)
        return {
            "object": _name(kind),
            "id": number,
            "fields": {field: self.value(getattr(value, field)) for field in fields if hasattr(value, field)},
        }

    def buffer(self, buffer: defaultdict[int, Row]) -> str:
        number, known = self.freezer.buffer_id(buffer)
        if number in self.buffers or number in self.removed:
            return number
        frozen = self.freezer.rows_frozen
        if not known or self.changes is None:
            self.buffers[number] = [self.row(index, row) for index, row in sorted(buffer.items())]
            self.whole.append(number)
            frozen[number] = set(buffer)
            return number
        written = self.changes.get(id(buffer))
        if written is None:
            return number
        had = frozen[number]
        now = set(buffer)
        self.buffers[number] = [self.row(index, buffer[index]) for index in sorted(set(written) & now)]
        self.removed[number] = sorted(had - now)
        frozen[number] = now
        return number

    def appearance(self, appearance: Appearance) -> int:
        index_of = self.freezer.appearance_index
        index = index_of.get(id(appearance))
        if index is None:
            index = index_of[id(appearance)] = len(index_of)
            self.freezer.held.append(appearance)
            self.appearances.append([self.value(appearance.rendition), appearance.hyperlink, appearance.hyperlink_id])
        return index

    def row(self, number: int, row: Row) -> FrozenRow:
        cells = []
        for column, cell in row.items():
            kind = _KINDS.get(type(cell))
            if kind is None:
                if type(cell) is not ProtectedCell:
                    raise TypeError("cannot freeze a cell of kind %s" % _name(type(cell)))
                kind = PROTECTED + cell.protection  # type: ignore[attr-defined]
            cells.append([column, cell.char, self.appearance(cell.appearance), kind])
        return [number, row.wrapped, cells]


def thaw(frozen: Frozen, into: object) -> None:
    """
    Write a frozen object's fields into `into`, an object of its class.

    `into` is built by its owner, so what the class does not save -- the
    callbacks, the caches, what the embedder sets -- is already there.
    What derives from saved fields, an object rebuilds in its own
    `after_thaw`, which runs once its fields are written.
    """
    _Thawer(frozen).fields(frozen.root, into)


class _Thawer:
    def __init__(self, frozen: Frozen) -> None:
        self.frozen = frozen
        self.made: dict[int, object] = {}
        self.made_buffers: dict[str, defaultdict[int, Row]] = {}
        self.appearances = [self.appearance(*entry) for entry in frozen.appearances]
        # One erased blank per appearance, the way a screen's erase makes one per call.
        self.erased: dict[int, ErasedCell] = {}

    def appearance(self, rendition: Any, hyperlink: str, hyperlink_id: str) -> Appearance:
        return appearance_of[self.value(rendition), hyperlink, hyperlink_id]

    def fields(self, entry: dict, into: object) -> None:
        if _name(type(into)) != entry["object"]:
            raise TypeError("a frozen %s cannot thaw into a %s" % (entry["object"], _name(type(into))))
        self.made[entry["id"]] = into
        for field, value in entry["fields"].items():
            current = getattr(into, field, None)
            if isinstance(value, dict) and "object" in value and _name(type(current)) == value["object"]:
                # The owner built this part too; fill it rather than replace it.
                self.fields(value, current)
            else:
                setattr(into, field, self.value(value))
        after_thaw = getattr(into, "after_thaw", None)
        if after_thaw is not None:
            after_thaw()

    def value(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "ref" in value:
            return self.made[value["ref"]]
        if "enum" in value:
            return _class(value["enum"])(value["value"])
        if "namedtuple" in value:
            return _class(value["namedtuple"])(*[self.value(item) for item in value["fields"]])
        if "tuple" in value:
            return tuple(self.value(item) for item in value["tuple"])
        if "bytes" in value:
            return bytes.fromhex(value["bytes"])
        if "buffer" in value:
            made = self.made_buffers.get(value["buffer"])
            if made is not None:
                return made
            buffer: defaultdict[int, Row] = defaultdict(Row)
            self.made_buffers[value["buffer"]] = buffer
            for number, wrapped, cells in self.frozen.buffers.get(value["buffer"], ()):
                buffer[number] = self.row(wrapped, cells)
            return buffer
        if "list" in value:
            items: list = []
            self.made[value["id"]] = items
            items.extend(self.value(item) for item in value["list"])
            return items
        if "set" in value or "frozenset" in value:
            kind = set if "set" in value else frozenset
            made = kind(self.value(item) for item in value[kind.__name__])
            self.made[value["id"]] = made
            return made
        if "dict" in value:
            mapping: dict = {}
            self.made[value["id"]] = mapping
            for key, item in value["dict"]:
                mapping[self.value(key)] = self.value(item)
            return mapping
        if "object" in value:
            made_object = _class(value["object"])()
            self.fields(value, made_object)
            return made_object
        raise ValueError("a frozen value of no known shape: %r" % (value,))

    def row(self, wrapped: bool, cells: list) -> Row:
        row = Row()
        row.wrapped = wrapped
        appearances = self.appearances
        for column, char, index, kind in cells:
            appearance = appearances[index]
            if kind == WRITTEN:
                cell = _CHAR_CACHE[char, appearance]
            elif kind == ERASED:
                cell = self.erased.get(index)
                if cell is None:
                    cell = self.erased[index] = ErasedCell(char, appearance)
                elif cell.char != char:
                    cell = ErasedCell(char, appearance)
            elif kind == PLAIN:
                cell = UNWRITTEN if char == " " and appearance is PLAIN_APPEARANCE else Cell(char, appearance)
            else:
                cell = _PROTECTED_CHAR_CACHE[char, appearance, kind - PROTECTED]
            row[column] = cell
        return row
