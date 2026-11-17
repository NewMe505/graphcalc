"""CAS algebra core for POST /api/cas/simplify, /expand and /factor.

Plan step P19/S1 implemented simplify(expr); plan step P19/S2 adds
expand(expr) next to it in this same module. factor() is left for a later
plan step to add. simplify() and expand() are the only things graphcalc/
cli.py calls from here so far; neither they nor _parse ever touches the
network.

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
algebra needs no trig-angle convention to simplify "(x^2-1)/(x-1))"), no
stored ans/variables/functions/lists, and no is_power_too_large freeze
guard -- a CAS request carries no stored state at all, the same "stateless,
like _handle_stats_regression" shape plan step P19's own planner notes
describe. A name _parse leaves unbound (any identifier not in the radians
whitelist, e.g. "x") becomes a free sympy Symbol via parse_expr's own
auto_symbol transformation -- the exact same fallback graphcalc.calc.
evaluate already relies on for a function definition's own parameter or an
otherwise-undefined variable.

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

from sympy import expand as _sympy_expand
from sympy import simplify as _sympy_simplify
from sympy.parsing.sympy_parser import parse_expr

from graphcalc.calc import _GLOBAL_DICT, _TRANSFORMATIONS, CalcError, _rad_names
from graphcalc.grammar import GrammarError, called_names, check_grammar, normalize_numbers


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
