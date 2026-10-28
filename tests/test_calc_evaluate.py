"""Tests for graphcalc.calc.evaluate, graphcalc.numfmt.format_decimal, and
the POST /api/calc/evaluate route (plan step S1).

Covers: "1/3+1/6" (fraction addition) gives exact "1/2" and decimal "0.5";
"2(3+1)^2" (implied multiplication plus a caret power) gives exact "32";
"1/3" gives a 12-significant-digit decimal "0.333333333333"; complex and
domain_error stay null for ordinary real arithmetic. format_decimal and
calc.evaluate are also exercised directly, with no HTTP involved.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

from sympy import Integer, Rational

from graphcalc.calc import evaluate
from graphcalc.cli import Handler
from graphcalc.numfmt import format_decimal


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


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


# ---- unit tests: format_decimal, no HTTP, no server ----


def test_format_decimal_one_half_has_no_trailing_zeros():
    assert format_decimal(Rational(1, 2)) == "0.5"


def test_format_decimal_one_third_is_twelve_significant_digits():
    assert format_decimal(Rational(1, 3)) == "0.333333333333"


def test_format_decimal_integer_has_no_decimal_point():
    assert format_decimal(Integer(32)) == "32"


def test_format_decimal_zero():
    assert format_decimal(Integer(0)) == "0"


# ---- unit tests: calc.evaluate, no HTTP, no server ----


def test_evaluate_fraction_sum():
    result = evaluate("1/3+1/6")
    assert result["expr"] == "1/3+1/6"
    assert result["exact"] == "1/2"
    assert result["decimal"] == "0.5"
    assert result["complex"] is None
    assert result["domain_error"] is None


def test_evaluate_implied_mult():
    result = evaluate("2(3+1)^2")
    assert result["exact"] == "32"
    assert result["complex"] is None
    assert result["domain_error"] is None


def test_evaluate_decimal_sig_digits():
    result = evaluate("1/3")
    assert result["decimal"] == "0.333333333333"
    # 12 significant digits: strip the leading "0." before counting.
    assert len(result["decimal"]) - len("0.") == 12


# ---- HTTP tests: the registered route ----


def test_api_calc_evaluate_returns_200_json_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1/3+1/6"})
        assert status == 200
        assert body["expr"] == "1/3+1/6"
        assert body["exact"] == "1/2"
        assert body["decimal"] == "0.5"
        assert body["complex"] is None
        assert body["domain_error"] is None
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_missing_expr_is_400():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {})
        assert status == 400
        assert "error" in body
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_malformed_expr_is_400_not_500():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "2+*3"})
        assert status == 400
        assert "error" in body
    finally:
        server.shutdown()
        server.server_close()
