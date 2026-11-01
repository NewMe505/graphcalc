"""Tests for free symbols, mode/expr validation and the reserved-name check
(feature P5, plan step S3).

Covers: an undefined name in an expression parses as a sympy Symbol via
implicit multiplication ("2x" -> exact "2*x"), and a result that still has
free symbols reports decimal (and complex) as None instead of trying to
format a non-number. mode accepts only "rad" or "deg" (anything else, or a
non-string value, is a 400); a missing or non-string expr is also a 400.
A syntax error ("2+*") stays a 400, never a 500, matching calc.evaluate's
and the HTTP handler's existing contract. Checked both via calc.evaluate
directly and over HTTP through POST /api/calc/evaluate, plus a direct unit
test of graphcalc.names.check_not_constant.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from graphcalc.calc import CalcError, evaluate
from graphcalc.cli import Handler
from graphcalc.names import check_not_constant


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


# ---- unit tests: calc.evaluate, no HTTP, no server ----


def test_evaluate_undefined_name_gives_free_symbol_exact_and_null_decimal():
    result = evaluate("2x")
    assert result["exact"] == "2*x"
    assert result["decimal"] is None
    assert result["complex"] is None
    assert result["domain_error"] is None


def test_evaluate_multiple_free_symbols_stays_symbolic():
    result = evaluate("x+y")
    assert result["exact"] == "x + y"
    assert result["decimal"] is None
    assert result["complex"] is None


def test_evaluate_invalid_mode_string_raises_calc_error():
    with pytest.raises(CalcError):
        evaluate("1", mode="grad")


def test_evaluate_non_string_mode_raises_calc_error():
    with pytest.raises(CalcError):
        evaluate("1", mode=5)


def test_evaluate_missing_expr_raises_calc_error():
    with pytest.raises(CalcError):
        evaluate(None)


def test_evaluate_non_string_expr_raises_calc_error():
    with pytest.raises(CalcError):
        evaluate(5)


def test_evaluate_syntax_error_raises_calc_error_not_other_exception():
    with pytest.raises(CalcError):
        evaluate("2+*3")


# ---- HTTP tests: the registered route ----


def test_api_undefined_name_returns_200_free_symbol_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "2x"})
        assert status == 200
        assert body["exact"] == "2*x"
        assert body["decimal"] is None
    finally:
        server.shutdown()
        server.server_close()


def test_api_mode_grad_returns_400_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1", "mode": "grad"})
        assert status == 400
        assert "error" in body
    finally:
        server.shutdown()
        server.server_close()


def test_api_mode_non_string_returns_400_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1", "mode": 5})
        assert status == 400
        assert "error" in body
    finally:
        server.shutdown()
        server.server_close()


def test_api_missing_expr_returns_400_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"mode": "rad"})
        assert status == 400
        assert "error" in body
    finally:
        server.shutdown()
        server.server_close()


def test_api_syntax_error_returns_400_never_500_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "2+*3"})
        assert status == 400
        assert "error" in body
    finally:
        server.shutdown()
        server.server_close()


# ---- unit tests: graphcalc.names.check_not_constant ----


def test_check_not_constant_raises_for_reserved_name():
    with pytest.raises(CalcError):
        check_not_constant("pi")


def test_check_not_constant_raises_for_other_reserved_names():
    for name in ("e", "E", "I", "i", "oo", "sin"):
        with pytest.raises(CalcError):
            check_not_constant(name)


def test_check_not_constant_allows_a_free_name():
    check_not_constant("x")  # must not raise
