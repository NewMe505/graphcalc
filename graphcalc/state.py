"""Persisted store for calculator variables, functions, "ans", history and
lists (plan step P7/S1; "ans" added by P26/S1, Bug #14 fix; srepr-backed
robust storage for variables and functions added by P26/S2, Bug #14 fix;
"history" and "lists" unified into this single store by plan step P9/S1).

CalcState holds the dicts graphcalc.cli attaches to each HTTPServer instance:
"variables" (name -> {"exact": str, "srepr": str | None}), "functions"
(name -> {"params": [...], "body": str, "body_srepr": str | None}), the
latter defaulting to {} so a state file written before functions existed
still loads cleanly, "ans" (the last plain evaluation's {"exact": str,
"srepr": str}, or absent/None when there is none yet), "history" (a plain
list of the same {"expr", "exact", "decimal"} entries graphcalc.history.
HistoryStore holds, oldest first -- see StateBackedHistoryStore in
graphcalc/history.py, the HistoryStore implementation that reads and writes
this list so a single JSON file backs both), and "lists" (name -> values,
empty until a later feature, P15, adds CRUD for it -- kept here now so the
on-disk shape, and POST /api/state/reset, do not have to change again then).

"srepr" (and "body_srepr") is None for an entry stored by a version of this
calculator before P26/S2, or loaded from a hand-edited file -- graphcalc.
calc.evaluate then falls back to the pre-P26/S2 rebuild (plain sympify() of
"exact"/"body"), still fine for most values but, for one built from a name
this calculator does not whitelist (e.g. "beta", "gamma", "zeta", "S", "N",
"Q"), possibly unrebuildable. That is never fatal to an unrelated
evaluation: graphcalc.calc.evaluate only ever attempts the rebuild for a
name an expression actually references (plan step P26/S2), so "1+1" is
never broken by an unrebuildable "a", no matter how "a" was stored.

With no path, CalcState is purely in-memory and never touches disk -- this
is what graphcalc.cli.build_server(port) uses by default, and what the
`--in-memory` acceptance run relies on to create no file. With a path, it
loads that file's JSON on construction (if the file exists) and writes
through atomically (a temp file in the same directory, then os.replace)
after every change, so a new CalcState built later on the same path picks
up where the previous one left off.

Loading is never allowed to raise (plan step P9/S1, Bug #14 fix): a missing
file leaves every field at its empty default (unchanged from before); a
file that exists but fails to parse as JSON, or whose top level is not a
JSON object, is treated the same as an empty "{}"; and any individual field
of the wrong JSON type (e.g. "variables" stored as a string or a list
instead of an object) falls back to that field's own empty default via
_coerce_dict/_coerce_list below, rather than raising while reading it.
Nothing in __init__ touches disk -- a load failure never triggers a write,
so a corrupt file on disk is left exactly as it was found until the next
actual change calls _save() and overwrites it with a valid one.

`--state PATH` (default "./graphcalc_state.json") and `--in-memory` are
wired up in graphcalc/cli.py's main()/serve() (plan step P9/S2): `--state`
builds a CalcState on that path (and a StateBackedHistoryStore on top of
it); `--in-memory` passes no path at all (and plugs in a plain
InMemoryHistoryStore instead), so nothing touches disk. POST
/api/state/reset (graphcalc/cli.py's _handle_state_reset, plan step P9/S3)
calls reset() below for exactly this one-atomic-write guarantee, then also
clears the history store. The repository's .gitignore lists
graphcalc_state.json so a developer's local state file is never committed.
"""

import json
import os
import tempfile


def _coerce_dict(value) -> dict:
    """Return a fresh dict copy of `value`, or {} if it is not a dict.

    Used for every dict-shaped field read back from a loaded state file
    (plan step P9/S1, Bug #14 fix) so a wrong-shape value for just one key
    (e.g. "variables" hand-edited into a string or a list) falls back to
    that key's own empty default instead of raising -- dict() of a
    non-mapping, non-pairs value (e.g. dict("oops")) can itself raise,
    which this guards against.
    """
    return dict(value) if isinstance(value, dict) else {}


def _coerce_list(value) -> list:
    """Return a fresh list copy of `value`, or [] if it is not a list.

    The list-shaped counterpart to _coerce_dict above, used for "history"
    (plan step P9/S1).
    """
    return list(value) if isinstance(value, list) else []


def _is_valid_ans(value) -> bool:
    """True if `value` is a well-formed stored "ans": {"exact": str, "srepr": str}.

    A missing "ans" key, a non-dict value, or a dict missing either string
    field (e.g. an old state file written before this feature existed, or a
    hand-edited file) must never crash a load -- it is simply treated as no
    stored answer at all (plan step P26/S1, Bug #14 fix).
    """
    return (
        isinstance(value, dict)
        and isinstance(value.get("exact"), str)
        and isinstance(value.get("srepr"), str)
    )


