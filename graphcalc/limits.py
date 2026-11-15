"""Pre-evaluation power-size guard for graphcalc.calc.evaluate (plan step
P28/S1, Bug #20 fix).

sympy's parse_expr evaluates `base**exponent` the instant it builds that AST
node (unless told not to) -- so a right-associative power tower such as
"9^9^9" (parsed as 9**(9**9), ~369,671,667 decimal digits) or "10^10^10"
(10**(10**10), 10,000,000,000 digits) makes parse_expr itself try to
materialize an exact integer with hundreds of millions, or billions, of
digits before graphcalc.calc.evaluate ever gets a chance to look at the
result. That can take minutes, hours, or effectively forever, and this
calculator's HTTP server (graphcalc.cli) handles one request at a time, so
every other request -- even an unrelated "1+1" -- would be stuck waiting
behind it.

is_power_too_large(expr) is graphcalc.calc.evaluate's guard against exactly
that: it parses `expr` a second time with evaluate=False, so sympy builds
the Add/Mul/Pow tree for the *literal text* without doing any of the actual
exponentiation -- not even the comparatively cheap inner step of a tower,
such as 9**9 -- then walks every Pow node the tree contains, however deeply
nested, estimating the decimal digit count of that node's own result from
float log10 arithmetic alone (see _log10_abs below). evaluate() calls this
before its own real, evaluating parse_expr call, and returns a domain_error
instead of ever making that call when this returns True.

This module intentionally knows nothing about graphcalc.calc's whitelist of
names (_rad_names/_deg_names), stored variables/functions, or "ans": its own
parse_expr call passes no local_dict at all, so any identifier -- a
built-in function name, a stored variable, "ans", or a name that is not
defined at all -- simply becomes a free Symbol (or an un-whitelisted
Function call) in the parsed tree. _log10_abs treats every such node as
"unknown", which this guard always allows through unflagged (the same rule
the plan step itself asks for: "any non-numeric or symbolic part" is
unknown, and unknown is always allowed) -- the real grammar/whitelist
checks still run, unchanged, inside graphcalc.calc.evaluate itself; this
module never accepts or rejects a name, only ever a *size*.
"""

import math

from sympy import Add, Basic, Float, Function, Integer, Mul, Pow, Rational, Symbol, factorial
from sympy.parsing.sympy_parser import (
    convert_xor,
    factorial_notation,
    function_exponentiation,
    implicit_application,
    implicit_multiplication,
    parse_expr,
    standard_transformations,
)

# A second copy of graphcalc.calc._TRANSFORMATIONS, not an import of it:
# graphcalc.calc imports this module (to call is_power_too_large below), so
# importing calc.py's tuple back here would be circular. The tuple only
# controls how "^", implicit multiplication, and postfix "!" are parsed into
# an AST shape -- it has no bearing on which *names* resolve to what, which
# is governed entirely by the global_dict/local_dict a parse_expr call is
# given -- see _GLOBAL_DICT just below.
_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication,
    implicit_application,
    function_exponentiation,
    convert_xor,
    factorial_notation,
)

# Also a second copy, not an import, of graphcalc.calc._GLOBAL_DICT's six
# constructors (Integer/Float/Rational/Symbol/Function/factorial), for the
# same circular-import reason -- parse_expr's own transformations need to
# find these names in *some* namespace to build a literal number, a bare
# name, or "!" from a generated AST node (auto_number, auto_symbol,
# factorial_notation). Add/Mul/Pow are this module's own addition, not
# needed by graphcalc.calc's real, evaluating parse_expr call: this
# module's call below passes evaluate=False, which rewrites every "+"/"-
# "/"*"/"/"/"**" into an explicit call to one of those three constructors
# (sympy.parsing.sympy_parser.EvaluateFalseTransformer) -- so they have to
# be reachable by name too, or parse_expr raises a plain NameError for any
# expr with such an operator (caught below by is_power_too_large's own
# broad except, but that would make this guard do nothing at all).
#
# Deliberately *not* `global_dict=None` (parse_expr's own default): with no
# global_dict at all, parse_expr instead gives the generated code sympy's
# complete real namespace (as if by "from sympy import *"), so a bare name
# that also happens to be a real sympy function or singleton -- "sec" (the
# secant function), "deg" (a units object), "S"/"N"/"Q" (sympify/evalf/
# assumptions) -- would resolve to that sympy object instead of becoming a
# free Symbol, which breaks is_power_too_large's own "a bare name is always
# unknown, so always allow it" rule (see _log10_abs's docstring): a bare
# sympy function reference such as the `sec` singleton is not a sympy Expr
# at all, and some of these (sympy.N, a plain Python function, not even a
# sympy object) do not even have an .atoms() method to call.
_GLOBAL_DICT = {
    "__builtins__": {},
    "Integer": Integer,
    "Float": Float,
    "Rational": Rational,
    "Symbol": Symbol,
    "Function": Function,
    "factorial": factorial,
    "Add": Add,
    "Mul": Mul,
    "Pow": Pow,
}

