"""Persisted store for calculator variables and functions (plan step P7/S1).

CalcState holds the dicts graphcalc.cli attaches to each HTTPServer instance:
"variables" (name -> exact value string) and "functions" (name -> {"params":
[...], "body": str}), the latter defaulting to {} so a state file written
before functions existed still loads cleanly.

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


class CalcState:
    """In-memory variables/functions, optionally mirrored to a JSON file."""

    def __init__(self, path: str | None = None):
        self._path = path
        self._data = {"variables": {}, "functions": {}}
        if path is not None and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            self._data["variables"] = dict(loaded.get("variables", {}))
            self._data["functions"] = dict(loaded.get("functions", {}))

    def variables(self) -> dict:
        """Return a fresh copy of the name -> exact-value-string mapping."""
        return dict(self._data["variables"])

    def functions(self) -> dict:
        """Return a fresh copy of the name -> {"params", "body"} mapping."""
        return dict(self._data["functions"])

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
