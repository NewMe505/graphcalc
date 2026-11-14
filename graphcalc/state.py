"""Persisted store for calculator variables, functions and "ans" (plan step
P7/S1; "ans" added by P26/S1, Bug #14 fix).

CalcState holds the dicts graphcalc.cli attaches to each HTTPServer instance:
"variables" (name -> exact value string), "functions" (name -> {"params":
[...], "body": str}), the latter defaulting to {} so a state file written
before functions existed still loads cleanly, and "ans" (the last plain
evaluation's {"exact": str, "srepr": str}, or absent/None when there is
none yet).

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
        self._data = {"variables": {}, "functions": {}}
        if path is not None and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            self._data["variables"] = dict(loaded.get("variables", {}))
            self._data["functions"] = dict(loaded.get("functions", {}))
            stored_ans = loaded.get("ans")
            if _is_valid_ans(stored_ans):
                self._data["ans"] = dict(stored_ans)

    def variables(self) -> dict:
        """Return a fresh copy of the name -> exact-value-string mapping."""
        return dict(self._data["variables"])

    def functions(self) -> dict:
        """Return a fresh copy of the name -> {"params", "body"} mapping."""
        return dict(self._data["functions"])

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

    def set_variable(self, name: str, exact: str) -> None:
        """Store `exact` under `name`, then save to disk if a path is set."""
        self._data["variables"][name] = exact
        self._save()

    def set_function(self, name: str, params: list, body: str) -> None:
        """Store {"params": params, "body": body} under `name` (plan step P7/S2).

        `body` is the plain sympy str() of the definition's right-hand side
        (e.g. "x**2 + 1") -- the same "**" notation graphcalc.calc.evaluate
        always returns and graphcalc.calc._function_locals re-sympify()s on
        every call, never the "^" caret form an API response shows. Saves to
        disk the same way set_variable does.
        """
        self._data["functions"][name] = {"params": list(params), "body": body}
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
