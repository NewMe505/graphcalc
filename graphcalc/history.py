"""The calculator's evaluation history: an interface plus an in-memory store.

HistoryStore is the only thing graphcalc/cli.py depends on; it never reaches
into a concrete implementation. InMemoryHistoryStore (a plain list, lost when
the process exits) is the only implementation today. A later feature (P9,
disk-backed state) can add a store that persists through a JSON file behind
this same interface without graphcalc/cli.py changing at all.
"""

from abc import ABC, abstractmethod


class HistoryStore(ABC):
    """An append-only log of successful evaluations, oldest entry first."""

    @abstractmethod
    def append(self, entry: dict) -> None:
        """Add `entry` as the newest item in the history."""

    @abstractmethod
    def entries(self) -> list:
        """Return every entry, oldest first.

        Each call returns a fresh list/dicts; mutating the result must never
        affect the store.
        """

    @abstractmethod
    def last(self) -> dict | None:
        """Return the most recently appended entry, or None if there is none."""

    @abstractmethod
    def clear(self) -> None:
        """Remove every entry."""


class InMemoryHistoryStore(HistoryStore):
    """A HistoryStore backed by a plain list; nothing survives a restart."""

    def __init__(self):
        self._entries: list = []

    def append(self, entry: dict) -> None:
        self._entries.append(dict(entry))

    def entries(self) -> list:
        return [dict(entry) for entry in self._entries]

    def last(self) -> dict | None:
        return dict(self._entries[-1]) if self._entries else None

    def clear(self) -> None:
        self._entries.clear()
