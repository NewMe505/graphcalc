"""Tests for the rectangular complex form in calc.evaluate (feature P5, plan
step S1).

Covers: a non-real result's "complex" field is a dict {"real": str, "imag":
str}, each a 12-significant-digit string, while "exact" stays sympy's own
str() form -- "sqrt(-4)" gives exact "2*I" with complex {"real":"0",
"imag":"2"}; "ln(-1)" gives exact "I*pi" with complex {"real":"0",
"imag":"3.14159265359"}. A real expression (e.g. "2+3") keeps the existing
response shape: complex stays null. Checked both via calc.evaluate directly
and over HTTP through POST /api/calc/evaluate.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

from graphcalc.calc import evaluate
from graphcalc.cli import Handler


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


def test_evaluate_sqrt_negative_four_gives_rectangular_complex():
    result = evaluate("sqrt(-4)")
    assert result["exact"] == "2*I"
    assert result["decimal"] is None
    assert result["complex"] == {"real": "0", "imag": "2"}
    assert result["domain_error"] is None


def test_evaluate_ln_negative_one_gives_rectangular_complex():
    result = evaluate("ln(-1)")
    assert result["exact"] == "I*pi"
    assert result["decimal"] is None
    assert result["complex"] == {"real": "0", "imag": "3.14159265359"}
    assert result["domain_error"] is None


def test_evaluate_real_expression_keeps_complex_null():
    result = evaluate("2+3")
    assert result["exact"] == "5"
    assert result["decimal"] == "5"
    assert result["complex"] is None
    assert result["domain_error"] is None


# ---- HTTP tests: the registered route ----


def test_api_sqrt_negative_four_returns_rectangular_complex_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "sqrt(-4)"})
        assert status == 200
        assert body["exact"] == "2*I"
        assert body["complex"] == {"real": "0", "imag": "2"}
    finally:
        server.shutdown()
        server.server_close()


def test_api_ln_negative_one_returns_rectangular_complex_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "ln(-1)"})
        assert status == 200
        assert body["exact"] == "I*pi"
        assert body["complex"] == {"real": "0", "imag": "3.14159265359"}
    finally:
        server.shutdown()
        server.server_close()


def test_api_real_expression_keeps_complex_null_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "2+3"})
        assert status == 200
        assert body["exact"] == "5"
        assert body["complex"] is None
    finally:
        server.shutdown()
        server.server_close()
