"""Tests for domain_error detection in calc.evaluate (feature P5, plan step
S2).

Covers: a result with no value -- zoo/oo/-oo from a division (1/0) or nan
from an indeterminate form (0/0) -- returns 200 with exact, decimal and
complex all None and a domain_error string. "division by zero" for zoo
(1/0); a non-null message for nan (0/0). A successful evaluation (1+1)
keeps domain_error None. Checked both via calc.evaluate directly and over
HTTP through POST /api/calc/evaluate.
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


def test_evaluate_division_by_zero_gives_domain_error():
    result = evaluate("1/0")
    assert result["exact"] is None
    assert result["decimal"] is None
    assert result["complex"] is None
    assert result["domain_error"] == "division by zero"


def test_evaluate_zero_over_zero_gives_nonnull_domain_error():
    result = evaluate("0/0")
    assert result["exact"] is None
    assert result["decimal"] is None
    assert result["complex"] is None
    assert result["domain_error"] is not None


def test_evaluate_success_keeps_domain_error_null():
    result = evaluate("1+1")
    assert result["exact"] == "2"
    assert result["decimal"] == "2"
    assert result["domain_error"] is None


# ---- HTTP tests: the registered route ----


def test_api_division_by_zero_returns_domain_error_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1/0"})
        assert status == 200
        assert body["exact"] is None
        assert body["decimal"] is None
        assert body["complex"] is None
        assert body["domain_error"] == "division by zero"
    finally:
        server.shutdown()
        server.server_close()


def test_api_zero_over_zero_returns_nonnull_domain_error_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "0/0"})
        assert status == 200
        assert body["exact"] is None
        assert body["decimal"] is None
        assert body["complex"] is None
        assert body["domain_error"] is not None
    finally:
        server.shutdown()
        server.server_close()


def test_api_success_keeps_domain_error_null_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200
        assert body["exact"] == "2"
        assert body["domain_error"] is None
    finally:
        server.shutdown()
        server.server_close()