# The most decimal digits (an estimate of abs(log10(value))) a power's
# result may have before evaluate() refuses to compute it at all. Must stay
# well below Python's own default integer-to-string conversion limit
# (sys.get_int_max_str_digits(), 4300 on 3.11+): once a result's exact
# Integer needs more digits than that, graphcalc.calc.evaluate's later
# str(result) call -- used to build the "exact" field -- raises ValueError
# ("Exceeds the limit (4300 digits)..."), which graphcalc.cli's catch-all
# then turns into a 400 "unexpected error: Exceeds the limit..." -- exactly
# the forbidden wording this plan step's acceptance criteria ban, and from
# a result (2**20000, 6,021 digits) far smaller than this guard's earlier
# 10**5 threshold let through. 4_000 keeps a comfortable margin below 4300
# for this estimate's own float-arithmetic imprecision, while still
# comfortably passing 10**1000 (1001 digits) and catching 2**20000 (~6,021
# digits), 2**10000000 (~3,010,300 digits), 9**9**9 (~369,671,667 digits),
# and 10**10**10 (10,000,000,000 digits).
MAX_POWER_DIGITS = 4_000


def _log10_abs(node):
    """Return an estimate of log10(abs(value)) for `node`, or None.

    None means "this guard cannot safely size `node` up" -- a Symbol, an
    unresolved function call, an Add/Mul, or anything else with a free
    symbol -- and is_power_too_large treats None the same as "small
    enough": a Pow is only ever flagged when its base and exponent, and
    recursively theirs, are each either a plain numeric literal (Integer,
    Rational, Float) or another such Pow, all the way down. A stored
    variable, "ans", or any other symbolic name used as a base or exponent
    therefore always comes back None here and is let through unflagged,
    exactly as the plan step asks ("treat any non-numeric or symbolic part
    as unknown and allow it").

    Never computes an exact value for a Pow node, however deeply nested --
    not even the cheap inner step of a tower such as 9**9 -- so this
    function's own running time stays proportional to the number of
    operators `node` contains, never to the size of the number any of them
    would actually evaluate to: a Pow's estimate is built purely from float
    arithmetic on its base's and exponent's own estimates. The exponent's
    own magnitude (not just its log10) is needed for the textbook
    log10(base**exponent) = exponent * log10(base) formula; it is
    reconstructed as 10 ** exponent_log10_abs -- always an ordinary
    (possibly "inf", never raising) float, long before this function would
    otherwise have to represent the actual, possibly-astronomical value
    itself.
    """
    if isinstance(node, Pow):
        base_log10 = _log10_abs(node.base)
        if base_log10 is None:
            return None
        if base_log10 == 0.0:
            # abs(base) == 1: 1**anything and (-1)**anything always has
            # abs(value) == 1, no matter how large -- or unknown -- the
            # exponent's own magnitude is. Returning early here also
            # sidesteps the one case the formula below cannot handle on
            # its own: an exponent magnitude that overflows to float
            # "inf" would otherwise multiply out to inf * 0.0 == nan.
            return 0.0
        exp_log10 = _log10_abs(node.exp)
        if exp_log10 is None:
            return None
        try:
            exponent_magnitude = 10.0**exp_log10
        except OverflowError:
            exponent_magnitude = math.inf
        if node.exp.is_negative:
            exponent_magnitude = -exponent_magnitude
        return exponent_magnitude * base_log10
    if node.free_symbols or not isinstance(node, (Integer, Rational, Float)):
        return None
    try:
        value = float(node)
    except OverflowError:
        # A literal integer typed directly in the expression text (never
        # produced by this guard itself -- see the module docstring) with
        # more digits than a float can represent at all. bit_length() is
        # cheap regardless of how many digits the literal has: unlike
        # str(n), it never has to produce a decimal rendering of `n`.
        if not isinstance(node, Integer):
            return None
        bits = abs(int(node)).bit_length()
        return (bits - 1) * math.log10(2) if bits else None
    if value == 0:
        return None
    return math.log10(abs(value))


def is_power_too_large(expr: str) -> bool:
    """True if `expr` contains a power estimated to need more than
    MAX_POWER_DIGITS decimal digits.

    Parses `expr` with evaluate=False and this module's own, restricted
    _GLOBAL_DICT (see the module docstring for why that matters), then
    checks every Pow node the parsed tree contains, however deeply nested,
    against MAX_POWER_DIGITS via _log10_abs.

    global_dict=_GLOBAL_DICT (not the default, global_dict=None) is what
    keeps a bare name that also happens to be a real sympy function or
    singleton -- "sec", "deg", "S", "N", "Q" -- resolving to a free Symbol
    here, the same as it does in graphcalc.calc's own, real parse_expr
    call: parse_expr's auto_symbol transformation only wraps a NAME token
    in Symbol(...) when that name is *not* already a key of global_dict (or
    local_dict), so the default global_dict=None -- which hands auto_symbol
    sympy's entire real namespace, as if by "from sympy import *" -- would
    otherwise let "sec" resolve to the real sec FunctionClass, "N" to the
    real N() function, and so on; none of those are a sympy Basic, so
    `.atoms(Pow)` below would raise AttributeError on them.

    The whole body (parse and walk) is wrapped in one broad except so this
    guard can never itself turn a valid request into a crash: anything this
    module's own parse_expr call cannot handle at all, or any shape the
    walk below does not expect (including the case just above, in case some
    other bare name slips past _GLOBAL_DICT the same way), simply returns
    False -- "not too large" -- and lets graphcalc.calc.evaluate's own real
    parse_expr/check_grammar reject or accept `expr` in the normal way.
    """
    try:
        parsed = parse_expr(
            expr, transformations=_TRANSFORMATIONS, evaluate=False, global_dict=_GLOBAL_DICT
        )
        if not isinstance(parsed, Basic):
            return False
        for node in parsed.atoms(Pow):
            estimate = _log10_abs(node)
            if estimate is not None and abs(estimate) > MAX_POWER_DIGITS:
                return True
        return False
    except Exception:
        return False
