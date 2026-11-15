"""Tests for clean decimal `exact` values (plan step P31, owner revision
2026-11-14: "clean exact for decimals").

Before this fix, graphcalc.calc.evaluate's `exact` field for a decimal
literal was built from plain str(result). sympy's own str() of a Float
pads the mantissa out to the value's working precision (15 decimal digits
by default), so {"expr": "1.5"} reported exact "1.50000000000000" instead
of the clean "1.5" a TI-Nspire CAS user typed, and {"expr": "1e5"} reported
exact "100000.000000000" instead of "100000".

The fix: graphcalc.numfmt.clean_float_exact(value) strips the trailing
fractional zeros (and the trailing "." for an integral value) from a
sympy Float's str(), and graphcalc.calc.evaluate uses it for `exact` only
when the result is actually a Float (plan step P31/S1). A result that is
not a Float -- a Rational such as "1/3", an Integer such as 10**1000, a
symbolic expression -- keeps plain str(result) exactly as before, so
"1/3" still reports exact "1/3" and 10**1000 still reports decimal
"1e1000" (plan step P25's scientific-notation threshold, unaffected since
10**1000 is an Integer, never a Float).
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

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


def _evaluate(expr):
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        return _post(base, "/api/calc/evaluate", {"expr": expr})
    finally:
        server.shutdown()
        server.server_close()


# ---- F1: {"expr":"1.5"} returns exact "1.5" and decimal "1.5";
#          {"expr":"1e5"} returns exact "100000" ----


def test_p31_decimal_exact_clean():
    status, body = _evaluate("1.5")
    assert status == 200, body
    assert body["exact"] == "1.5", body
    assert body["decimal"] == "1.5", body


def test_p31_scientific_exact_integer():
    status, body = _evaluate("1e5")
    assert status == 200, body
    assert body["exact"] == "100000", body


# ---- F2: {"expr":"1/3"} still returns exact "1/3" ----


def test_p31_rational_exact_fraction():
    status, body = _evaluate("1/3")
    assert status == 200, body
    assert body["exact"] == "1/3", body


# ---- regression: a huge Integer result keeps its P25 scientific decimal ----


def test_p31_rational_bigint_decimal_unchanged():
    status, body = _evaluate("10^1000")
    assert status == 200, body
    assert body["decimal"] == "1e1000", body
