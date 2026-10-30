"""Tests for graphcalc.calc.evaluate, graphcalc.numfmt.format_decimal, and
the POST /api/calc/evaluate route (plan steps S1 and S2).

Covers: "1/3+1/6" (fraction addition) gives exact "1/2" and decimal "0.5";
"2(3+1)^2" (implied multiplication plus a caret power) gives exact "32";
"1/3" gives a 12-significant-digit decimal "0.333333333333"; complex and
domain_error stay null for ordinary real arithmetic. format_decimal and
calc.evaluate are also exercised directly, with no HTTP involved.

S2 adds the client-error side: a parse failure ("2+*3"), a missing "expr"
key (exact message "missing parameter: expr"), a malformed (non-JSON) body,
and an invalid "mode" (e.g. "grad") must each answer 400 with a JSON body
whose "error" is a string -- never a 500. A test with a patched-in
unexpected exception proves the handler's catch-all actually catches.
"""

import http.client
import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest
from sympy import Integer, Rational

from graphcalc.calc import CalcError, evaluate
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


def _raw_post(server, path, raw_body: bytes):
    """POST raw (possibly non-JSON) bytes, for malformed-body tests."""
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


# ---- unit tests: calc.evaluate raises CalcError, no HTTP, no server (S2) ----


def test_evaluate_malformed_expression_raises_calc_error():
    with pytest.raises(CalcError):
        evaluate("2+*3")


def test_evaluate_missing_expr_raises_calc_error():
    with pytest.raises(CalcError):
        evaluate("")


def test_evaluate_non_string_expr_raises_calc_error():
    with pytest.raises(CalcError):
        evaluate(None)


def test_evaluate_invalid_mode_raises_calc_error():
    with pytest.raises(CalcError):
        evaluate("1+1", mode="grad")


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
        assert body["error"] == "missing parameter: expr"
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_malformed_expr_is_400_not_500():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "2+*3"})
        assert status == 400
        assert isinstance(body["error"], str)
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_malformed_json_body_is_400():
    server = _start_server()
    try:
        status, body = _raw_post(server, "/api/calc/evaluate", b'{"expr": "1+1"')  # truncated
        assert status == 400
        assert isinstance(body["error"], str)
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_non_object_json_body_is_400():
    server = _start_server()
    try:
        status, body = _raw_post(server, "/api/calc/evaluate", b"[1, 2, 3]")
        assert status == 400
        assert isinstance(body["error"], str)
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_invalid_mode_grad_is_400():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1", "mode": "grad"})
        assert status == 400
        assert isinstance(body["error"], str)
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_unexpected_exception_is_400_not_500(monkeypatch):
    """The catch-all: if calc.evaluate ever raised something other than a
    CalcError, the endpoint must still answer 400, never a 500."""
    import graphcalc.calc as calc_module

    def _boom(expr, mode="rad"):
        raise RuntimeError("boom")

    monkeypatch.setattr(calc_module, "evaluate", _boom)
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 400
        assert isinstance(body["error"], str)
    finally:
        server.shutdown()
        server.server_close()
