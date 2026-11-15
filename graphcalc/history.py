"""The calculator's evaluation history: an interface plus two stores.

HistoryStore is the only thing graphcalc/cli.py depends on; it never reaches
into a concrete implementation. InMemoryHistoryStore (a plain list, lost when
the process exits) is unchanged since before this feature.
StateBackedHistoryStore (plan step P9/S1) is the disk-backed implementation:
it holds no state of its own, deferring entirely to a graphcalc.state.
CalcState's own "history" list, so history is written to the same JSON file
as variables/functions/lists, through that CalcState's existing atomic
_save. Wiring either store onto a server (--state vs. --in-memory) is a
later step of this same feature, P9; graphcalc/cli.py does not change here.
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


class StateBackedHistoryStore(HistoryStore):
    """A HistoryStore backed by a graphcalc.state.CalcState (plan step
    P9/S1), so history survives a restart on the same --state path.

    Holds no list of its own: every method just delegates to `state`'s own
    history()/append_history()/clear_history(), so every append and clear
    goes through CalcState's existing atomic _save (a temp file in the same
    directory, then os.replace) -- the same guarantee variables and
    functions already have, extended to history without a second code path
    that could fall out of sync with it or write the file non-atomically.
    """

    def __init__(self, state):
        self._state = state

    def append(self, entry: dict) -> None:
        self._state.append_history(entry)

    def entries(self) -> list:
        return self._state.history()

    def last(self) -> dict | None:
        entries = self._state.history()
        return entries[-1] if entries else None

    def clear(self) -> None:
        self._state.clear_history()
