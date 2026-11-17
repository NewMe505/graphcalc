"""CAS algebra core for POST /api/cas/simplify, /expand, /factor and
/derivative.

Plan step P19/S1 implemented simplify(expr); plan step P19/S2 added
expand(expr) next to it in this same module; plan step P19/S3 added
factor(expr) to complete that set. Plan step P20/S1 adds derivative(expr,
var) next to them. simplify(), expand(), factor() and derivative() are the
only things graphcalc/cli.py calls from here; neither they nor _parse ever
touches the network.

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
"""

from sympy import Symbol
from sympy import diff as _sympy_diff
from sympy import expand as _sympy_expand
from sympy import factor as _sympy_factor
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
