"""Tests for graphcalc.grammar.check_grammar and its use by
graphcalc.calc.evaluate (plan step P23/S1 and S2, Bug #5 fix).

Before this fix, sympy's parse_expr -- built on Python's own tokenizer --
silently accepted a lot more than this calculator's grammar: Python
comparison operators (<, >, <=, >=, ==, !=), %, //, the bitwise/shift
operators (&, |, ~, <<, >>), Python-only numeric literals (0x10, 0b11, 0o7,
1_000, 2j, 3J), and an extra argument to a built-in unary function
(ln(e,2), sqrt(4,2), since sympy's own log(x, base) takes two). check_grammar
now rejects every one of those before parse_expr ever runs, and
graphcalc.calc.evaluate turns that rejection into the usual CalcError -> 400
over HTTP, never a 500.

The "test_grammar_operators_*" tests below are the newly-rejected cases
(every acceptance-criteria example PRODUCT.md's P23 lists: the eight
comparison/bitwise/shift operators, the six Python-only literals, and the
two extra-argument calls). The "test_grammar_literals_*" tests (plan step
S2) pin the same six Python-only-literal inputs (F2) under the naming that
step asks for, plus a guard that implied multiplication by a name starting
with "j"/"J" ("2job", "3Jane") -- the one case the literal check's "j"/"J"
suffix could have broken -- and by an ordinary name ("2x", "2y", defined or
left symbolic) still evaluates. The "test_grammar_regression_*" tests pin
what must keep working exactly as before: "1 = = 2", "1==2", "1 != 2",
"(1,2)" and "{1:2}" still answer 400 (just as they did before this fix, via
a different path -- see graphcalc.grammar's module docstring for why a bare
"=" is allowed at the token level), "5!" still evaluates to exact "120",
and "a:=5" still defines the variable "a".
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from graphcalc.calc import CalcError, evaluate
from graphcalc.cli import Handler
from graphcalc.grammar import GrammarError, check_grammar


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


def _assert_rejected(expr):
    """POST {"expr": expr} and assert it answers 400 with a JSON error key."""
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": expr})
        assert status == 400, f"{expr!r} -> status {status}, body {body}"
        assert isinstance(body.get("error"), str), f"{expr!r} -> body {body}"
    finally:
        server.shutdown()
        server.server_close()


# ---- F1: Python comparison, modulo, floor-division, bitwise/shift operators ----


def test_grammar_operators_lt_is_400():
    _assert_rejected("1<2")


def test_grammar_operators_ge_is_400():
    _assert_rejected("2>=3")


def test_grammar_operators_mod_is_400():
    _assert_rejected("7%2")


def test_grammar_operators_floordiv_is_400():
    _assert_rejected("7//2")


def test_grammar_operators_bitand_is_400():
    _assert_rejected("2 & 3")


def test_grammar_operators_bitor_is_400():
    _assert_rejected("2 | 1")


def test_grammar_operators_bitnot_is_400():
    _assert_rejected("~1")


def test_grammar_operators_lshift_is_400():
    _assert_rejected("1<<2")


# ---- Python-only numeric literals: hex, bin, oct, underscore grouping, j/J ----


def test_grammar_operators_hex_literal_is_400():
    _assert_rejected("0x10")


def test_grammar_operators_bin_literal_is_400():
    _assert_rejected("0b11")


def test_grammar_operators_oct_literal_is_400():
    _assert_rejected("0o7")


def test_grammar_operators_underscore_literal_is_400():
    _assert_rejected("1_000")


def test_grammar_operators_imaginary_lower_j_is_400():
    _assert_rejected("2j")


def test_grammar_operators_imaginary_upper_j_is_400():
    _assert_rejected("3J")


# ---- extra arguments to a built-in unary function ----


def test_grammar_operators_ln_extra_argument_is_400():
    _assert_rejected("ln(e,2)")


def test_grammar_operators_sqrt_extra_argument_is_400():
    _assert_rejected("sqrt(4,2)")


# ---- F3: extra arguments to a unary function (plan step S3), under the
# "test_grammar_arity_*" naming that step asks for -- same two inputs the
# "test_grammar_operators_*" tests above already cover, deliberately
# redundant, plus the guard test S3 calls for that a single-argument call
# still evaluates once the arity check is in place. ----


def test_grammar_arity_ln_extra_argument_is_400():
    _assert_rejected("ln(e,2)")


def test_grammar_arity_sqrt_extra_argument_is_400():
    _assert_rejected("sqrt(4,2)")


def test_grammar_arity_sqrt_single_argument_still_evaluates():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "sqrt(4)"})
        assert status == 200
        assert body["exact"] == "2"
    finally:
        server.shutdown()
        server.server_close()


# ---- F2: Python-only numeric literals (plan step S2), one test per input ----
#
# These pin check_grammar's literal rejection under the "test_grammar_literals_*"
# names plan step S2 asks for, one per F2 acceptance-criteria input (the
# test_grammar_operators_* tests above already covered the same six inputs
# as part of F1's broader sweep -- these are kept too, deliberately
# redundant, since the plan step calls for this exact naming).


def test_grammar_literals_hex_is_400():
    _assert_rejected("0x10")


def test_grammar_literals_bin_is_400():
    _assert_rejected("0b11")


def test_grammar_literals_oct_is_400():
    _assert_rejected("0o7")


def test_grammar_literals_underscore_is_400():
    _assert_rejected("1_000")


def test_grammar_literals_imaginary_lower_j_is_400():
    _assert_rejected("2j")


def test_grammar_literals_imaginary_upper_j_is_400():
    _assert_rejected("3J")


# ---- F2 guard: the literal checks above must not break implied multiplication ----
#
# check_grammar's NUMBER token swallows a trailing "j"/"J" only when no
# identifier character follows (see the module docstring and the NUMBER
# pattern's "(?!\\w)" lookahead) -- otherwise "2job" or "3Jane" would get
# misread as the rejected literal "2j"/"3J" plus a stray identifier, instead
# of "2"/"3" times a name that happens to start with "j"/"J". These guard
# tests pin that "2x"-style implied multiplication still evaluates, for a
# defined variable and for a left-undefined (symbolic) one, after the F2
# literal checks above.


def test_grammar_literals_implied_mult_defined_symbol_still_evaluates():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "x:=5"})
        assert status == 200
        assert body["exact"] == "5"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "2x"})
        assert status == 200
        assert body["exact"] == "10"
    finally:
        server.shutdown()
        server.server_close()


def test_grammar_literals_implied_mult_symbolic_name_still_evaluates():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "2y"})
        assert status == 200
        assert body["exact"] == "2*y"
        assert body["decimal"] is None
    finally:
        server.shutdown()
        server.server_close()


def test_check_grammar_accepts_implied_mult_name_starting_with_j():
    # Without the "(?!\w)" lookahead on NUMBER's "j"/"J" suffix, this would
    # be misread as the rejected literal "2j" plus a stray "ob" identifier.
    check_grammar("2job")  # must not raise


def test_check_grammar_accepts_implied_mult_name_starting_with_capital_j():
    check_grammar("3Jane")  # must not raise


# ---- F4 regression: must still be rejected, exactly as before this fix ----


def test_grammar_regression_spaced_double_equals_is_400():
    _assert_rejected("1 = = 2")


def test_grammar_regression_double_equals_is_400():
    _assert_rejected("1==2")


def test_grammar_regression_not_equal_is_400():
    _assert_rejected("1 != 2")


def test_grammar_regression_bare_tuple_is_400():
    _assert_rejected("(1,2)")


def test_grammar_regression_bare_dict_is_400():
    _assert_rejected("{1:2}")


# ---- F4 regression: must still work, exactly as before this fix ----


def test_grammar_regression_factorial_still_120():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "5!"})
        assert status == 200
        assert body["exact"] == "120"
    finally:
        server.shutdown()
        server.server_close()


def test_grammar_regression_definition_still_defines_a():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
        assert status == 200
        assert body["exact"] == "5"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "a"})
        assert status == 200
        assert body["exact"] == "5"
    finally:
        server.shutdown()
        server.server_close()


# ---- unit tests: graphcalc.grammar.check_grammar directly, no HTTP ----


def test_check_grammar_accepts_factorial():
    check_grammar("5!")  # must not raise


def test_check_grammar_accepts_top_level_definition_syntax():
    check_grammar("a:=5")  # must not raise -- ":=" stays allowed


def test_check_grammar_accepts_implied_multiplication():
    check_grammar("2(x+1)")  # must not raise


def test_check_grammar_rejects_lshift():
    with pytest.raises(GrammarError):
        check_grammar("1<<2")


def test_check_grammar_rejects_hex_literal():
    with pytest.raises(GrammarError):
        check_grammar("0x10")


def test_check_grammar_rejects_extra_argument_to_sqrt():
    with pytest.raises(GrammarError):
        check_grammar("sqrt(4,2)")


def test_check_grammar_allows_multi_arg_call_to_non_builtin_name():
    check_grammar("f(1,2)")  # "f" is not one of the restricted unary built-ins


# ---- unit tests: calc.evaluate raises CalcError (never GrammarError) ----


def test_evaluate_raises_calc_error_for_hex_literal():
    with pytest.raises(CalcError):
        evaluate("0x10")


def test_evaluate_raises_calc_error_for_floordiv():
    with pytest.raises(CalcError):
        evaluate("7//2")


def test_evaluate_raises_calc_error_for_sqrt_extra_argument():
    with pytest.raises(CalcError):
        evaluate("sqrt(4,2)")
