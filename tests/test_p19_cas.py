"""Tests for plan step P19/S1: POST /api/cas/simplify.

F1 (PRODUCT.md, [failing] before this step): 'simplify "(x^2-1)/(x-1)"
returns result "x + 1"'. test_cas_simplify_rational_cancellation proves
exactly that, through the real POST /api/cas/simplify route (graphcalc.
cli.Handler.do_POST) against an in-process server, reusing the same `_post`
HTTP helper and server-building pattern tests/test_p17_regression.py
already uses. test_cas_simplify_unit_rational_cancellation proves the same
thing directly against graphcalc.cas.simplify(), with no HTTP involved.

The remaining tests cover this step's own spec: simplify renders a power
with "^" (test_cas_simplify_power_notation, both via HTTP and the unit
function), and the acceptance checklist's "a malformed expr returns 400"
half (test_cas_simplify_400_malformed_expr, test_cas_simplify_400_missing_expr,
test_cas_simplify_400_non_object_body) -- each a JSON 400 with an "error"
key, never a 500, the same "never a 500" rule every other math-performing
route already follows. test_cas_simplify_unit_malformed_expr_raises_calc_error
proves the same malformed-expr case raises graphcalc.calc.CalcError
directly from graphcalc.cas.simplify, which is what lets the HTTP handler
turn it into a 400 in the first place.
"""

import threading

import pytest

from graphcalc import cas
from graphcalc.calc import CalcError
from graphcalc.cli import build_server

from tests.test_p15_lists import _post  # reuse the same tiny HTTP helper


@pytest.fixture
def server():
    """A fresh server with a default (in-memory) history store and state.

    Same per-test isolation as tests/test_p17_regression.py's own `server`
    fixture -- this route is stateless, but the server itself is still
    built fresh per test to match every other HTTP test in this suite.
    """
    srv = build_server(0)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def base(server):
    return f"http://127.0.0.1:{server.server_port}"


# ---- F1: simplify "(x^2-1)/(x-1)" returns result "x + 1" ----


def test_cas_simplify_rational_cancellation(base):
    status, body = _post(base, "/api/cas/simplify", {"expr": "(x^2-1)/(x-1)"})
    assert status == 200, body
    assert body == {"result": "x + 1"}, body


def test_cas_simplify_unit_rational_cancellation():
    assert cas.simplify("(x^2-1)/(x-1)") == "x + 1"


# ---- powers render with "^", never "**" ----


def test_cas_simplify_power_notation(base):
    status, body = _post(base, "/api/cas/simplify", {"expr": "x*x"})
    assert status == 200, body
    assert body["result"] == "x^2", body


def test_cas_simplify_unit_power_notation():
    assert cas.simplify("x*x") == "x^2"


# ---- "a malformed expr returns 400" ----


def test_cas_simplify_400_malformed_expr(base):
    status, body = _post(base, "/api/cas/simplify", {"expr": "x+"})
    assert status == 400, body
    assert "error" in body, body


def test_cas_simplify_400_missing_expr(base):
    status, body = _post(base, "/api/cas/simplify", {})
    assert status == 400, body
    assert "error" in body, body


def test_cas_simplify_400_non_object_body(base):
    status, body = _post(base, "/api/cas/simplify", ["not", "an", "object"])
    assert status == 400, body
    assert "error" in body, body


def test_cas_simplify_unit_malformed_expr_raises_calc_error():
    with pytest.raises(CalcError):
        cas.simplify("x+")
