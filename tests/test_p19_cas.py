"""Tests for plan step P19/S1 (POST /api/cas/simplify), P19/S2 (POST
/api/cas/expand) and P19/S3 (POST /api/cas/factor).

F1 (PRODUCT.md, [failing] before P19/S1): 'simplify "(x^2-1)/(x-1)"
returns result "x + 1"'. test_cas_simplify_rational_cancellation proves
exactly that, through the real POST /api/cas/simplify route (graphcalc.
cli.Handler.do_POST) against an in-process server, reusing the same `_post`
HTTP helper and server-building pattern tests/test_p17_regression.py
already uses. test_cas_simplify_unit_rational_cancellation proves the same
thing directly against graphcalc.cas.simplify(), with no HTTP involved.

The remaining simplify tests cover that step's own spec: simplify renders
a power with "^" (test_cas_simplify_power_notation, both via HTTP and the
unit function), and the acceptance checklist's "a malformed expr returns
400" half (test_cas_simplify_400_malformed_expr, test_cas_simplify_400_missing_expr,
test_cas_simplify_400_non_object_body) -- each a JSON 400 with an "error"
key, never a 500, the same "never a 500" rule every other math-performing
route already follows. test_cas_simplify_unit_malformed_expr_raises_calc_error
proves the same malformed-expr case raises graphcalc.calc.CalcError
directly from graphcalc.cas.simplify, which is what lets the HTTP handler
turn it into a 400 in the first place.

F2 (PRODUCT.md, [failing] before P19/S2): 'expand "(x+1)^2" returns result
"x^2 + 2*x + 1"'. test_cas_expand_square_binomial proves exactly that
through the real POST /api/cas/expand route; test_cas_expand_unit_square_binomial
proves the same thing directly against graphcalc.cas.expand(). The
remaining expand tests mirror the simplify ones above: the result uses
"^" and never "**" (test_cas_expand_power_notation_no_double_star, both via
HTTP and the unit function), the "a malformed expr returns 400" half
(test_cas_expand_400_malformed_expr, test_cas_expand_400_missing_expr,
test_cas_expand_400_non_object_body), and the unit-level CalcError
(test_cas_expand_unit_malformed_expr_raises_calc_error).

F3 (PRODUCT.md, [failing] before P19/S3): 'factor "x^2-5x+6" returns
result "(x - 3)*(x - 2)"; a malformed expr returns 400'.
test_cas_factor_quadratic_two_roots proves the result half through the
real POST /api/cas/factor route; test_cas_factor_unit_quadratic_two_roots
proves the same thing directly against graphcalc.cas.factor(). The
remaining factor tests mirror the simplify/expand ones above
(test_cas_factor_400_malformed_expr, test_cas_factor_400_missing_expr,
test_cas_factor_400_non_object_body, and the unit-level
test_cas_factor_unit_malformed_expr_raises_calc_error).

The acceptance checklist's "a malformed expr returns 400" clause names
/simplify, /expand and /factor together, not factor alone, so
test_cas_factor_400_all_endpoints_empty_expr,
test_cas_factor_400_all_endpoints_non_string_expr and
test_cas_factor_400_all_endpoints_invalid_json_body each parametrize over
all three CAS paths and prove the remaining malformed-input shapes the
earlier F1/F2 tests above did not yet cover for any of them: an empty
"expr" string, a non-string "expr" (a JSON number), and a request body
that is not valid JSON at all (truncated JSON text, via the same
http.client-based _raw_post helper tests/test_calc_evaluate.py already
uses for this). Every case is a JSON 400 with an "error" key, never a
500, the same "never a 500" rule every other math-performing route
already follows.
"""

import http.client
import json
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


def _raw_post(server, path, raw_body: bytes):
    """POST raw (possibly non-JSON) bytes, for malformed-body tests.

    Same helper tests/test_calc_evaluate.py already uses: `_post` always
    re-encodes a Python object with json.dumps, so it cannot send a body
    that is not valid JSON in the first place.
    """
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
    try:
        conn.request(
            "POST",
            path,
            body=raw_body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(raw_body))},
        )
        res = conn.getresponse()
        return res.status, json.loads(res.read().decode("utf-8"))
    finally:
        conn.close()


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


