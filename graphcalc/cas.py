"""CAS algebra core for POST /api/cas/simplify, /expand, /factor,
/derivative, /integral and /limit.

Plan step P19/S1 implemented simplify(expr); plan step P19/S2 added
expand(expr) next to it in this same module; plan step P19/S3 added
factor(expr) to complete that set. Plan step P20/S1 adds derivative(expr,
var) next to them. Plan step P20/S2 adds integral(expr, var, lower=None,
upper=None). Plan step P20/S3 adds limit(expr, var, point, dir=None).
Plan step P20/S4 teaches _parse_bound (used by both integral() and
limit()) to also accept an expression string such as "pi" or "oo" for
"lower"/"upper"/"point", not just a bare JSON number.
simplify(), expand(), factor(), derivative(), integral() and limit() are
the only things graphcalc/cli.py calls from here; neither they nor _parse
ever touches the network.

_parse(expr) turns `expr` into a sympy expression and is deliberately built
the same way graphcalc.calc.evaluate() parses its own input (plan steps
P23/S1, P24/S3, P27/S1, P27/S2): graphcalc.grammar.check_grammar rejects
anything outside this calculator's own grammar (Python comparison/bitwise/
shift/floor-division operators, a Python-only numeric literal, an extra
argument to a built-in unary function such as "sqrt(4,2)", and any
non-ASCII letter, digit or numeral) before sympy's own parse_expr ever sees
the string; graphcalc.grammar.normalize_numbers then rewrites a
grammar-accepted number literal such as "0005" into text Python's own
tokenizer can actually compile; and graphcalc.grammar.called_names is
checked against the same radians-mode whitelist graphcalc.calc._rad_names()
builds (pi, e, sqrt, sin, cos, tan, asin, acos, atan, ln, log, exp, abs), so
a call on a name this calculator does not know ("zeta(2)", the uppercase
"SIN(x)") is rejected with "unknown function '<name>'" before parse_expr
ever runs -- exactly the same check graphcalc.calc.evaluate applies, and for
the same reason: without it, parse_expr's own auto_symbol fallback would
silently turn the call into an implicit product instead of raising.

Unlike graphcalc.calc.evaluate, this module has no "rad"/"deg" mode (CAS
algebra needs no trig-angle convention to simplify "(x^2-1)/(x-1))") and no
stored ans/variables/functions/lists -- a CAS request carries no stored
state at all, the same "stateless, like _handle_stats_regression" shape
plan step P19's own planner notes describe. A name _parse leaves unbound
(any identifier not in the radians whitelist, e.g. "x") becomes a free
sympy Symbol via parse_expr's own auto_symbol transformation -- the exact
same fallback graphcalc.calc.evaluate already relies on for a function
definition's own parameter or an otherwise-undefined variable.

_parse does reuse one guard of graphcalc.calc.evaluate's: plan step P20/S1
(planner note "guard against hangs, as in P28") adds graphcalc.limits.
is_power_too_large's own check right where graphcalc.calc.evaluate runs it
(see that module's docstring for the full reason) -- after normalize_numbers,
before the real, evaluating parse_expr call. Without it, an `expr` such as
"9^9^9" would make *this* module's own parse_expr try to materialize a
~370-million-digit integer before any CAS operation ever got a chance to
run, exactly the Bug #20 hang P28 fixed for graphcalc.calc.evaluate. A
flagged `expr` raises CalcError(graphcalc.calc.DOMAIN_ERROR_TOO_LARGE) --
this module has no "domain_error" response field to set instead, unlike
evaluate's own 200-with-domain_error shape, so the flagged case becomes a
400 here, the same as any other CalcError this module raises. This also
closes a latent gap simplify/expand/factor (P19) never guarded against,
since every CAS operation shares this one _parse.

to_text(value) renders a sympy object with sympy's own str() printer, then
replaces "**" with "^" -- this calculator's own output power notation.
graphcalc.calc.to_caret does the same replace, but on an already-str exact
value rather than a sympy object fresh out of simplify()/expand()/factor();
to_text is its own small function here, as this plan step's own spec asks
for, rather than making every caller str() the value first just to reuse
to_caret.

Parse failures -- a GrammarError from check_grammar, an unknown function
call, or anything parse_expr itself rejects -- all raise graphcalc.calc.
CalcError, never any other exception, so graphcalc/cli.py's handlers can
catch exactly that one type and turn it into the usual JSON 400, the same
"never a 500" rule every other math-performing route already follows.

_parse_bound(value, name) (plan steps P20/S2, P20/S4) turns a POST body's
"lower"/"upper"/"point" value into an exact sympy object for integral()'s
definite-integral form and limit()'s own point. A JSON number: bool is
rejected even though Python's bool is an int subclass (True/False are not
valid bounds), and a float NaN or infinity is rejected the same way a
non-finite "start"/"step" is rejected elsewhere in this codebase
(graphcalc.graph.table). A plain int becomes an exact sympy.Integer; a
float is handed to sympy.nsimplify(..., rational=True) so e.g. 0.5 comes
back as the exact Rational 1/2 instead of the ugly binary fraction
float(0.5) actually is -- "the results stay exact" the same way every
other CAS operation's result is exact.

Plan step P20/S4 adds a string `value`: an expression such as "pi", "oo"
or "-oo". "oo"/"+oo"/"-oo" and the spelled-out "infinity"/"+infinity"/
"-infinity" (stripped of surrounding whitespace first) are mapped
straight to sympy.oo/-oo via a small lookup table, _INFINITY_TOKENS,
rather than being run through _parse: "oo" is not one of _rad_names()'s
whitelisted names, so _parse("oo") would otherwise turn it into a free
Symbol('oo') via parse_expr's own auto_symbol fallback, not sympy's
actual infinity. Any other string is run through this module's own
_parse -- the same grammar/whitelist every CAS operation's own "expr"
goes through, so "pi" and "e" resolve via _rad_names() to sympy.pi/E and
"2*pi" to the product, and the P20/S1 power-size guard inside _parse
still applies to a bound string too. The parsed result must then have no
free symbols -- "y" parses fine as a bare Symbol but is not a number, so
it is rejected the same as any other invalid bound -- which is also why
a bound given as the empty string raises CalcError: _parse itself
rejects an empty/whitespace-only string before free_symbols is ever
checked. Any other type (list, dict, None, ...) still raises CalcError
naming `name` (e.g. "lower", "upper", "point") so the caller's error
message says which parameter was bad.

limit(expr, var, point, dir=None) (plan step P20/S3) parses `point` with
_parse_bound (the same JSON-number-only rule described above) and runs
sympy.limit() with respect to `var`. `dir` is None (two-sided, sympy's own
dir="+-"), "+" or "-"; any other value -- including a non-string such as
5 -- raises CalcError before `expr` is even parsed. sympy.limit() itself
sometimes raises (e.g. a ValueError for "sign(x)" at 0, where the two
one-sided limits disagree) and sometimes just returns sympy's own zoo
(complex infinity) or nan (e.g. the two-sided limit of "1/x" at 0, which
sympy evaluates to zoo without raising); both are translated into
CalcError here, never left to reach graphcalc/cli.py as anything but the
usual JSON 400. A real infinity (sympy.oo/-oo) is a legitimate answer --
e.g. the one-sided limit of "1/x" at 0 with dir="+" -- and renders as
"oo"/"-oo" through the same to_text() every other CAS result uses.
"""

