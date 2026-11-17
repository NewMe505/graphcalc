"""Tests for plan steps P12/S1, P12/S2 and P12/S3: graphcalc/graph.py's
analyze() and POST /api/graph/analyze -- the "value", "zero", "minimum",
"maximum" and "intersection" operations, plus request validation shared
by every operation.

F1 (PRODUCT.md, [failing] before P12/S1): 'value of "x^2+1" at x=3
returns x "3", y "10"; zero of "x^2-4" on [0,5] returns x "2"'.
test_p12_value_direct/test_p12_value_http and
test_p12_zero_direct/test_p12_zero_http prove this directly (calling
graphcalc.graph.analyze) and over HTTP, against an in-process server
built the same way tests/test_p11_graph_window.py's own `server`/`base`
fixtures build one for /api/graph/window.

The acceptance criteria's own third example -- 'zero of "x^2+1" on
[-5,5] returns 200 with x null, y null and domain_error "no zero in
interval"' -- is proven by test_p12_zero_none_direct/_http: this is a
200, not a 400 ("No zero or intersection: 200 with domain_error",
planner notes).

A gap at the requested x (e.g. "1/x" at x=0) is covered by
test_p12_value_domain_gap: "y" is None, "domain_error" is set, but "x"
is still the formatted input and the status is 200 -- "a gap returns
domain_error instead of y" (planner notes).

F2 (PRODUCT.md, [failing] before P12/S2): 'minimum of "x^2-2x" on [-5,5]
returns x "1", y "-1"; maximum of "-x^2+4" on [-3,3] returns x "0", y
"4"'. test_p12_minimum_direct/test_p12_minimum_http and
test_p12_maximum_direct/test_p12_maximum_http prove this directly and
over HTTP, the same two ways F1 is proven above.
test_p12_extremum_no_finite_value_direct/_http covers the "no finite
value anywhere on the interval" domain_error case the planner notes call
out for this step, the same 200-with-domain_error shape "zero"'s own
no-root case already uses.

F3 (PRODUCT.md, [failing] before P12/S3): 'intersection of "x" and "x^2"
on [0.5,2] returns x "1", y "1"; zero of "x^2+1" on [-5,5] returns 200
with x null, y null and domain_error "no zero in interval"'.
test_p12_intersection_direct/test_p12_intersection_http prove the first
half; the second half is the same test_p12_zero_none_direct/_http
already proving F1's own third example above -- F3 does not add a new
case for it, since "intersection"'s own zero-finder (P12/S3's "run the
S1 zero-finder on h = f - g") is the same one "zero" already uses.
"intersection without g gives 400" is the "intersection_missing_g" case
already parametrized into test_p12_bad_request_400 below.

Validation -- bad operation, missing f, value without x, zero without
lower/upper, lower==upper, lower>upper, a non-finite bound, intersection
without g, and an unsafe expression -- is covered by
test_p12_bad_request_400, parametrized over all of those cases: each
must 400 with a JSON {"error": ...} body, and the equivalent direct call
must raise graphcalc.graph.GraphError or graphcalc.calc.CalcError,
never return normally.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from graphcalc import calc
from graphcalc.cli import build_server
from graphcalc.graph import GraphError, analyze


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


@pytest.fixture
def server():
    """A fresh server with a default (in-memory) history store and state.

    POST /api/graph/analyze never reads either one (stateless, like
    /api/graph/plot and /api/graph/window), but build_server() always
    wires up both regardless, the same way every other test in this
    repository builds a server.
    """
    srv = build_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def base(server):
    return f"http://127.0.0.1:{server.server_port}"


# ---- F1: value of "x^2+1" at x=3 ----


def test_p12_value_direct():
    result = analyze({"operation": "value", "f": "x^2+1", "x": 3})
    assert result == {
        "operation": "value",
        "x": "3",
        "y": "10",
        "domain_error": None,
    }, result


def test_p12_value_http(base):
    status, body = _post(
        base, "/api/graph/analyze", {"operation": "value", "f": "x^2+1", "x": 3}
    )
    assert status == 200, body
    assert body == {
        "operation": "value",
        "x": "3",
        "y": "10",
        "domain_error": None,
    }, body


# ---- F1: zero of "x^2-4" on [0,5] ----


def test_p12_zero_direct():
    result = analyze({"operation": "zero", "f": "x^2-4", "lower": 0, "upper": 5})
    assert result["operation"] == "zero", result
    assert result["x"] == "2", result
    assert result["y"] == "0", result
    assert result["domain_error"] is None, result


def test_p12_zero_http(base):
    status, body = _post(
        base,
        "/api/graph/analyze",
        {"operation": "zero", "f": "x^2-4", "lower": 0, "upper": 5},
    )
    assert status == 200, body
    assert body["operation"] == "zero", body
    assert body["x"] == "2", body
    assert body["y"] == "0", body
    assert body["domain_error"] is None, body


# ---- acceptance criteria's third example: no zero in the interval ----


def test_p12_zero_none_direct():
    result = analyze({"operation": "zero", "f": "x^2+1", "lower": -5, "upper": 5})
    assert result == {
        "operation": "zero",
        "x": None,
        "y": None,
        "domain_error": "no zero in interval",
    }, result


def test_p12_zero_none_http(base):
    status, body = _post(
        base,
        "/api/graph/analyze",
        {"operation": "zero", "f": "x^2+1", "lower": -5, "upper": 5},
    )
    assert status == 200, body
    assert body == {
        "operation": "zero",
        "x": None,
        "y": None,
        "domain_error": "no zero in interval",
    }, body


# ---- a gap at the requested x is a domain_error, not an error status ----


def test_p12_value_domain_gap():
    result = analyze({"operation": "value", "f": "1/x", "x": 0})
    assert result["operation"] == "value", result
    assert result["y"] is None, result
    assert isinstance(result["domain_error"], str) and result["domain_error"], result


def test_p12_value_domain_gap_http(base):
    status, body = _post(
        base, "/api/graph/analyze", {"operation": "value", "f": "1/x", "x": 0}
    )
    assert status == 200, body
    assert body["y"] is None, body
    assert isinstance(body["domain_error"], str) and body["domain_error"], body


# ---- F2: minimum of "x^2-2x" on [-5,5] ----


def test_p12_minimum_direct():
    result = analyze(
        {"operation": "minimum", "f": "x^2-2x", "lower": -5, "upper": 5}
    )
    assert result == {
        "operation": "minimum",
        "x": "1",
        "y": "-1",
        "domain_error": None,
    }, result


def test_p12_minimum_http(base):
    status, body = _post(
        base,
        "/api/graph/analyze",
        {"operation": "minimum", "f": "x^2-2x", "lower": -5, "upper": 5},
    )
    assert status == 200, body
    assert body == {
        "operation": "minimum",
        "x": "1",
        "y": "-1",
        "domain_error": None,
    }, body


# ---- F2: maximum of "-x^2+4" on [-3,3] ----


def test_p12_maximum_direct():
    result = analyze(
        {"operation": "maximum", "f": "-x^2+4", "lower": -3, "upper": 3}
    )
    assert result == {
        "operation": "maximum",
        "x": "0",
        "y": "4",
        "domain_error": None,
    }, result


def test_p12_maximum_http(base):
    status, body = _post(
        base,
        "/api/graph/analyze",
        {"operation": "maximum", "f": "-x^2+4", "lower": -3, "upper": 3},
    )
    assert status == 200, body
    assert body == {
        "operation": "maximum",
        "x": "0",
        "y": "4",
        "domain_error": None,
    }, body


# ---- minimum/maximum: no finite value anywhere on the interval ----


def test_p12_extremum_no_finite_value_direct():
    result = analyze(
        {"operation": "minimum", "f": "1/0", "lower": -5, "upper": 5}
    )
    assert result == {
        "operation": "minimum",
        "x": None,
        "y": None,
        "domain_error": "no minimum in interval",
    }, result


def test_p12_extremum_no_finite_value_http(base):
    status, body = _post(
        base,
        "/api/graph/analyze",
        {"operation": "maximum", "f": "1/0", "lower": -5, "upper": 5},
    )
    assert status == 200, body
    assert body == {
        "operation": "maximum",
        "x": None,
        "y": None,
        "domain_error": "no maximum in interval",
    }, body


# ---- F3: intersection of "x" and "x^2" on [0.5,2] ----


def test_p12_intersection_direct():
    result = analyze(
        {"operation": "intersection", "f": "x", "g": "x^2", "lower": 0.5, "upper": 2}
    )
    assert result == {
        "operation": "intersection",
        "x": "1",
        "y": "1",
        "domain_error": None,
    }, result


def test_p12_intersection_http(base):
    status, body = _post(
        base,
        "/api/graph/analyze",
        {"operation": "intersection", "f": "x", "g": "x^2", "lower": 0.5, "upper": 2},
    )
    assert status == 200, body
    assert body == {
        "operation": "intersection",
        "x": "1",
        "y": "1",
        "domain_error": None,
    }, body


# ---- intersection: no intersection in the interval ----


def test_p12_intersection_none_direct():
    result = analyze(
        {"operation": "intersection", "f": "x^2+1", "g": "0", "lower": -5, "upper": 5}
    )
    assert result == {
        "operation": "intersection",
        "x": None,
        "y": None,
        "domain_error": "no intersection in interval",
    }, result


def test_p12_intersection_none_http(base):
    status, body = _post(
        base,
        "/api/graph/analyze",
        {
            "operation": "intersection",
            "f": "x^2+1",
            "g": "0",
            "lower": -5,
            "upper": 5,
        },
    )
    assert status == 200, body
    assert body == {
        "operation": "intersection",
        "x": None,
        "y": None,
        "domain_error": "no intersection in interval",
    }, body


# ---- validation: every way the request can be malformed ----


_BAD_REQUESTS = {
    "bad_operation": {"operation": "sideways", "f": "x", "lower": 0, "upper": 1},
    "missing_f": {"operation": "value", "x": 1},
    "value_missing_x": {"operation": "value", "f": "x^2+1"},
    "zero_missing_bounds": {"operation": "zero", "f": "x^2-4"},
    "zero_missing_upper": {"operation": "zero", "f": "x^2-4", "lower": 0},
    "lower_equals_upper": {
        "operation": "zero",
        "f": "x^2-4",
        "lower": 1,
        "upper": 1,
    },
    "lower_greater_than_upper": {
        "operation": "zero",
        "f": "x^2-4",
        "lower": 5,
        "upper": 0,
    },
    "non_finite_bound": {
        "operation": "zero",
        "f": "x^2-4",
        "lower": 0,
        "upper": float("inf"),
    },
    "intersection_missing_g": {
        "operation": "intersection",
        "f": "x",
        "lower": 0,
        "upper": 1,
    },
    "unsafe_expression": {
        "operation": "value",
        "f": '__import__("os")',
        "x": 1,
    },
}


@pytest.mark.parametrize("case", sorted(_BAD_REQUESTS))
def test_p12_bad_request_400(base, case):
    payload = _BAD_REQUESTS[case]
    status, body = _post(base, "/api/graph/analyze", payload)
    assert status == 400, (case, body)
    assert isinstance(body.get("error"), str) and body["error"], (case, body)

    with pytest.raises((GraphError, calc.CalcError)):
        analyze(payload)