# ---- F2: expand "(x+1)^2" returns result "x^2 + 2*x + 1" ----


def test_cas_expand_square_binomial(base):
    status, body = _post(base, "/api/cas/expand", {"expr": "(x+1)^2"})
    assert status == 200, body
    assert body == {"result": "x^2 + 2*x + 1"}, body


def test_cas_expand_unit_square_binomial():
    assert cas.expand("(x+1)^2") == "x^2 + 2*x + 1"


# ---- powers render with "^", never "**" ----


def test_cas_expand_power_notation_no_double_star(base):
    status, body = _post(base, "/api/cas/expand", {"expr": "(x+1)^2"})
    assert status == 200, body
    assert "^" in body["result"], body
    assert "**" not in body["result"], body


def test_cas_expand_unit_power_notation_no_double_star():
    result = cas.expand("(x+1)^2")
    assert "^" in result, result
    assert "**" not in result, result


# ---- "a malformed expr returns 400" ----


def test_cas_expand_400_malformed_expr(base):
    status, body = _post(base, "/api/cas/expand", {"expr": "x+"})
    assert status == 400, body
    assert "error" in body, body


def test_cas_expand_400_missing_expr(base):
    status, body = _post(base, "/api/cas/expand", {})
    assert status == 400, body
    assert "error" in body, body


def test_cas_expand_400_non_object_body(base):
    status, body = _post(base, "/api/cas/expand", ["not", "an", "object"])
    assert status == 400, body
    assert "error" in body, body


def test_cas_expand_unit_malformed_expr_raises_calc_error():
    with pytest.raises(CalcError):
        cas.expand("x+")


# ---- F3: factor "x^2-5x+6" returns result "(x - 3)*(x - 2)" ----


def test_cas_factor_quadratic_two_roots(base):
    status, body = _post(base, "/api/cas/factor", {"expr": "x^2-5x+6"})
    assert status == 200, body
    assert body == {"result": "(x - 3)*(x - 2)"}, body


def test_cas_factor_unit_quadratic_two_roots():
    assert cas.factor("x^2-5x+6") == "(x - 3)*(x - 2)"


# ---- "a malformed expr returns 400" ----


def test_cas_factor_400_malformed_expr(base):
    status, body = _post(base, "/api/cas/factor", {"expr": "(x+"})
    assert status == 400, body
    assert "error" in body, body


def test_cas_factor_400_missing_expr(base):
    status, body = _post(base, "/api/cas/factor", {})
    assert status == 400, body
    assert "error" in body, body


def test_cas_factor_400_non_object_body(base):
    status, body = _post(base, "/api/cas/factor", ["not", "an", "object"])
    assert status == 400, body
    assert "error" in body, body


def test_cas_factor_unit_malformed_expr_raises_calc_error():
    with pytest.raises(CalcError):
        cas.factor("(x+")


# ---- malformed-input shapes shared across /simplify, /expand and /factor ----

CAS_PATHS = ("/api/cas/simplify", "/api/cas/expand", "/api/cas/factor")


@pytest.mark.parametrize("path", CAS_PATHS)
def test_cas_factor_400_all_endpoints_empty_expr(base, path):
    status, body = _post(base, path, {"expr": ""})
    assert status == 400, body
    assert "error" in body, body


@pytest.mark.parametrize("path", CAS_PATHS)
def test_cas_factor_400_all_endpoints_non_string_expr(base, path):
    status, body = _post(base, path, {"expr": 42})
    assert status == 400, body
    assert "error" in body, body


@pytest.mark.parametrize("path", CAS_PATHS)
def test_cas_factor_400_all_endpoints_invalid_json_body(server, path):
    status, body = _raw_post(server, path, b'{"expr": "x+1"')  # truncated JSON
    assert status == 400, body
    assert "error" in body, body
