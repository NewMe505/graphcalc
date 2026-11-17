"""Regression tests for Bug #14 (plan step P26/S2): a stored variable or
function must never break a later, unrelated evaluation -- in the same
process, and after a reload from disk.

Bug #14's root cause: before P26, a stored variable's value (or a function's
body) was rebuilt for *every* evaluate() call by plain `sympify()` of its
`exact`/"**"-notation string -- sympy's own full namespace, not this
calculator's restricted whitelist (`graphcalc.calc._rad_names()`). A name
this calculator deliberately never whitelists -- "beta", "gamma", "zeta",
"S", "N", "Q" -- is a real sympy function/singleton in that namespace, not
just a free `Symbol`, so re-`sympify()`-ing a stored value such as
`"beta + 1"` could raise (`TypeError: unsupported operand type(s) for +:
'FunctionClass' and 'One'`) -- and because the old rebuild ran
unconditionally, that raise broke *any* later expression, even one that
never mentioned the stored name at all, such as a plain `"1+1"`.

The fix (`graphcalc.state.CalcState.set_variable`/`set_function`,
`graphcalc.calc._rebuild_stored_value`/`_function_locals`/
`_referenced_names`) has two parts:
  1. Storage format: alongside the plain `exact`/`body` string, CalcState
     also persists that value's sympy `srepr()` ("variable_sreprs"/
     "function_sreprs" in the on-disk JSON). `srepr()`'s `Symbol('beta')` is
     a quoted string literal argument to a constructor, never a bare name
     `sympify()` could resolve against its own namespace -- so rebuilding
     from `srepr` via `sympify(srepr_string)` always reconstructs the exact
     original object regardless of what the name would otherwise mean bare.
  2. Laziness: `calc.evaluate` only ever attempts to rebuild a stored name
     (variable, function, or "ans") when the expression actually references
     that name as a whole token (`calc._referenced_names`). A definition
     that cannot be rebuilt -- stored before this fix, with no srepr, or
     hand-edited on disk -- can therefore only break an expression that
     actually uses it; "1+1" is never affected by any stored "a", "f" or
     "g", no matter how badly any of them is stored.

F2 (PRODUCT.md, [failing] before this fix): after
`{"expr":"a:=beta+1"}` or `{"expr":"f(x):=beta(x)"}`, `{"expr":"1+1"}`
returns 200 with exact "2". Note what F2 does and does not require: it never
requires `"f(x):=beta(x)"` itself to succeed. "beta" is not a whitelisted
callable (`graphcalc.calc._rad_names()` has no "beta" entry, by the same
P24/S3 design that also rejects `"zeta(2)"` -- see tests/test_p24_names.py),
so `calc.evaluate`'s `called_names` check (P24/S3, Bug #7 fix) rejects
`"beta(x)"` with 400 `"unknown function 'beta'"` before anything is stored;
widening that whitelist to accept "beta" as callable would itself be P24/S3
drift, so this file does not do that. What F2 actually needs -- and what
this file checks -- is that attempting (and failing) that definition leaves
state untouched, so "1+1" right after it is still exactly "2". A function
body that references "beta" *without* calling it (`"g(x):=beta*x"`) stores
fine, the same way `"a:=beta+1"` does, and exercises the same srepr-rebuild
machinery for `graphcalc.calc._function_locals` that variables exercise for
`graphcalc.calc._rebuild_stored_value` -- used here to also prove "a stored
definition... reloads correctly", not just "...does not break an unrelated
evaluation".

Note for the next session: the plan step's file list names
`graphcalc/evaluator.py`; no such module exists in this repo. The logic it
describes -- `evaluate()`, `parse_definition()`, `parse_function_
definition()` -- lives in `graphcalc/calc.py`, confirmed by direct reading.
"""

import json
import threading
import urllib.error
import urllib.request

from graphcalc.cli import build_server
from graphcalc.state import CalcState


