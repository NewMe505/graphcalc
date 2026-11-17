"""Tests for scientific-notation decimals past 12 digits (plan step P25).

Before this fix, graphcalc.numfmt.format_decimal always printed in
fixed-point ("f") notation, rounded to 12 significant digits but never
switched to scientific notation for large magnitudes. Decimal's context
rounding keeps the original exponent, so a value like 2**100 (31 digits)
came back as "126765060023" followed by 19 literal zeros instead of the
12-significant-digit value a TI-Nspire CAS user would expect: the "." check
that strips trailing zeros for normal magnitudes never fires because a
whole number has no "." in its fixed-point text.

The fix: once the rounded Decimal's adjusted() exponent (the position of
its leading digit) reaches `sig` -- i.e. the value needs more than `sig`
digits before the decimal point -- format_decimal switches to scientific
notation instead: 12 significant digits, no trailing zeros in the
mantissa, lowercase "e", no "+" and no leading zeros in the exponent.
Magnitudes that still fit within `sig` integer digits are unaffected.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

from sympy import Integer, Rational

from graphcalc.cli import Handler
from graphcalc.numfmt import format_decimal


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
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


# ---- F1: {"expr":"2^100"} returns decimal "1.26765060023e30" ----


def test_p25_two_to_the_hundred_is_scientific_notation():
    status, body = _evaluate("2^100")
    assert status == 200, body
    assert body["decimal"] == "1.26765060023e30", body


# ---- unit tests on format_decimal directly ----


def test_format_decimal_two_to_the_hundred():
    # 2**100 == 1267650600228229401496703205376, a 31-digit integer.
    # Rounded to 12 significant digits: 126765060022|8... -> rounds up the
    # last kept digit (2 -> 3) because the next (13th) digit is 8.
    assert format_decimal(Integer(2) ** 100) == "1.26765060023e30"


def test_format_decimal_scientific_has_no_trailing_zeros_in_mantissa():
    # 1.2e15 has only two significant digits; the mantissa must not be
    # padded out to "1.20000000000e15".
    assert format_decimal(Integer(12) * Integer(10) ** 14) == "1.2e15"


def test_format_decimal_thirteen_digit_integer_is_scientific():
    # Exactly 13 digits (10**12) is already past the 12-digit threshold.
    assert format_decimal(Integer(10) ** 12) == "1e12"


def test_format_decimal_twelve_digit_integer_stays_fixed_point():
    # Exactly 12 digits must still print in fixed-point notation, since the
    # feature is specifically about values past 12 digits.
    value = Integer(10) ** 11  # "100000000000", 12 digits
    assert format_decimal(value) == "100000000000"


def test_format_decimal_negative_large_value_is_scientific():
    assert format_decimal(-(Integer(2) ** 100)) == "-1.26765060023e30"


def test_format_decimal_existing_small_values_unaffected():
    # Guard against a regression on the magnitudes format_decimal already
    # handled correctly before this fix.
    assert format_decimal(Rational(1, 2)) == "0.5"
    assert format_decimal(Rational(1, 3)) == "0.333333333333"
    assert format_decimal(Integer(32)) == "32"
    assert format_decimal(Integer(0)) == "0"