import math

from sympy import Integer, Symbol, nan, oo, zoo
from sympy import Integral as _sympy_Integral
from sympy import diff as _sympy_diff
from sympy import expand as _sympy_expand
from sympy import factor as _sympy_factor
from sympy import integrate as _sympy_integrate
from sympy import limit as _sympy_limit
from sympy import nsimplify
from sympy import simplify as _sympy_simplify
from sympy.parsing.sympy_parser import parse_expr

from graphcalc.calc import (
    _GLOBAL_DICT,
    _TRANSFORMATIONS,
    DOMAIN_ERROR_TOO_LARGE,
    CalcError,
    _rad_names,
)
from graphcalc.grammar import GrammarError, called_names, check_grammar, normalize_numbers
from graphcalc.limits import is_power_too_large


def _parse(expr: str):
    """Parse `expr` into a sympy expression, raising CalcError on failure.

    See this module's own docstring for the full grammar/whitelist rule;
    this is the one parsing step every CAS operation (simplify, and later
    expand/factor) shares.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise CalcError("missing parameter: expr")
    try:
        check_grammar(expr)
    except GrammarError as exc:
        raise CalcError(str(exc)) from exc
    expr = normalize_numbers(expr)
    if is_power_too_large(expr):
        raise CalcError(DOMAIN_ERROR_TOO_LARGE)
    local_dict = _rad_names()
    for name in called_names(expr):
        if name not in local_dict:
            raise CalcError(f"unknown function '{name}'")
    try:
        return parse_expr(
            expr,
            transformations=_TRANSFORMATIONS,
            global_dict=_GLOBAL_DICT,
            local_dict=local_dict,
        )
    except CalcError:
        raise
    except Exception as exc:
        raise CalcError(f"invalid expression: {expr}") from exc


def to_text(value) -> str:
    """Render a sympy object with "^" for power instead of sympy's own "**"."""
    return str(value).replace("**", "^")


