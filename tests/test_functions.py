"""Tests for graphcalc.calc.evaluate's function namespace (plan step S1 of
feature P4: sqrt, abs, ln, log (base 10) and postfix "!").

Covers: {"expr":"sqrt(8)"} -> exact "2*sqrt(2)"; {"expr":"5!"} -> exact
"120"; {"expr":"log(1000)"} -> exact "3" (log is base 10, simplified so the
result is an exact integer, not a fraction of logs); plus
{"expr":"abs(-3)"} -> exact "3" as a sanity check that the existing Abs
wiring still holds. Each case is checked both directly against
calc.evaluate (no HTTP) and over POST /api/calc/evaluate (no 500s).
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


def test_evaluate_sqrt_8_is_two_sqrt_two():
    result = evaluate("sqrt(8)")
    assert result["exact"] == "2*sqrt(2)"
    assert result["complex"] is None
    assert result["domain_error"] is None


def test_evaluate_five_factorial_is_120():
    result = evaluate("5!")
    assert result["exact"] == "120"
    assert result["decimal"] == "120"


def test_evaluate_log_1000_is_exactly_3():
    result = evaluate("log(1000)")
    assert result["exact"] == "3"
    assert result["decimal"] == "3"


def test_evaluate_abs_negative_3_is_3():
    result = evaluate("abs(-3)")
    assert result["exact"] == "3"
    assert result["decimal"] == "3"


# ---- HTTP tests: the registered route ----


def test_api_calc_evaluate_sqrt_8_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "sqrt(8)"})
        assert status == 200
        assert body["exact"] == "2*sqrt(2)"
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_five_factorial_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "5!"})
        assert status == 200
        assert body["exact"] == "120"
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_log_1000_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "log(1000)"})
        assert status == 200
        assert body["exact"] == "3"
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_abs_negative_3_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "abs(-3)"})
        assert status == 200
        assert body["exact"] == "3"
    finally:
        server.shutdown()
        server.server_close()
