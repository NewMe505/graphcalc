"""Persisted store for calculator variables, functions and "ans" (plan step
P7/S1; "ans" added by P26/S1, Bug #14 fix; srepr-backed robust storage for
variables and functions added by P26/S2, Bug #14 fix).

CalcState holds the dicts graphcalc.cli attaches to each HTTPServer instance:
"variables" (name -> {"exact": str, "srepr": str | None}), "functions"
(name -> {"params": [...], "body": str, "body_srepr": str | None}), the
latter defaulting to {} so a state file written before functions existed
still loads cleanly, and "ans" (the last plain evaluation's {"exact": str,
"srepr": str}, or absent/None when there is none yet).

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

There is no `--state` CLI flag yet, and no default on-disk path -- a caller
must pass one explicitly. That wiring, together with lists and history,
belongs to a later feature (P9, disk-backed state for the whole product).
"""

import json
import os
import tempfile


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
        }
        if path is not None and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            self._data["variables"] = dict(loaded.get("variables", {}))
            self._data["functions"] = dict(loaded.get("functions", {}))
            # Absent for a state file written before P26/S2 (or a hand-edited
            # one) -- every name then simply has no srepr, the same as a
            # name stored this session with srepr=None (see set_variable/
            # set_function below), so variable_entries()/function_entries()
            # fall back to the pre-P26/S2 plain-exact rebuild for it.
            self._data["variable_sreprs"] = dict(loaded.get("variable_sreprs", {}))
            self._data["function_sreprs"] = dict(loaded.get("function_sreprs", {}))
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
