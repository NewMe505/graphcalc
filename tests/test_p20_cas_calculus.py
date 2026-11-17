"""Tests for plan step P20/S1 (POST /api/cas/derivative), P20/S2
(POST /api/cas/integral) and P20/S3 (POST /api/cas/limit).

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

F2 (PRODUCT.md, [failing] before P20/S2): 'integral of "x^2" by x returns
"x^3/3"; with lower 0 and upper 1 it returns "1/3"'.
test_p20_integral_indefinite_power_rule and
test_p20_integral_definite_power_rule prove exactly that through the real
POST /api/cas/integral route; test_p20_integral_unit_indefinite_power_rule
and test_p20_integral_unit_definite_power_rule prove the same two things
directly against graphcalc.cas.integral(), with no HTTP involved. This
plan step's own spec only teaches _parse_bound to accept a JSON int/float
for "lower"/"upper" -- an expression string such as "pi" is a later step,
not proven here.

test_p20_integral_400_only_one_bound and
test_p20_integral_unit_only_one_bound_raises_calc_error prove supplying
exactly one of "lower"/"upper" is a JSON 400 (graphcalc.cas.integral
raises CalcError, never silently treating the missing one as anything).
test_p20_integral_400_bool_bound and test_p20_integral_400_object_bound
prove a bool or a JSON object "lower"/"upper" is also a JSON 400 (bool is
explicitly rejected even though Python's bool is an int subclass);
test_p20_integral_unit_bool_bound_raises_calc_error and
test_p20_integral_unit_object_bound_raises_calc_error prove the same two
cases directly raise CalcError from graphcalc.cas.integral.

F3 (PRODUCT.md, [failing] before P20/S3): 'limit of "sin(x)/x" at point 0
returns "1"; limit of "1/x" at point 0 with dir "+" returns "oo"'.
test_p20_limit_two_sided_sinx_over_x and test_p20_limit_one_sided_plus_1_over_x
prove exactly that through the real POST /api/cas/limit route;
test_p20_limit_unit_two_sided_sinx_over_x and
test_p20_limit_unit_one_sided_plus_1_over_x prove the same two things
directly against graphcalc.cas.limit(), with no HTTP involved.

test_p20_limit_400_dir_non_plus_minus_string and
test_p20_limit_400_dir_non_string prove an invalid "dir" -- a string
other than "+"/"-", or a non-string such as 5 -- is a JSON 400;
test_p20_limit_unit_dir_non_plus_minus_string_raises_calc_error and
test_p20_limit_unit_dir_non_string_raises_calc_error prove the same two
cases directly raise CalcError from graphcalc.cas.limit.
test_p20_limit_400_missing_point proves a missing "point" is a JSON 400,
never a 500. test_p20_limit_400_two_sided_1_over_x and
test_p20_limit_unit_two_sided_1_over_x_raises_calc_error prove the
two-sided limit of "1/x" at 0 -- where sympy.limit() hands back its own
zoo instead of raising -- is also a CalcError/400, not a 200 echoing an
undefined "zoo" result.

F4 (PRODUCT.md, [failing] before P20/S4): 'integral of "sin(x)" by x with
lower 0 and upper "pi" returns "2"; limit of "1/x" at point "oo" returns
"0"'. test_p20_symbolic_bounds_integral_upper_pi and
test_p20_symbolic_bounds_unit_integral_upper_pi prove the first half
through the real POST /api/cas/integral route and directly against
graphcalc.cas.integral(); test_p20_symbolic_bounds_limit_point_oo and
test_p20_symbolic_bounds_unit_limit_point_oo prove the second half the
same two ways. test_p20_symbolic_bounds_limit_point_negative_oo and
test_p20_symbolic_bounds_unit_limit_point_negative_oo prove the "-oo"
spelling also works (the acceptance checklist only names "oo", but this
plan step's own notes ask for "-oo" too, since _parse_bound maps both).
test_p20_symbolic_bounds_400_free_symbol and
test_p20_symbolic_bounds_unit_400_free_symbol_raises_calc_error prove a
bound that parses to a free symbol ("y") is a JSON 400, never treated as
a number. test_p20_symbolic_bounds_400_garbage_string and
test_p20_symbolic_bounds_unit_400_garbage_string_raises_calc_error prove
a bound that is not valid grammar at all ("x+") is also a JSON 400, not a
500.
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


# ---- F2: integral of "x^2" by x returns "x^3/3"; lower 0, upper 1 returns "1/3" ----


def test_p20_integral_indefinite_power_rule(base):
    status, body = _post(base, "/api/cas/integral", {"expr": "x^2", "var": "x"})
    assert status == 200, body
    assert body == {"result": "x^3/3"}, body


def test_p20_integral_unit_indefinite_power_rule():
    assert cas.integral("x^2", "x") == "x^3/3"


def test_p20_integral_definite_power_rule(base):
    status, body = _post(
        base, "/api/cas/integral", {"expr": "x^2", "var": "x", "lower": 0, "upper": 1}
    )
    assert status == 200, body
    assert body == {"result": "1/3"}, body


def test_p20_integral_unit_definite_power_rule():
    assert cas.integral("x^2", "x", 0, 1) == "1/3"


# ---- supplying exactly one of "lower"/"upper" is a JSON 400 ----


def test_p20_integral_400_only_one_bound(base):
    status, body = _post(base, "/api/cas/integral", {"expr": "x^2", "var": "x", "lower": 0})
    assert status == 400, body
    assert "error" in body, body


def test_p20_integral_unit_only_one_bound_raises_calc_error():
    with pytest.raises(CalcError):
        cas.integral("x^2", "x", lower=0)


# ---- a bool or object "lower"/"upper" is a JSON 400 ----


def test_p20_integral_400_bool_bound(base):
    status, body = _post(
        base, "/api/cas/integral", {"expr": "x^2", "var": "x", "lower": True, "upper": 1}
    )
    assert status == 400, body
    assert "error" in body, body


def test_p20_integral_unit_bool_bound_raises_calc_error():
    with pytest.raises(CalcError):
        cas.integral("x^2", "x", True, 1)


def test_p20_integral_400_object_bound(base):
    status, body = _post(
        base, "/api/cas/integral", {"expr": "x^2", "var": "x", "lower": {}, "upper": 1}
    )
    assert status == 400, body
    assert "error" in body, body


def test_p20_integral_unit_object_bound_raises_calc_error():
    with pytest.raises(CalcError):
        cas.integral("x^2", "x", {}, 1)


# ---- F3: limit of "sin(x)/x" at 0 returns "1"; limit of "1/x" at 0 with dir "+" returns "oo" ----


def test_p20_limit_two_sided_sinx_over_x(base):
    status, body = _post(base, "/api/cas/limit", {"expr": "sin(x)/x", "var": "x", "point": 0})
    assert status == 200, body
    assert body == {"result": "1"}, body


def test_p20_limit_unit_two_sided_sinx_over_x():
    assert cas.limit("sin(x)/x", "x", 0) == "1"


def test_p20_limit_one_sided_plus_1_over_x(base):
    status, body = _post(
        base, "/api/cas/limit", {"expr": "1/x", "var": "x", "point": 0, "dir": "+"}
    )
    assert status == 200, body
    assert body == {"result": "oo"}, body


def test_p20_limit_unit_one_sided_plus_1_over_x():
    assert cas.limit("1/x", "x", 0, "+") == "oo"


# ---- an invalid "dir" (not None, "+" or "-") is a JSON 400 ----


def test_p20_limit_400_dir_non_plus_minus_string(base):
    status, body = _post(
        base, "/api/cas/limit", {"expr": "1/x", "var": "x", "point": 0, "dir": "x"}
    )
    assert status == 400, body
    assert "error" in body, body


def test_p20_limit_unit_dir_non_plus_minus_string_raises_calc_error():
    with pytest.raises(CalcError):
        cas.limit("1/x", "x", 0, "x")


def test_p20_limit_400_dir_non_string(base):
    status, body = _post(base, "/api/cas/limit", {"expr": "1/x", "var": "x", "point": 0, "dir": 5})
    assert status == 400, body
    assert "error" in body, body


def test_p20_limit_unit_dir_non_string_raises_calc_error():
    with pytest.raises(CalcError):
        cas.limit("1/x", "x", 0, 5)


# ---- a missing "point" is a JSON 400 ----


def test_p20_limit_400_missing_point(base):
    status, body = _post(base, "/api/cas/limit", {"expr": "sin(x)/x", "var": "x"})
    assert status == 400, body
    assert "error" in body, body


def test_p20_limit_unit_missing_point_raises_calc_error():
    with pytest.raises(CalcError):
        cas.limit("sin(x)/x", "x", None)


# ---- a two-sided limit that does not exist (sympy hands back zoo) is a JSON 400, not a 500 ----


def test_p20_limit_400_two_sided_1_over_x(base):
    status, body = _post(base, "/api/cas/limit", {"expr": "1/x", "var": "x", "point": 0})
    assert status == 400, body
    assert "error" in body, body


def test_p20_limit_unit_two_sided_1_over_x_raises_calc_error():
    with pytest.raises(CalcError):
        cas.limit("1/x", "x", 0)


# ---- F4: integral of "sin(x)" by x, lower 0, upper "pi" returns "2";
#          limit of "1/x" at point "oo" returns "0" ----


def test_p20_symbolic_bounds_integral_upper_pi(base):
    status, body = _post(
        base, "/api/cas/integral", {"expr": "sin(x)", "var": "x", "lower": 0, "upper": "pi"}
    )
    assert status == 200, body
    assert body == {"result": "2"}, body


def test_p20_symbolic_bounds_unit_integral_upper_pi():
    assert cas.integral("sin(x)", "x", 0, "pi") == "2"


def test_p20_symbolic_bounds_limit_point_oo(base):
    status, body = _post(base, "/api/cas/limit", {"expr": "1/x", "var": "x", "point": "oo"})
    assert status == 200, body
    assert body == {"result": "0"}, body


def test_p20_symbolic_bounds_unit_limit_point_oo():
    assert cas.limit("1/x", "x", "oo") == "0"


def test_p20_symbolic_bounds_limit_point_negative_oo(base):
    status, body = _post(base, "/api/cas/limit", {"expr": "1/x", "var": "x", "point": "-oo"})
    assert status == 200, body
    assert body == {"result": "0"}, body


def test_p20_symbolic_bounds_unit_limit_point_negative_oo():
    assert cas.limit("1/x", "x", "-oo") == "0"


# ---- a bound that parses to a free symbol ("y") is a JSON 400 ----


def test_p20_symbolic_bounds_400_free_symbol(base):
    status, body = _post(
        base, "/api/cas/integral", {"expr": "x^2", "var": "x", "lower": 0, "upper": "y"}
    )
    assert status == 400, body
    assert "error" in body, body


def test_p20_symbolic_bounds_unit_400_free_symbol_raises_calc_error():
    with pytest.raises(CalcError):
        cas.integral("x^2", "x", 0, "y")


# ---- a bound that is not valid grammar at all is a JSON 400, not a 500 ----


def test_p20_symbolic_bounds_400_garbage_string(base):
    status, body = _post(base, "/api/cas/limit", {"expr": "1/x", "var": "x", "point": "x+"})
    assert status == 400, body
    assert "error" in body, body


def test_p20_symbolic_bounds_unit_400_garbage_string_raises_calc_error():
    with pytest.raises(CalcError):
        cas.limit("1/x", "x", "x+")
