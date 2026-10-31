"""Tests for variable definitions ("name:=expr"), plan step P7/S1.

graphcalc.calc.parse_definition detects a bare "name:=expr" assignment
before normal sympy parsing ("f(x):=expr" function definitions are a
separate, later step, and deliberately do not match here). graphcalc.cli's
_handle_calc_evaluate evaluates the right-hand side the normal way (so it
already sees previously stored variables), rejects a reserved name via
graphcalc.names.check_not_constant (-> 400 "cannot redefine constant
<name>"), and on success stores the exact result under name in a
graphcalc.state.CalcState held on the HTTPServer instance -- separate from
the history store. graphcalc.calc.evaluate accepts that store's
variables() dict and binds each name to its sympified value in local_dict,
so e.g. "2a+1" substitutes "a" the same way "pi" or "ans" already do.

CalcState is in-memory only when built with no path (what build_server(port)
uses by default, and what the --in-memory run relies on to create no file);
given a path, it loads that file's JSON (defaulting a missing "functions"
key to {}, so a state file written before functions existed still loads)
and writes through atomically after every change, so a new CalcState built
later on the same path picks up where the previous one left off.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from graphcalc import calc
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


@pytest.fixture
def server():
    """A fresh server with the default (in-memory, no path) CalcState."""
    srv = build_server(0)
    base = _start(srv)
    try:
        yield srv, base
    finally:
        _stop(srv)


# ---- unit tests: calc.parse_definition and calc.evaluate(variables=...) ----


def test_parse_definition_matches_bare_assignment():
    assert calc.parse_definition("a:=5") == ("a", "5")
    assert calc.parse_definition(" a := 2+3 ") == ("a", "2+3")


def test_parse_definition_rejects_function_syntax_and_plain_expr():
    # "f(x):=expr" is a function definition -- a separate, later step.
    assert calc.parse_definition("f(x):=x^2+1") is None
    assert calc.parse_definition("2+3") is None
    assert calc.parse_definition("a==5") is None


def test_evaluate_substitutes_stored_variables():
    result = calc.evaluate("2a+1", variables={"a": "5"})
    assert result["exact"] == "11"
    assert result["domain_error"] is None


# ---- HTTP: a:=5 then 2a+1, through the default (no state arg) server ----


def test_define_variable_returns_exact_value(server):
    _srv, base = server
    status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
    assert status == 200
    assert body["exact"] == "5"
    assert body["expr"] == "a:=5"


def test_defined_variable_usable_in_later_expression(server):
    _srv, base = server
    status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
    assert status == 200
    assert body["exact"] == "5"

    status, body = _post(base, "/api/calc/evaluate", {"expr": "2a+1"})
    assert status == 200
    assert body["exact"] == "11"


def test_defining_function_body_variable_depends_on_prior_definition(server):
    _srv, base = server
    _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
    status, body = _post(base, "/api/calc/evaluate", {"expr": "b:=a+1"})
    assert status == 200
    assert body["exact"] == "6"

    status, body = _post(base, "/api/calc/evaluate", {"expr": "a+b"})
    assert status == 200
    assert body["exact"] == "11"


# ---- redefining a reserved constant is rejected ----


def test_redefining_pi_is_rejected(server):
    _srv, base = server
    status, body = _post(base, "/api/calc/evaluate", {"expr": "pi:=3"})
    assert status == 400
    assert body == {"error": "cannot redefine constant pi"}

    # pi itself must still mean the real constant afterwards.
    status, body = _post(base, "/api/calc/evaluate", {"expr": "2pi"})
    assert status == 200
    assert body["exact"] == "2*pi"


# ---- a domain error on the right-hand side stores nothing ----


def test_defining_with_domain_error_does_not_store(server):
    _srv, base = server
    status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=1/0"})
    assert status == 200
    assert body["exact"] is None
    assert body["domain_error"] is not None

    # "a" was never stored, so it remains a free symbol.
    status, body = _post(base, "/api/calc/evaluate", {"expr": "a"})
    assert status == 200
    assert body["exact"] == "a"


# ---- CalcState: disk persistence and reload (new instance, same file) ----


def test_calc_state_in_memory_creates_no_file(tmp_path):
    state = CalcState()
    state.set_variable("a", "5")
    assert state.variables() == {"a": "5"}
    assert list(tmp_path.iterdir()) == []  # nothing written anywhere


def test_calc_state_round_trips_through_the_same_file(tmp_path):
    path = str(tmp_path / "state.json")
    state = CalcState(path)
    state.set_variable("a", "5")

    # A brand-new CalcState built on the same path picks up the value.
    reloaded = CalcState(path)
    assert reloaded.variables() == {"a": "5"}
    assert reloaded.functions() == {}
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == {
        "variables": {"a": "5"},
        "functions": {},
    }


def test_calc_state_loads_old_file_missing_functions_key(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"variables": {"a": "5"}}), encoding="utf-8")

    state = CalcState(str(path))
    assert state.variables() == {"a": "5"}
    assert state.functions() == {}


def test_variable_survives_server_restart_on_same_state_file(tmp_path):
    """The variable still works after state is reloaded from disk: a new
    CalcState/server instance on the same state file, standing in for a
    process restart with the same --state path (the CLI flag itself is a
    later feature, P9)."""
    path = str(tmp_path / "state.json")

    srv1 = build_server(0, state=CalcState(path))
    base1 = _start(srv1)
    try:
        status, body = _post(base1, "/api/calc/evaluate", {"expr": "a:=5"})
        assert status == 200
        assert body["exact"] == "5"
    finally:
        _stop(srv1)

    srv2 = build_server(0, state=CalcState(path))
    base2 = _start(srv2)
    try:
        status, body = _post(base2, "/api/calc/evaluate", {"expr": "2a+1"})
        assert status == 200
        assert body["exact"] == "11"
    finally:
        _stop(srv2)