class CalcState:
    """In-memory variables/functions/ans, optionally mirrored to a JSON file."""

    def __init__(self, path: str | None = None):
        self._path = path
        self._data = {
            "variables": {},
            "functions": {},
            "variable_sreprs": {},
            "function_sreprs": {},
            "history": [],
            "lists": {},
        }
        if path is not None and os.path.exists(path):
            loaded = {}
            try:
                with open(path, encoding="utf-8") as fh:
                    loaded = json.load(fh)
            except (OSError, ValueError):
                # Missing-by-the-time-we-open-it, unreadable, or not valid
                # JSON at all (json.JSONDecodeError is a ValueError) -- an
                # empty "{}" below, same as a state file that simply does
                # not exist yet (plan step P9/S1, Bug #14 fix).
                loaded = {}
            if not isinstance(loaded, dict):
                # Valid JSON, but the top level is not an object (e.g. a
                # hand-edited file holding a bare list or string) -- same
                # fallback as above (plan step P9/S1, Bug #14 fix).
                loaded = {}
            self._data["variables"] = _coerce_dict(loaded.get("variables"))
            self._data["functions"] = _coerce_dict(loaded.get("functions"))
            # Absent for a state file written before P26/S2 (or a hand-edited
            # one) -- every name then simply has no srepr, the same as a
            # name stored this session with srepr=None (see set_variable/
            # set_function below), so variable_entries()/function_entries()
            # fall back to the pre-P26/S2 plain-exact rebuild for it.
            self._data["variable_sreprs"] = _coerce_dict(loaded.get("variable_sreprs"))
            self._data["function_sreprs"] = _coerce_dict(loaded.get("function_sreprs"))
            # Absent for a state file written before P9/S1 -- every name
            # then simply has no history/lists yet, the same defaulting
            # pattern as variable_sreprs/function_sreprs above.
            self._data["history"] = _coerce_list(loaded.get("history"))
            self._data["lists"] = _coerce_dict(loaded.get("lists"))
            stored_ans = loaded.get("ans")
            if _is_valid_ans(stored_ans):
                self._data["ans"] = dict(stored_ans)

    def variables(self) -> dict:
        """Return a fresh copy of the name -> exact-value-string mapping.

        Public shape, unchanged by P26/S2: plain str, never the {"exact",
        "srepr"} dict graphcalc.calc.evaluate's `variables` wants -- that is
        variable_entries() below. graphcalc.cli._handle_calc_vars_get (GET
        /api/calc/vars) reads this one directly.
        """
        return dict(self._data["variables"])

    def functions(self) -> dict:
        """Return a fresh copy of the name -> {"params", "body"} mapping.

        Public shape, unchanged by P26/S2: no "body_srepr" key -- that is
        function_entries() below. graphcalc.cli._handle_calc_vars_get (GET
        /api/calc/vars) reads this one directly.
        """
        return dict(self._data["functions"])

    def variable_entries(self) -> dict:
        """Return name -> {"exact": str, "srepr": str | None} (plan step
        P26/S2, Bug #14 fix): the shape graphcalc.calc.evaluate's
        `variables` parameter, and its _rebuild_stored_value helper, read.

        `srepr` is None for a name stored before this fix, or loaded from a
        state file written before this fix (or hand-edited) -- evaluate()
        then falls back to its own pre-fix plain-sympify() rebuild for that
        one name, same as always; a name stored or reloaded with a real
        srepr rebuilds through that srepr instead, safe regardless of what
        the name would otherwise mean bare (e.g. "beta", a real sympy
        function, not just a free symbol, in sympy's own namespace).
        """
        sreprs = self._data["variable_sreprs"]
        return {
            name: {"exact": exact, "srepr": sreprs.get(name)}
            for name, exact in self._data["variables"].items()
        }

    def function_entries(self) -> dict:
        """Return name -> {"params": [...], "body": str, "body_srepr": str |
        None} (plan step P26/S2, Bug #14 fix): the shape graphcalc.calc.
        evaluate's `functions` parameter, and its _function_locals helper,
        read. See variable_entries() above for why "body_srepr" can be None
        and why that is never fatal.
        """
        sreprs = self._data["function_sreprs"]
        return {
            name: {**spec, "body_srepr": sreprs.get(name)}
            for name, spec in self._data["functions"].items()
        }

    def ans(self) -> dict | None:
        """Return a fresh copy of the last plain evaluation's answer, or None.

        None whenever no plain evaluation has ever succeeded on this store
        (including right after loading a file with no "ans" key, or a
        malformed one -- see _is_valid_ans). Otherwise {"exact": str,
        "srepr": str}: `exact` is the exact string that evaluation
        returned; `srepr` is the result's sympy srepr(), the only form
        graphcalc.calc.evaluate reads back (via plain sympify(), sympy's
        own full namespace) to safely rebuild "ans" for a later expression
        that references it -- never str(), which is ambiguous for a name
        this calculator does not whitelist (e.g. "beta", "gamma", "zeta",
        "S", "N", "Q": each is a real sympy function/singleton name, not
        just a free symbol, in sympy's own namespace).
        """
        stored = self._data.get("ans")
        return dict(stored) if stored is not None else None

    def set_variable(self, name: str, exact: str, srepr: str | None = None) -> None:
        """Store `exact` under `name`, then save to disk if a path is set.

        `srepr` -- sympy's srepr() of the same value, or None -- is stored
        alongside `exact` in a separate map (plan step P26/S2, Bug #14 fix)
        so variable_entries() can hand graphcalc.calc.evaluate a value that
        rebuilds correctly regardless of what `name`'s *other* stored value
        would otherwise mean bare (e.g. "beta", a real sympy function, not
        just a free symbol, in sympy's own namespace). `variables()`'s own
        public shape -- plain str -- is unchanged by this; `srepr` is never
        visible there, only through variable_entries().
        """
        self._data["variables"][name] = exact
        self._data["variable_sreprs"][name] = srepr
        self._save()

    def set_function(self, name: str, params: list, body: str, body_srepr: str | None = None) -> None:
        """Store {"params": params, "body": body} under `name` (plan step P7/S2).

        `body` is the plain sympy str() of the definition's right-hand side
        (e.g. "x**2 + 1") -- the same "**" notation graphcalc.calc.evaluate
        always returns and graphcalc.calc._function_locals re-sympify()s on
        every call, never the "^" caret form an API response shows. Saves to
        disk the same way set_variable does.

        `body_srepr` -- sympy's srepr() of the same body, or None -- is
        stored alongside `body` in a separate map (plan step P26/S2, Bug #14
        fix), the same way set_variable stores `srepr`; see its docstring
        for why. `functions()`'s own public shape is unchanged by this;
        `body_srepr` is never visible there, only through function_entries().
        """
        self._data["functions"][name] = {"params": list(params), "body": body}
        self._data["function_sreprs"][name] = body_srepr
        self._save()

    def set_ans(self, exact: str, srepr: str) -> None:
        """Store {"exact": exact, "srepr": srepr} as the last plain
        evaluation's answer, then save to disk if a path is set (plan step
        P26/S1, Bug #14 fix). Only graphcalc.cli's plain-evaluate path
        calls this -- never a "name:=expr" or "f(x):=expr" definition's own
        right-hand-side evaluation -- so "ans" only ever recalls a plain
        evaluation's result, the same rule the history store already
        followed.
        """
        self._data["ans"] = {"exact": exact, "srepr": srepr}
        self._save()

    def clear_ans(self) -> None:
        """Forget the stored answer, then save to disk if a path is set.

        Called alongside clearing the history store (DELETE
        /api/calc/history) so "ans" goes back to undefined at the same
        time the history it was recalling from does.
        """
        self._data.pop("ans", None)
        self._save()

    def history(self) -> list:
        """Return a fresh copy of the evaluation history, oldest entry first
        (plan step P9/S1).

        Each entry is a fresh dict too, so mutating the result never affects
        the store -- the same contract graphcalc.history.HistoryStore.
        entries() documents. graphcalc.history.StateBackedHistoryStore reads
        this to implement that interface on top of CalcState, so history
        lives in the same JSON file as variables/functions/lists.
        """
        return [dict(entry) for entry in self._data["history"]]

    def append_history(self, entry: dict) -> None:
        """Append a fresh copy of `entry` to the history, then save to disk
        if a path is set (plan step P9/S1).
        """
        self._data["history"].append(dict(entry))
        self._save()

    def clear_history(self) -> None:
        """Remove every history entry, then save to disk if a path is set
        (plan step P9/S1).

        Called by graphcalc.history.StateBackedHistoryStore.clear(), the
        same way DELETE /api/calc/history already clears an
        InMemoryHistoryStore -- and, same as before, left to the caller to
        pair with clear_ans() if "ans" should also go back to undefined.
        """
        self._data["history"] = []
        self._save()

    def lists(self) -> dict:
        """Return a fresh copy of the named-lists store (plan step P9/S1).

        Empty until a later feature (P15) adds CRUD for named lists; kept
        here now, and included in reset() below, so the on-disk shape (and
        POST /api/state/reset) will not need to change again then.
        """
        return dict(self._data["lists"])

    def reset(self) -> None:
        """Empty variables, functions, lists, history and ans in one go,
        then save to disk once (plan step P9/S1).

        Backs POST /api/state/reset (CLI/route wiring is a later step of
        this same feature, P9): a single _save() call here, rather than one
        per field, so a reset is one atomic write, never a sequence of
        partial ones.
        """
        self._data["variables"] = {}
        self._data["functions"] = {}
        self._data["variable_sreprs"] = {}
        self._data["function_sreprs"] = {}
        self._data["lists"] = {}
        self._data["history"] = []
        self._data.pop("ans", None)
        self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        directory = os.path.dirname(self._path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".calcstate-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
