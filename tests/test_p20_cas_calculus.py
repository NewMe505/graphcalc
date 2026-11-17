"""Tests for plan step P20/S1 (POST /api/cas/derivative).

F1 (PRODUCT.md, [failing] before P20/S1): 'derivative of "x*sin(x)" by x
returns "x*cos(x) + sin(x)"'. test_p20_derivative_product_rule proves
exactly that through the real POST /api/cas/derivative route (graphcalc.
cli.Handler.do_POST) against an in-process server, reusing the same
`_post` HTTP helper tests/test_p19_cas.py already reuses from
tests/test_p15_lists.py. test_p20_derivative_unit_product_rule proves the
same thing directly against graphcalc.cas.derivative(), with no HTTP
involved.

The acceptance checklist does not list a derivative malformed-input case
explicitly, but P20/S1's own plan step asks for the same "never a 500"
shape every other CAS route already has: test_p20_derivative_400_missing_var
and test_p20_derivative_400_non_string_var prove a missing or non-string
"var" is a JSON 400 (never a 500), test_p20_derivative_400_malformed_expr
proves the same for a malformed "expr", and
test_p20_derivative_unit_malformed_expr_raises_calc_error proves the
malformed-expr case directly raises graphcalc.calc.CalcError from
graphcalc.cas.derivative, which is what lets the HTTP handler turn it into
a 400 in the first place. test_p20_derivative_unit_non_identifier_var_raises_calc_error
proves the same for a `var` that is not a plain identifier (e.g. "x+1").

test_p20_derivative_400_huge_power_expr proves the P28-style power-size
guard plan step P20/S1 adds to graphcalc.cas._parse (shared by every CAS
operation) turns a would-hang "expr" such as "x*9^9^9" into a quick JSON
400 instead of ever letting sympy's own parse_expr try to materialize an
astronomically large integer -- the "guard against hangs, as in P28"
planner note for this plan step.
"""

import pytest

from graphcalc import cas
from graphcalc.calc import CalcError
from graphcalc.cli import build_server

from tests.test_p15_lists import _post  # reuse the same tiny HTTP helper

# Reuse the exact same `server`/`base` fixtures tests/test_p19_cas.py defines
# for the sibling CAS routes (stateless route, fresh server per test anyway).
import threading

import pytest as _pytest  # noqa: F401  (kept for fixture parity/readability)


@pytest.fixture
def server():
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


# ---- F1: derivative of "x*sin(x)" by x returns "x*cos(x) + sin(x)" ----


def test_p20_derivative_product_rule(base):
    status, body = _post(base, "/api/cas/derivative", {"expr": "x*sin(x)", "var": "x"})
    assert status == 200, body
    assert body == {"result": "x*cos(x) + sin(x)"}, body


def test_p20_derivative_unit_product_rule():
    assert cas.derivative("x*sin(x)", "x") == "x*cos(x) + sin(x)"


# ---- a missing or non-string "var" is a JSON 400 ----


def test_p20_derivative_400_missing_var(base):
    status, body = _post(base, "/api/cas/derivative", {"expr": "x*sin(x)"})
    assert status == 400, body
    assert "error" in body, body


def test_p20_derivative_400_non_string_var(base):
    status, body = _post(base, "/api/cas/derivative", {"expr": "x*sin(x)", "var": 42})
    assert status == 400, body
    assert "error" in body, body


# ---- a malformed "expr" is a JSON 400 ----


def test_p20_derivative_400_malformed_expr(base):
    status, body = _post(base, "/api/cas/derivative", {"expr": "x+", "var": "x"})
    assert status == 400, body
    assert "error" in body, body


def test_p20_derivative_unit_malformed_expr_raises_calc_error():
    with pytest.raises(CalcError):
        cas.derivative("x+", "x")


def test_p20_derivative_unit_non_identifier_var_raises_calc_error():
    with pytest.raises(CalcError):
        cas.derivative("x*sin(x)", "x+1")


# ---- P28-style power-size guard: does not hang on "9^9^9" ----


def test_p20_derivative_400_huge_power_expr(base):
    status, body = _post(base, "/api/cas/derivative", {"expr": "x*9^9^9", "var": "x"})
    assert status == 400, body
    assert "error" in body, body
