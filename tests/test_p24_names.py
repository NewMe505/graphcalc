"""Tests for multi-letter identifier handling (plan step P24/S1, Bug #7 fix).

Before this fix, graphcalc.calc._TRANSFORMATIONS used sympy's bundled
implicit_multiplication_application, whose first step is split_symbols:
any identifier not already in local_dict/global_dict gets broken into one
symbol per letter. That meant "rate" parsed as r*a*t*e, and because the
parser's own whitelist (graphcalc.calc._rad_names()) binds "e" to the
constant E, the split re-resolved that lone "e" letter into E -- so "rate"
evaluated to "E*a*r*t", "sec" to "E*c*s", "deg" to "E*d*g", and
"SIN(pi/2)" (not a whitelisted name) to "I*pi*N*S/2", none of which is what
a TI-Nspire CAS user typing a multi-letter name would expect.

The fix drops split_symbols entirely, keeping only implicit_multiplication,
implicit_application and function_exponentiation: a run of
letters/digits/underscores the calculator's own grammar.py tokenizer
already reads as a single IDENT token (grammar.py's _TOKEN_RE) is now
parsed as exactly one name too, mapped through _rad_names()/_deg_names()
when it is a whitelisted constant or function, through the caller-supplied
variables/functions/symbols dicts when it is user-defined, and otherwise
left as a single plain Symbol(name) -- never split into letters, so an
"e", "E" or "I" that merely happens to appear inside a longer name never
turns into a constant. Implicit multiplication between a number and the
identifier or call that follows it (2x, 2pi, 2sin(...)) is unaffected,
since that comes from implicit_multiplication/implicit_application, not
from split_symbols.
"""

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

from graphcalc.cli import Handler

# Matches a standalone "E" or "I" token -- sympy's own constant names for
# Euler's number and the imaginary unit -- but never one that is merely part
# of a longer identifier such as "SIN" (whose own "I" is just a letter of
# the name the user typed, not the constant).
_STANDALONE_E_OR_I_RE = re.compile(r"(?<![A-Za-z0-9_])[EI](?![A-Za-z0-9_])")


def _has_constant_e_or_i(exact):
    return _STANDALONE_E_OR_I_RE.search(exact) is not None


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


# ---- F1: a multi-letter name is one name, never split into letters ----


def test_p24_multiletter_rate_xy():
    status, body = _evaluate("rate")
    assert status == 200, body
    assert body["exact"] == "rate", body
    assert body["decimal"] is None, body

    status, body = _evaluate("xy")
    assert status == 200, body
    assert body["exact"] == "xy", body


def test_p24_multiletter_sec_deg_no_constant():
    # "sec" and "deg" are not in the calculator's whitelist (_rad_names()),
    # so each must come back as the plain name itself, with no stray "E"
    # (from a split-off "e") or "I" anywhere in the result.
    for expr in ("sec", "deg"):
        status, body = _evaluate(expr)
        assert status == 200, body
        assert body["exact"] == expr, body
        assert not _has_constant_e_or_i(body["exact"]), body
        assert body["complex"] is None, body


def test_p24_multiletter_rate_times_two_no_constant():
    status, body = _evaluate("rate*2")
    assert status == 200, body
    assert body["exact"] is not None
    assert not _has_constant_e_or_i(body["exact"]), body
    assert body["complex"] is None, body


def test_p24_uppercase_sin_400_or_no_constant():
    status, body = _evaluate("SIN(pi/2)")
    if status == 400:
        assert isinstance(body.get("error"), str), body
    else:
        assert status == 200, body
        assert body["exact"] is not None
        assert not _has_constant_e_or_i(body["exact"]), body


# ---- S2: a bare name that is also a sympy name/function/singleton is a
# plain Symbol, never resolved against sympy's own global namespace ----


def test_p24_bare_names_no_constant():
    # "sec" and "deg" are real sympy names (the secant function; degree
    # units), and "S", "N" and "Q" are real sympy singletons/functions (the
    # sympify shorthand, the numeric-evaluation function, the assumptions
    # object) -- none of them are in this calculator's own whitelist
    # (graphcalc.calc._rad_names()), and graphcalc.calc._GLOBAL_DICT never
    # hands parse_expr sympy's real global namespace, so each must come
    # back as the plain name itself: a free Symbol, not the sympy object of
    # the same spelling, and with no stray "E" or "I" constant from a
    # split-off letter (the P24/S1 bug this step guards against staying
    # fixed).
    for name in ("sec", "deg", "S", "N", "Q"):
        status, body = _evaluate(name)
        assert status == 200, body
        assert body["exact"] == name, body
        assert not _has_constant_e_or_i(body["exact"]), body
        assert body["decimal"] is None, body
        assert body["complex"] is None, body

    status, body = _evaluate("rate*2")
    assert status == 200, body
    assert body["exact"] == "2*rate", body
    assert not _has_constant_e_or_i(body["exact"]), body
    assert body["complex"] is None, body

    # "E" and "I" are the one pair of single-letter names this calculator
    # *does* whitelist on purpose (graphcalc.calc._rad_names()'s own "E" and
    # "I" entries) -- PRODUCT.md's P5 pins "sqrt(-4)" as exact "2*I" and
    # names.check_not_constant (tests/test_calc_definitions.py,
    # tests/test_p5_symbols_mode.py) already rejects "I:=3" and "E:=5" as
    # redefining a constant. P24's bug is "e, E or I *inside* a name" (e.g.
    # "rate", "SIN") silently becoming that constant -- never the bare name
    # typed on its own -- so a standalone "E" or "I" must keep resolving to
    # the real constant, not fall back to a plain Symbol.
    status, body = _evaluate("E")
    assert status == 200, body
    assert body["exact"] == "E", body
    assert body["decimal"] == "2.71828182846", body

    status, body = _evaluate("I")
    assert status == 200, body
    assert body["exact"] == "I", body
    assert body["complex"] == {"real": "0", "imag": "1"}, body


# ---- F4: implied multiplication by a number is kept ----


def test_p24_implicit_mult_kept():
    status, body = _evaluate("2x")
    assert status == 200, body
    assert body["exact"] == "2*x", body

    status, body = _evaluate("2pi")
    assert status == 200, body
    assert body["exact"] == "2*pi", body

    status, body = _evaluate("ln(e^2)")
    assert status == 200, body
    assert body["exact"] == "2", body

    status, body = _evaluate("2sin(pi/6)")
    assert status == 200, body
    assert body["exact"] == "1", body
