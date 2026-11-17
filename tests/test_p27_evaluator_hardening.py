"""Tests for the evaluate-path callable allowlist (plan step P27/S1, Bug #21).

Before this fix, graphcalc.calc.evaluate's pre-parse "unknown function"
check (graphcalc.grammar.called_names(expr) against local_dict) let a call
through whenever the name was also a key of _GLOBAL_DICT -- the small set
of sympy constructors (Integer, Float, Rational, Symbol, Function,
factorial) that parse_expr's own transformations (auto_number, auto_symbol,
factorial_notation) need to emit internally, never meant to be reachable by
name from user-typed text. That let a user bypass the calculator's own
grammar entirely by typing the constructor's name directly: "Integer(2)",
"Float(2)", "Rational(1,2)" and "factorial(5)" all evaluated successfully
instead of being rejected as calls on an unknown function.

The fix drops the "name not in _GLOBAL_DICT" half of that check, so a
called name must be in local_dict (the rad/deg whitelist, a stored variable
or function, a function definition's own param, or "ans") regardless of
whether it also happens to be a _GLOBAL_DICT key. _GLOBAL_DICT itself is
unchanged -- still passed to parse_expr as `global_dict` so the
transformations can still build an Integer/Float/Rational/Symbol/Function/
factorial object from a *generated* AST node (a bare number, a bare name, a
postfix "!") -- those code paths never run through called_names(expr) at
all, because called_names only ever sees a name the user actually typed
followed by "(" in the source text. That is why "5!" (factorial_notation's
own generated factorial(...) call) and "1/3+1/6" (Rational's own generated
calls) both still evaluate normally after this fix.
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


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def _evaluate_over_http(expr):
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        return _post(base, "/api/calc/evaluate", {"expr": expr})
    finally:
        server.shutdown()
        server.server_close()


# ---- F1: Integer(2), Float(2), Rational(1,2), factorial(5) are each a 400 ----


@pytest.mark.parametrize(
    "expr",
    ["Integer(2)", "Float(2)", "Rational(1,2)", "factorial(5)"],
)
def test_p27_constructors_rejected_by_evaluate_raise_calc_error(expr):
    with pytest.raises(CalcError):
        evaluate(expr)


@pytest.mark.parametrize(
    "expr",
    ["Integer(2)", "Float(2)", "Rational(1,2)", "factorial(5)"],
)
def test_p27_constructors_rejected_over_http_return_400_with_error_key(expr):
    status, body = _evaluate_over_http(expr)
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


# ---- F1: the legitimate paths that reach the same constructors still work ----


def test_p27_constructors_factorial_notation_still_gives_exact_120():
    result = evaluate("5!")
    assert result["exact"] == "120"
    assert result["domain_error"] is None


def test_p27_constructors_fraction_sum_still_gives_exact_one_half():
    result = evaluate("1/3+1/6")
    assert result["exact"] == "1/2"
    assert result["domain_error"] is None


def test_p27_constructors_factorial_notation_over_http_gives_exact_120():
    status, body = _evaluate_over_http("5!")
    assert status == 200, body
    assert body["exact"] == "120"


def test_p27_constructors_fraction_sum_over_http_gives_exact_one_half():
    status, body = _evaluate_over_http("1/3+1/6")
    assert status == 200, body
    assert body["exact"] == "1/2"


# ---- F2: a Unicode digit, letter or superscript/subscript is a 400 -------
#
# Plan step P27/S2, Bug #21 fix: Python's own "\w"/"\d" (what graphcalc.
# grammar._TOKEN_RE's IDENT/NUMBER groups are built on) are Unicode-aware,
# so without graphcalc.grammar._check_ascii_only these would otherwise all
# be silently *accepted* -- "２+２" as two NUMBER tokens, "٣+1" as a NUMBER
# plus "+1", "x²" as one IDENT token "x²" -- never reaching a rejection at
# all. See graphcalc.grammar._check_ascii_only's own docstring for exactly
# which Unicode categories/str. checks catch each case.


@pytest.mark.parametrize(
    "expr",
    ["２+２", "٣+1", "x²"],
)
def test_p27_unicode_expr_raises_calc_error(expr):
    with pytest.raises(CalcError):
        evaluate(expr)


def test_p27_unicode_expr_fullwidth_digit_is_400():
    # "２+２" -- U+FF12 FULLWIDTH DIGIT TWO, twice.
    status, body = _evaluate_over_http("２+２")
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


def test_p27_unicode_expr_arabic_indic_digit_is_400():
    # "٣+1" -- U+0663 ARABIC-INDIC DIGIT THREE, plus an ordinary ASCII "1".
    status, body = _evaluate_over_http("٣+1")
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


def test_p27_unicode_expr_superscript_is_400():
    # "x²" -- an ASCII "x" immediately followed by U+00B2 SUPERSCRIPT TWO,
    # which Python's own "\w" (and so the tokenizer's IDENT group) would
    # otherwise fold into one identifier token "x²".
    status, body = _evaluate_over_http("x²")
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


# ---- F2 (definitions): the same rejection for a defined name/param -------
#
# graphcalc.calc._DEFINITION_RE and _FUNCTION_DEFINITION_RE split a
# "name:=expr"/"f(params):=expr" definition's name (and params) off from
# its body *before* the body is ever handed to evaluate() -- so without
# re.ASCII on those two patterns, a non-ASCII character folded into the
# captured name/param (e.g. "x²", "a２") would never reach graphcalc.
# grammar's ASCII check at all, since that check only ever runs on the
# body. re.ASCII makes both patterns fail to match a non-ASCII name/param
# as a definition in the first place, so the whole original string falls
# through to a plain evaluate() call instead, which does reject it.


def test_p27_unicode_definition_superscript_in_name_is_400():
    status, body = _evaluate_over_http("x²:=4")
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


def test_p27_unicode_definition_fullwidth_digit_in_name_is_400():
    status, body = _evaluate_over_http("a２:=1")
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


def test_p27_unicode_function_definition_superscript_in_param_is_400():
    status, body = _evaluate_over_http("f(x²):=1")
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


def test_p27_unicode_rejected_definitions_do_not_change_stored_vars():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        for expr in ("x²:=4", "a２:=1", "f(x²):=1"):
            status, body = _post(base, "/api/calc/evaluate", {"expr": expr})
            assert status == 400, (expr, body)

        status, body = _get(base, "/api/calc/vars")
        assert status == 200, body
        assert body == {"variables": {}, "functions": {}}, body
    finally:
        server.shutdown()
        server.server_close()