def simplify(expr: str) -> str:
    """Parse `expr`, run sympy.simplify() on it, and return the "^"-notation
    text of the result (plan step P19/S1).

    e.g. simplify("(x^2-1)/(x-1)") -> "x + 1". Raises CalcError for a
    malformed `expr`, never any other exception.
    """
    parsed = _parse(expr)
    return to_text(_sympy_simplify(parsed))


def expand(expr: str) -> str:
    """Parse `expr`, run sympy.expand() on it, and return the "^"-notation
    text of the result (plan step P19/S2).

    e.g. expand("(x+1)^2") -> "x^2 + 2*x + 1". Raises CalcError for a
    malformed `expr`, never any other exception.
    """
    parsed = _parse(expr)
    return to_text(_sympy_expand(parsed))


def factor(expr: str) -> str:
    """Parse `expr`, run sympy.factor() on it, and return the "^"-notation
    text of the result (plan step P19/S3).

    e.g. factor("x^2-5x+6") -> "(x - 3)*(x - 2)". Raises CalcError for a
    malformed `expr`, never any other exception.
    """
    parsed = _parse(expr)
    return to_text(_sympy_factor(parsed))


def derivative(expr: str, var: str) -> str:
    """Parse `expr`, run sympy.diff() on it with respect to `var`, and
    return the "^"-notation text of the result (plan step P20/S1).

    e.g. derivative("x*sin(x)", "x") -> "x*cos(x) + sin(x)". `var` must be
    a plain ASCII identifier string (e.g. "x", not "x+1", "2" or a non-ASCII
    letter) -- the same shape graphcalc.grammar.check_grammar already
    requires of every identifier `expr` itself may contain -- anything else
    raises CalcError before `expr` is even parsed. A malformed `expr`, or
    any other sympy failure, also raises CalcError, never any other
    exception.
    """
    if not isinstance(var, str) or not var.isascii() or not var.isidentifier():
        raise CalcError(f"invalid variable: {var!r}")
    parsed = _parse(expr)
    try:
        result = _sympy_diff(parsed, Symbol(var))
        return to_text(result)
    except CalcError:
        raise
    except Exception as exc:
        raise CalcError(f"invalid expression: {expr}") from exc


# Plan step P20/S4: exact spellings mapped straight to sympy infinity,
# checked (after stripping surrounding whitespace) before any string bound
# is ever handed to _parse -- see this module's own docstring for why "oo"
# itself must not fall through to _parse (it is not one of _rad_names()'s
# whitelisted names, so _parse would otherwise turn it into a free
# Symbol('oo') instead of sympy's actual infinity).
_INFINITY_TOKENS = {
    "oo": oo,
    "+oo": oo,
    "-oo": -oo,
    "infinity": oo,
    "+infinity": oo,
    "-infinity": -oo,
}


def _parse_bound(value, name: str):
    """Turn a POST body's `value` for "lower"/"upper"/"point" into an exact
    sympy object, raising CalcError on failure (plan steps P20/S2, P20/S4).
    See this module's own docstring for the full rule: a JSON int or float
    (bool and non-finite float -- NaN, +-inf -- are rejected), or a string
    expression such as "pi", "2*pi", "e", "oo" or "-oo", parsed through
    _INFINITY_TOKENS or, failing that, _parse itself, then required to have
    no free symbols. Any other type raises CalcError naming `name` (e.g.
    "lower", "upper", "point") so the caller's error message says which
    parameter was bad.
    """
    if isinstance(value, bool):
        raise CalcError(f"invalid {name}: {value!r}")
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise CalcError(f"invalid {name}: {value!r}")
        return nsimplify(value, rational=True)
    if isinstance(value, int):
        return Integer(value)
    if isinstance(value, str):
        token = value.strip()
        if token in _INFINITY_TOKENS:
            return _INFINITY_TOKENS[token]
        parsed = _parse(value)
        if parsed.free_symbols:
            raise CalcError(f"invalid {name}: {value!r}")
        return parsed
    raise CalcError(f"invalid {name}: {value!r}")


