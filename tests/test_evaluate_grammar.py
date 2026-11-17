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
import re
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from graphcalc.calc import CalcError, evaluate
from graphcalc.cli import Handler
from graphcalc.grammar import GrammarError, _tokenize, check_grammar, normalize_numbers


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


# ---- P29/S1: a number is read as the longest run of digits and dots ----
#
# Owner revision (2026-11-15): "1.2.3", "1..2" and "1.5e3.2" must each
# tokenize as exactly ONE NUMBER token (never two NUMBER tokens read as an
# implied product, e.g. "1.2.3" misread as "1.2 * .3"), which then fails
# the unchanged _STRICT_NUMBER_RE check as a single bad literal. The
# GrammarError message is asserted to *quote the whole literal back*,
# which is only possible if the tokenizer handed check_grammar one token
# covering the full text, not two shorter ones.


def test_p29_longest_run_dotted_literal_is_one_bad_number():
    with pytest.raises(GrammarError, match=re.escape("'1.2.3'")):
        check_grammar("1.2.3")


def test_p29_longest_run_double_dot_is_one_bad_number():
    with pytest.raises(GrammarError, match=re.escape("'1..2'")):
        check_grammar("1..2")


def test_p29_longest_run_dotted_exponent_is_one_bad_number():
    with pytest.raises(GrammarError, match=re.escape("'1.5e3.2'")):
        check_grammar("1.5e3.2")


def test_p29_reject_malformed_bare_dot():
    with pytest.raises(GrammarError, match=re.escape("'.'")):
        check_grammar(".")


def test_p29_reject_malformed_double_dot():
    with pytest.raises(GrammarError, match=re.escape("'1..2'")):
        check_grammar("1..2")


def test_p29_reject_malformed_three_part_dotted():
    with pytest.raises(GrammarError, match=re.escape("'1.2.3'")):
        check_grammar("1.2.3")


def test_p29_longest_run_never_two_numbers_multiplied():
    # A tokenizer that (incorrectly) split "1.2.3" into two NUMBER tokens
    # ("1.2" and ".3") would let check_grammar through clean, since each
    # piece alone passes _STRICT_NUMBER_RE -- it is read as the implied
    # product "1.2 * .3". Pin that this never happens: check_grammar must
    # raise, not silently accept, for all three owner-revision inputs.
    for bad in ("1.2.3", "1..2", "1.5e3.2"):
        with pytest.raises(GrammarError):
            check_grammar(bad)


def test_p29_longest_run_malformed_tokenizes_as_single_number_token():
    # Directly pins the tokenizer-level claim the plan step asks for: each
    # input is exactly one NUMBER token, not NUMBER followed by another
    # NUMBER (which is what "implied multiplication of two numbers" would
    # require).
    for bad in ("1.2.3", "1..2", "1.5e3.2", "."):
        tokens = list(_tokenize(bad))
        assert len(tokens) == 1, f"{bad!r} -> {tokens}"
        assert tokens[0][0] == "NUMBER"
        assert tokens[0][1] == bad


# ---- P29/S1 regression: must keep working exactly as before ----


def test_p29_regression_implied_mult_digit_then_name_still_evaluates():
    status, body = _evaluate_over_http("2x", setup=("x:=5",))
    assert status == 200
    assert body["exact"] == "10"


def test_p29_regression_implied_mult_digit_then_constant_still_symbolic():
    status, body = _evaluate_over_http("2pi")
    assert status == 200
    assert body["exact"] == "2*pi"


def test_p29_regression_hex_literal_still_400():
    _assert_rejected("0x10")


def test_p29_regression_underscore_literal_still_400():
    _assert_rejected("1_000")


def test_p29_regression_imaginary_j_literal_still_400():
    _assert_rejected("2j")


def test_p29_regression_unicode_digit_still_400():
    with pytest.raises(GrammarError):
        check_grammar("２+２")  # U+FF12 FULLWIDTH DIGIT TWO, twice


