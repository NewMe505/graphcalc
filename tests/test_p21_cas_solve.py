"""Tests for plan step P21/S1 (POST /api/cas/solve).

F1 (PRODUCT.md, [failing] before P21/S1): 'solve "x^2=4" for x returns
{"solutions":["-2","2"]}'. test_p21_solve_quadratic_two_real_roots proves
exactly that through the real POST /api/cas/solve route (graphcalc.cli.
Handler.do_POST) against an in-process server, reusing the same `_post`
HTTP helper tests/test_p20_cas_calculus.py already reuses from
tests/test_p15_lists.py. test_p21_solve_unit_quadratic_two_real_roots
proves the same thing directly against graphcalc.cas.solve(), with no
HTTP involved.

F2 (PRODUCT.md, [failing] before P21/S1): 'solve "x^2+1" for x returns
{"solutions":["-I","I"]}' -- a bare expression with no "=" is taken to
equal 0, and sympy.solve() already finds the complex roots with no extra
domain hint. test_p21_solve_no_equals_complex_roots and
test_p21_solve_unit_no_equals_complex_roots prove exactly that, the same
two ways (HTTP route, then direct unit call).

F3 (PRODUCT.md, [failing] before P21/S1): 'solve "2y+3=7" for y returns
{"solutions":["2"]}; a missing var returns 400'.
test_p21_solve_linear_single_root and test_p21_solve_unit_linear_single_root
prove the first half; test_p21_solve_400_missing_var proves a missing
"var" is a JSON 400 (never a 500), the same "missing parameter: var"
shape _handle_cas_derivative/_handle_cas_limit already use.
test_p21_solve_400_non_string_var proves the same for a non-string "var".

The acceptance checklist does not list an "equation" malformed-input case
explicitly, but P21/S1's own plan step gives graphcalc.cas.solve the same
"never a 500" shape every other CAS route already has:
test_p21_solve_400_missing_equation proves a missing "equation" is a JSON
400; test_p21_solve_400_multiple_equals proves an "equation" with more
than one "=" (e.g. "x=y=2") is also a JSON 400, not treated as a valid
two-part split. test_p21_solve_unit_missing_equation_raises_calc_error and
test_p21_solve_unit_multiple_equals_raises_calc_error prove the same two
cases directly raise graphcalc.calc.CalcError from graphcalc.cas.solve,
which is what lets the HTTP handler turn them into a 400 in the first
place. test_p21_solve_unit_non_identifier_var_raises_calc_error proves the
same for a `var` that is not a plain identifier (e.g. "x+1"), the same
rule derivative()/integral()/limit() already apply.
"""

import pytest

from graphcalc import cas
from graphcalc.calc import CalcError
from graphcalc.cli import build_server

from tests.test_p15_lists import _post  # reuse the same tiny HTTP helper

# Reuse the exact same `server`/`base` fixture shape tests/test_p20_cas_calculus.py
# defines for the sibling CAS routes (stateless route, fresh server per test anyway).
import threading


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


# ---- F1: solve "x^2=4" for x returns {"solutions":["-2","2"]} ----


def test_p21_solve_quadratic_two_real_roots(base):
    status, body = _post(base, "/api/cas/solve", {"equation": "x^2=4", "var": "x"})
    assert status == 200, body
    assert body == {"solutions": ["-2", "2"]}, body


def test_p21_solve_unit_quadratic_two_real_roots():
    assert cas.solve("x^2=4", "x") == ["-2", "2"]


# ---- F2: solve "x^2+1" for x returns {"solutions":["-I","I"]} ----


def test_p21_solve_no_equals_complex_roots(base):
    status, body = _post(base, "/api/cas/solve", {"equation": "x^2+1", "var": "x"})
    assert status == 200, body
    assert body == {"solutions": ["-I", "I"]}, body


def test_p21_solve_unit_no_equals_complex_roots():
    assert cas.solve("x^2+1", "x") == ["-I", "I"]


# ---- F3: solve "2y+3=7" for y returns {"solutions":["2"]}; a missing var returns 400 ----


def test_p21_solve_linear_single_root(base):
    status, body = _post(base, "/api/cas/solve", {"equation": "2y+3=7", "var": "y"})
    assert status == 200, body
    assert body == {"solutions": ["2"]}, body


def test_p21_solve_unit_linear_single_root():
    assert cas.solve("2y+3=7", "y") == ["2"]


def test_p21_solve_400_missing_var(base):
    status, body = _post(base, "/api/cas/solve", {"equation": "2y+3=7"})
    assert status == 400, body
    assert "error" in body, body


def test_p21_solve_400_non_string_var(base):
    status, body = _post(base, "/api/cas/solve", {"equation": "2y+3=7", "var": 42})
    assert status == 400, body
    assert "error" in body, body


# ---- a missing "equation" is a JSON 400, not a 500 ----


def test_p21_solve_400_missing_equation(base):
    status, body = _post(base, "/api/cas/solve", {"var": "x"})
    assert status == 400, body
    assert "error" in body, body


def test_p21_solve_unit_missing_equation_raises_calc_error():
    with pytest.raises(CalcError):
        cas.solve("", "x")


# ---- an "equation" with more than one "=" is a JSON 400, not a 500 ----


def test_p21_solve_400_multiple_equals(base):
    status, body = _post(base, "/api/cas/solve", {"equation": "x=y=2", "var": "x"})
    assert status == 400, body
    assert "error" in body, body


def test_p21_solve_unit_multiple_equals_raises_calc_error():
    with pytest.raises(CalcError):
        cas.solve("x=y=2", "x")


def test_p21_solve_unit_non_identifier_var_raises_calc_error():
    with pytest.raises(CalcError):
        cas.solve("2y+3=7", "x+1")