def integral(expr: str, var: str, lower=None, upper=None) -> str:
    """Parse `expr`, run sympy.integrate() on it with respect to `var`, and
    return the "^"-notation text of the result (plan step P20/S2).

    With neither `lower` nor `upper` given, returns the indefinite
    integral: integral("x^2", "x") -> "x^3/3". With both given, returns
    the definite integral: integral("x^2", "x", 0, 1) -> "1/3". Supplying
    exactly one of `lower`/`upper` raises CalcError -- a definite integral
    needs both ends or neither. Each bound is parsed by _parse_bound (see
    its own docstring for what it currently accepts). `var` must be a
    plain ASCII identifier string, the same rule derivative() already
    applies, checked before `expr` is even parsed. If sympy cannot find a
    closed form -- it would hand back an unevaluated sympy.Integral instead
    of a value -- this raises CalcError("no closed form") rather than
    echoing the input back as if it were an answer. A malformed `expr`, or
    any other sympy failure, also raises CalcError, never any other
    exception.
    """
    if not isinstance(var, str) or not var.isascii() or not var.isidentifier():
        raise CalcError(f"invalid variable: {var!r}")
    if (lower is None) != (upper is None):
        raise CalcError("integral needs both lower and upper, or neither")
    parsed = _parse(expr)
    symbol = Symbol(var)
    try:
        if lower is None:
            result = _sympy_integrate(parsed, symbol)
        else:
            lo = _parse_bound(lower, "lower")
            hi = _parse_bound(upper, "upper")
            result = _sympy_integrate(parsed, (symbol, lo, hi))
    except CalcError:
        raise
    except Exception as exc:
        raise CalcError(f"invalid expression: {expr}") from exc
    if result.has(_sympy_Integral):
        raise CalcError("no closed form")
    return to_text(result)


def limit(expr: str, var: str, point, dir=None) -> str:
    """Parse `expr`, run sympy.limit() on it with respect to `var` as it
    approaches `point`, and return the "^"-notation text of the result
    (plan step P20/S3).

    e.g. limit("sin(x)/x", "x", 0) -> "1" (the two-sided limit, sympy's own
    dir="+-"); limit("1/x", "x", 0, "+") -> "oo". `dir` must be None, "+"
    or "-" -- any other value, including a non-string such as 5, raises
    CalcError before `expr` is even parsed. `point` is parsed by
    _parse_bound (see its own docstring for what it currently accepts),
    the same helper integral() uses for "lower"/"upper". `var` must be a
    plain ASCII identifier string, the same rule derivative() and
    integral() already apply, checked before `expr` is even parsed. If
    sympy.limit() raises (e.g. the two one-sided limits disagree, as with
    "sign(x)" at 0) or hands back sympy's own zoo/nan instead of a value
    (e.g. the two-sided limit of "1/x" at 0), this raises CalcError("limit
    does not exist: ...") rather than echoing an undefined result as if it
    were an answer. A malformed `expr`, or any other sympy failure, also
    raises CalcError, never any other exception.
    """
    if not isinstance(var, str) or not var.isascii() or not var.isidentifier():
        raise CalcError(f"invalid variable: {var!r}")
    if dir is not None and dir not in ("+", "-"):
        raise CalcError(f"invalid dir: {dir!r}")
    parsed = _parse(expr)
    symbol = Symbol(var)
    pt = _parse_bound(point, "point")
    sympy_dir = dir if dir is not None else "+-"
    try:
        result = _sympy_limit(parsed, symbol, pt, dir=sympy_dir)
    except CalcError:
        raise
    except Exception as exc:
        raise CalcError(f"limit does not exist: {expr}") from exc
    if result == zoo or result == nan:
        raise CalcError(f"limit does not exist: {expr}")
    return to_text(result)