# ---- P29/S2: '.5' and '5.' accepted, as on a TI (owner revision,
# 2026-11-14/2026-11-15) ----
#
# check_grammar's _STRICT_NUMBER_RE now accepts a bare leading dot (".5"),
# a bare trailing dot ("5."), and a leading-zero digit run ("0005") -- none
# of those raise GrammarError any more. normalize_numbers then rewrites
# each of those three accepted shapes into ordinary Python-safe
# digits-point-digits text ("0.5", "5.0", "5") before parse_expr ever sees
# it, since Python's own tokenizer -- unlike this grammar -- rejects a
# leading-zero integer literal outright. Malformed input stays rejected by
# check_grammar exactly as pinned by the P29/S1 tests above, and
# normalize_numbers leaves a string it is never actually asked to rewrite
# (one check_grammar would have already rejected) unchanged rather than
# mangling it.


def test_p29_accept_leading_dot_check_grammar():
    check_grammar(".5")  # must not raise


def test_p29_accept_trailing_dot_check_grammar():
    check_grammar("5.")  # must not raise


def test_p29_accept_leading_zero_check_grammar():
    check_grammar("0005")  # must not raise


def test_p29_accept_implied_mult_leading_dot_check_grammar():
    check_grammar(".5x")  # must not raise -- implied multiplication intact


def test_p29_accept_still_rejects_malformed_bare_dot():
    with pytest.raises(GrammarError, match=re.escape("'.'")):
        check_grammar(".")


def test_p29_accept_still_rejects_python_only_literals():
    for bad in ("0x10", "1_000", "2j"):
        with pytest.raises(GrammarError):
            check_grammar(bad)


def test_p29_accept_normalize_leading_dot():
    assert normalize_numbers(".5") == "0.5"


def test_p29_accept_normalize_trailing_dot():
    assert normalize_numbers("5.") == "5.0"


def test_p29_accept_normalize_leading_zero():
    assert normalize_numbers("0005") == "5"


def test_p29_accept_normalize_leading_zero_single_zero_stays_zero():
    assert normalize_numbers("00") == "0"


def test_p29_accept_normalize_leaves_ordinary_number_unchanged():
    assert normalize_numbers("5") == "5"
    assert normalize_numbers("3.14") == "3.14"


def test_p29_accept_normalize_mixed_expression():
    assert normalize_numbers(".5x + 2*.5 - 0005") == "0.5x + 2*0.5 - 5"


def test_p29_accept_normalize_leaves_malformed_literal_unchanged():
    # Never actually reached with real input (check_grammar rejects these
    # first), but normalize_numbers' own docstring promises a literal
    # outside _NUMBER_PARTS_RE's shape is returned as-is, not mangled.
    for bad in ("1.2.3", "1..2", "1.5e3.2"):
        assert normalize_numbers(bad) == bad


def test_p29_accept_evaluate_leading_dot():
    result = evaluate(".5")
    assert result["decimal"] == "0.5"


def test_p29_accept_evaluate_trailing_dot():
    result = evaluate("5.")
    assert result["decimal"] == "5"


def test_p29_accept_evaluate_leading_zero():
    result = evaluate("0005")
    assert result["exact"] == "5"


def test_p29_accept_evaluate_mixed_implied_mult():
    # Plan step P31 ("clean exact for decimals") strips the padding
    # sympy's own str(Float) would otherwise leave here -- "2" not
    # "2.00000000000000" -- since the result is a Float, not an Integer.
    status, body = _evaluate_over_http(".5x", setup=("x:=4",))
    assert status == 200
    assert body["exact"] == "2"


def test_p29_accept_evaluate_mixed_explicit_mult():
    # Same P31 cleanup as above: "1", not the padded "1.00000000000000".
    status, body = _evaluate_over_http("2*.5")
    assert status == 200
    assert body["exact"] == "1"


def _evaluate_over_http(expr, setup=()):
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        for prior in setup:
            status, body = _post(base, "/api/calc/evaluate", {"expr": prior})
            assert status == 200, f"setup {prior!r} -> status {status}, body {body}"
        return _post(base, "/api/calc/evaluate", {"expr": expr})
    finally:
        server.shutdown()
        server.server_close()