def _post(base, path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def _start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


def _stop(server):
    server.shutdown()
    server.server_close()


# ---- F2, same process: a stored "beta" definition never breaks "1+1" ----


def test_variable_referencing_beta_does_not_break_later_evaluation():
    srv = build_server(0)
    base = _start(srv)
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=beta+1"})
        assert status == 200, body
        assert body["exact"] == "beta + 1", body

        # The regression this guards against: a plain, unrelated expression
        # right after storing "a" must not be broken by "a"'s own rebuild.
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body

        # "a" itself must still recall the exact value it was defined with.
        status, body = _post(base, "/api/calc/evaluate", {"expr": "a"})
        assert status == 200, body
        assert body["exact"] == "beta + 1", body
    finally:
        _stop(srv)


def test_function_definition_calling_unwhitelisted_name_never_breaks_later_evaluation():
    srv = build_server(0)
    base = _start(srv)
    try:
        # "beta" is not a whitelisted callable (same design as "zeta(2)" in
        # tests/test_p24_names.py) -- this may 200 or 400, but never 500, and
        # never leaves state in a shape that breaks the next request.
        status, body = _post(base, "/api/calc/evaluate", {"expr": "f(x):=beta(x)"})
        assert status in (200, 400), body
        if status == 400:
            assert isinstance(body.get("error"), str), body

        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body
    finally:
        _stop(srv)


def test_function_body_referencing_beta_stores_and_evaluates():
    # Unlike "beta(x)" above, a bare (uncalled) "beta" inside a function body
    # is exactly the same kind of value a stored variable can hold, so this
    # must succeed and exercise calc._function_locals' own srepr rebuild.
    srv = build_server(0)
    base = _start(srv)
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "g(x):=beta*x"})
        assert status == 200, body
        assert body["exact"] == "beta*x", body

        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body

        status, body = _post(base, "/api/calc/evaluate", {"expr": "g(2)"})
        assert status == 200, body
        assert body["exact"] == "2*beta", body
    finally:
        _stop(srv)


# ---- F2, after a reload from disk: same guarantees, new CalcState/server ----


def test_variable_and_function_with_beta_survive_reload_from_disk(tmp_path):
    """Standing in for a process restart with the same --state path -- see
    test_calc_definitions.py's
    test_variable_survives_server_restart_on_same_state_file for the same
    pattern (and tests/test_p9_state_persistence.py::
    test_p9_restart_persists_variable for the same check through the real
    CLI subprocess and --state flag). Without "variable_sreprs"/
    "function_sreprs" surviving the round
    trip to disk, the reloaded server would fall back to plain sympify() of
    "beta + 1"/"beta*x", which raises, turning "a" and "g(2)" into 400s --
    this is the test that actually catches a missing srepr on disk."""
    path = str(tmp_path / "state.json")

    srv1 = build_server(0, state=CalcState(path))
    base1 = _start(srv1)
    try:
        status, body = _post(base1, "/api/calc/evaluate", {"expr": "a:=beta+1"})
        assert status == 200, body
        status, body = _post(base1, "/api/calc/evaluate", {"expr": "g(x):=beta*x"})
        assert status == 200, body
        # Attempted but never stored -- see test_function_definition_calling_
        # unwhitelisted_name_never_breaks_later_evaluation above.
        _post(base1, "/api/calc/evaluate", {"expr": "f(x):=beta(x)"})

        status, body = _post(base1, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body
    finally:
        _stop(srv1)

    srv2 = build_server(0, state=CalcState(path))
    base2 = _start(srv2)
    try:
        status, body = _post(base2, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body

        status, body = _post(base2, "/api/calc/evaluate", {"expr": "a"})
        assert status == 200, body
        assert body["exact"] == "beta + 1", body

        status, body = _post(base2, "/api/calc/evaluate", {"expr": "g(2)"})
        assert status == 200, body
        assert body["exact"] == "2*beta", body
    finally:
        _stop(srv2)


# ---- An old-format (pre-P26/S2) or hand-edited state file: no srepr at all ----


def test_old_format_state_file_without_sreprs_never_breaks_unrelated_evaluation(tmp_path):
    """A state file written before P26/S2 (or hand-edited) has "variables"/
    "functions" but no "variable_sreprs"/"function_sreprs" keys at all --
    CalcState.variable_entries()/function_entries() then hand back srepr=None
    for every name, so calc.evaluate falls back to the old, unsafe plain
    sympify() rebuild for a name that is actually referenced. That fallback
    can fail for a value such as "beta + 1" (sympify's own namespace binds
    bare "beta" to the real Euler Beta function, and `FunctionClass + One`
    raises `TypeError`) -- the failure must stay local to a request that
    references "a"/"g" (-> 400, never 500), and must never affect "1+1"."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "variables": {"a": "beta + 1"},
                "functions": {"g": {"params": ["x"], "body": "beta*x"}},
            }
        ),
        encoding="utf-8",
    )

    srv = build_server(0, state=CalcState(str(path)))
    base = _start(srv)
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body

        status, body = _post(base, "/api/calc/evaluate", {"expr": "a"})
        assert status == 400, body
        assert isinstance(body.get("error"), str), body

        status, body = _post(base, "/api/calc/evaluate", {"expr": "g(2)"})
        assert status == 400, body
        assert isinstance(body.get("error"), str), body
    finally:
        _stop(srv)
