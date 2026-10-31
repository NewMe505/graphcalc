"""Tests for the "mode" field on calc.evaluate / POST /api/calc/evaluate
(feature P4, plan step S3): angles in radians (the default) or degrees.

Covers: {"expr":"sin(30)","mode":"deg"} -> exact "1/2"; {"expr":"sin(pi/6)"}
(default mode, i.e. radians) -> exact "1/2"; {"expr":"asin(1/2)","mode":"deg"}
-> exact "30". In deg mode, sin/cos/tan multiply their argument by pi/180
before evaluating, and asin/acos/atan multiply their result by 180/pi,
all kept as exact sympy expressions (no float rounding). An invalid mode
(anything other than "rad" or "deg", e.g. "grad") answers 400 with a JSON
error -- never a 500.

Each case is checked both directly against calc.evaluate (no HTTP) and
over POST /api/calc/evaluate.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from graphcalc.calc import CalcError, evaluate
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


def test_evaluate_sin_30_deg_is_one_half():
    result = evaluate("sin(30)", mode="deg")
    assert result["exact"] == "1/2"
    assert result["decimal"] == "0.5"
    assert result["complex"] is None
    assert result["domain_error"] is None


def test_evaluate_sin_pi_over_6_default_mode_is_one_half():
    result = evaluate("sin(pi/6)")
    assert result["exact"] == "1/2"
    assert result["decimal"] == "0.5"


def test_evaluate_asin_one_half_deg_is_30():
    result = evaluate("asin(1/2)", mode="deg")
    assert result["exact"] == "30"
    assert result["decimal"] == "30"


def test_evaluate_cos_60_deg_is_one_half():
    result = evaluate("cos(60)", mode="deg")
    assert result["exact"] == "1/2"


def test_evaluate_tan_45_deg_is_one():
    result = evaluate("tan(45)", mode="deg")
    assert result["exact"] == "1"


def test_evaluate_acos_one_deg_is_zero():
    result = evaluate("acos(1)", mode="deg")
    assert result["exact"] == "0"


def test_evaluate_atan_one_deg_is_45():
    result = evaluate("atan(1)", mode="deg")
    assert result["exact"] == "45"


def test_evaluate_sin_pi_over_2_rad_mode_explicit_is_one():
    result = evaluate("sin(pi/2)", mode="rad")
    assert result["exact"] == "1"


def test_evaluate_invalid_mode_grad_raises_calc_error():
    with pytest.raises(CalcError):
        evaluate("sin(30)", mode="grad")


# ---- HTTP tests: the registered route ----


def test_api_calc_evaluate_sin_30_deg_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "sin(30)", "mode": "deg"})
        assert status == 200
        assert body["exact"] == "1/2"
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_sin_pi_over_6_default_mode_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "sin(pi/6)"})
        assert status == 200
        assert body["exact"] == "1/2"
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_asin_one_half_deg_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "asin(1/2)", "mode": "deg"})
        assert status == 200
        assert body["exact"] == "30"
    finally:
        server.shutdown()
        server.server_close()


def test_api_calc_evaluate_mode_grad_is_400_json_not_500():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "sin(30)", "mode": "grad"})
        assert status == 400
        assert isinstance(body["error"], str)
    finally:
        server.shutdown()
        server.server_close()
