"""HTTP-free calculator core: parse an expression, evaluate it with sympy.

evaluate() and parse_definition() are the only things graphcalc/cli.py
calls; neither touches the network. Parsing is deliberately locked down:
global_dict and local_dict only contain the constructors parse_expr's
transformations emit and a small whitelist of calculator names, so an
expression string can never reach a real Python builtin.
"""

import re

from sympy import (
    Abs,
    Dummy,
    E,
    Float,
    Function,
    I,
    Integer,
    Lambda,
    N,
    Rational,
    Symbol,
    acos,
    asin,
    atan,
    cos,
    exp,
    factorial,
    log,
    nan,
    oo,
    pi,
    simplify,
    sin,
    sqrt,
    srepr,
    sympify,
    tan,
    zoo,
)
from sympy.parsing.sympy_parser import (
    convert_xor,
    factorial_notation,
    function_exponentiation,
    implicit_application,
    implicit_multiplication,
    parse_expr,
    standard_transformations,
)

from graphcalc.grammar import GrammarError, _tokenize, called_names, check_grammar
from graphcalc.limits import is_power_too_large
from graphcalc.numfmt import format_decimal

# Deliberately NOT sympy's bundled implicit_multiplication_application: that
# tuple opens with split_symbols, which breaks a multi-letter identifier such
# as "rate" or "xy" into one symbol per letter (plan step P24/S1, Bug #7).
# Each letter is then re-resolved against local_dict on its own, so "rate"'s
# "e" silently becomes the constant E, "sec" becomes "E*c*s", and so on --
# never the single name the TI-Nspire CAS (and this calculator) treats it
# as. implicit_multiplication and implicit_application alone still give "2x",
# "2pi" and "2sin(pi/6)" their implied multiplication/call -- they just never
# split a name that was typed as one run of letters/digits/underscores in
# the first place.
_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication,
    implicit_application,
    function_exponentiation,
    convert_xor,
    factorial_notation,
)

# Only the sympy constructors parse_expr's transformations emit -- never the
# real Python builtins. Setting "__builtins__" to {} is what keeps eval()
# from silently getting the real ones back (the default when a global dict
# omits the key at all). factorial_notation's postfix "!" expands to a call
# to a bare "factorial" name, so that constructor belongs here too.
_GLOBAL_DICT = {
    "__builtins__": {},
    "Integer": Integer,
    "Float": Float,
    "Rational": Rational,
    "Symbol": Symbol,
    "Function": Function,
    "factorial": factorial,
}


_DEG_TO_RAD = pi / 180


def _log10(x):
    return log(x, 10)


def _rad_names():
    """The whitelisted calculator names, angles in radians."""
    return {
        "pi": pi,
        "e": E,
        "E": E,
        "I": I,
        "sqrt": sqrt,
        "sin": sin,
        "cos": cos,
        "tan": tan,
        "asin": asin,
        "acos": acos,
        "atan": atan,
        "ln": log,
        "log": _log10,
        "exp": exp,
        "abs": Abs,
    }


def _deg_names():
    """The same whitelist, with trig functions converting to/from degrees."""
    names = _rad_names()
    names.update(
        {
            "sin": lambda x: sin(x * _DEG_TO_RAD),
            "cos": lambda x: cos(x * _DEG_TO_RAD),
            "tan": lambda x: tan(x * _DEG_TO_RAD),
            "asin": lambda x: asin(x) / _DEG_TO_RAD,
            "acos": lambda x: acos(x) / _DEG_TO_RAD,
            "atan": lambda x: atan(x) / _DEG_TO_RAD,
        }
    )
    return names


# A bare "name:=expr" assignment (plan step P7/S1). The identifier must be
# the whole left-hand side -- "f(x):=..." (a function definition) has a "("
# right after the name, which this pattern's \s*:=\s* cannot match, so it
# is deliberately left for a later plan step to handle.
#
# re.ASCII (plan step P27/S2, Bug #21 fix): without it, "\w" is
# Unicode-aware, so e.g. "x²:=4" or "a２:=1" would match here with the
# non-ASCII character folded straight into the captured name ("x²", "a２")
# -- never reaching graphcalc.grammar's own ASCII check at all, since that
# check only ever runs on the *right*-hand side (`evaluate(rhs, ...)`
# below), not on a name this regex already split off. With re.ASCII, "\w"
# only matches [A-Za-z0-9_], so neither pattern matches as a definition at
# all; both fall through to a plain evaluate(expr) call on the *original,
# unsplit* string, whose own non-ASCII character is then rejected by
# graphcalc.grammar.check_grammar the same way any other such character is.
_DEFINITION_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*:=\s*(.+?)\s*$", re.ASCII)


def parse_definition(expr: str) -> tuple[str, str] | None:
    """Return (name, rhs) if `expr` is a plain "name:=expr" assignment.

    Returns None for anything else -- including "f(x):=expr", normal
    expressions, and non-string input -- so callers can try this first and
    fall back to evaluate() unchanged when it returns None.
    """
    if not isinstance(expr, str):
        return None
    match = _DEFINITION_RE.match(expr)
    if match is None:
        return None
    return match.group(1), match.group(2)


# A "f(x):=expr" or "f(x,y):=expr" function definition (plan step P7/S2):
# an identifier, a parenthesised comma-separated list of one or more plain
# identifier params, then ":=". "f():=1" (no params) and "f(1):=2" (a
# non-identifier "param") deliberately do not match -- they fall through to
# evaluate(), which reports its own CalcError for the stray ":=".
#
# re.ASCII (plan step P27/S2, Bug #21 fix): same reasoning as
# _DEFINITION_RE just above -- without it, "f(x²):=1" would match with the
# non-ASCII param folded straight into the captured name ("x²"), bypassing
# graphcalc.grammar's own ASCII check entirely (that check only ever runs
# on the body, via evaluate(rhs, ...) below, never on a param this regex
# already split off into `symbols`). With re.ASCII, this simply fails to
# match "f(x²):=1" as a function definition at all, so it falls through to
# a plain evaluate() call on the original string instead.
_FUNCTION_DEFINITION_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*\(\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*\)\s*:=\s*(.+?)\s*$",
    re.ASCII,
)


def parse_function_definition(expr: str) -> tuple[str, list[str], str] | None:
    """Return (name, params, rhs) if `expr` is a "f(x[, y...]):=expr" definition.

    Returns None for anything else -- including a bare "name:=expr" variable
    definition (parse_definition matches that instead), a function call such
    as "f(3)" (no ":=" at all), and malformed syntax -- so callers can try
    this after parse_definition and fall back to evaluate() unchanged when
    both return None.
    """
    if not isinstance(expr, str):
        return None
    match = _FUNCTION_DEFINITION_RE.match(expr)
    if match is None:
        return None
    name = match.group(1)
    params = [p.strip() for p in match.group(2).split(",")]
    rhs = match.group(3)
    return name, params, rhs


def to_caret(exact: str) -> str:
    """Render a sympy str() result with "^" for power instead of "**".

    sympy's str() always prints exponentiation as "**" (plain Python); this
    calculator's own input syntax, a function definition's returned body
    (plan step P7/S2), and later P19's CAS results instead use "^". A plain
    string replace is safe because sympy's str() never emits a literal "**"
    for anything else. The *stored* body string (graphcalc.state.CalcState)
    stays in "**" form -- this conversion is applied only when building an
    API response, so the stored string stays directly re-sympify()-able.
    """
    return exact.replace("**", "^")


def _function_locals(functions: dict, referenced: set) -> dict:
    """Build {name: Lambda(params_as_Symbols, body)} for every *referenced*
    stored function (plan step P26/S2, Bug #14 fix).

    `functions` is graphcalc.state.CalcState.functions()'s mapping: name ->
    {"params": [str, ...], "body": <plain sympy str, "**" notation>,
    "body_srepr": <srepr str, or None for a function stored before this
    fix>}. Only a name in `referenced` (evaluate()'s own _referenced_names
    (expr)) is ever rebuilt here -- the same lazy rule evaluate() already
    applies to a stored "ans" (P26/S1) and a stored variable (see
    _rebuild_stored_value just above): an expression that never calls a
    given function can never be broken by that function's body being
    impossible to rebuild.

    The body is rebuilt from "body_srepr" when it is not None -- srepr()'s
    quoted Symbol('name') constructor arguments can never resolve against
    sympy's own namespace the way a bare name in a plain str() rebuild can
    (see the "ans" paragraph of evaluate()'s docstring for the full
    explanation), so this is safe regardless of what the name would
    otherwise mean bare -- e.g. "beta", a real sympy function, not just a
    free symbol, in sympy's own namespace. "body_srepr" is None for a
    function this calculator stored before this fix (no srepr was ever
    persisted for it then); "body" -- plain sympify(), never the restricted
    local_dict/global_dict a user's own input parses with -- is the
    fallback for that case, unchanged from before this fix.
    """
    built = {}
    for name, spec in functions.items():
        if name not in referenced:
            continue
        params = tuple(Symbol(p) for p in spec["params"])
        body_srepr = spec.get("body_srepr")
        body = sympify(body_srepr) if body_srepr is not None else sympify(spec["body"])
        built[name] = Lambda(params, body)
    return built


def _rebuild_stored_value(value):
    """Rebuild a stored variable's value into a sympy object (plan step
    P26/S2, Bug #14 fix).

    `value` is either the current CalcState shape, {"exact": str, "srepr":
    str | None}, or a plain exact string -- the shape every variable had
    before this fix, still accepted here both for a state file written by
    an older version of this calculator and for a caller that passes the
    `variables` dict to evaluate() directly (several existing unit tests
    do). "srepr", when present and not None, is preferred: srepr()'s quoted
    Symbol('name') constructor arguments can never resolve against sympy's
    own namespace the way a bare name in a plain str() rebuild can (see the
    "ans" paragraph of evaluate()'s docstring for the full explanation), so
    this is the only rebuild that is safe regardless of what the name would
    otherwise mean bare -- e.g. "beta", a real sympy function. Falls back
    to plain sympify() of the exact string when there is no srepr to use,
    the same rebuild this calculator always used before this fix.

    Can raise -- evaluate() only calls this for a name `expr` actually
    references (see _referenced_names), so a failure here becomes the
    usual CalcError -> 400 for that expression, never left to break an
    unrelated one that never mentions the name at all.
    """
    if isinstance(value, dict):
        srepr_value = value.get("srepr")
        exact_value = value.get("exact")
        return sympify(srepr_value) if srepr_value is not None else sympify(exact_value)
    return sympify(value)


class CalcError(Exception):
    """A user-facing calculator error: bad syntax or an invalid parameter."""


# The two domain_error messages: zoo/oo/-oo (a division by zero) vs. nan (an
# indeterminate form such as 0/0). Kept as module constants so other
# features (and tests) can check against the exact wording.
DOMAIN_ERROR_DIVISION_BY_ZERO = "division by zero"
DOMAIN_ERROR_UNDEFINED = "undefined"
# A power whose result graphcalc.limits.is_power_too_large estimates would
# need more decimal digits than it allows (plan step P28/S1, Bug #20 fix) --
# "9^9^9", "10^10^10", "2^10000000". Reported the same way as the two
# domain_error messages above: exact/decimal/complex are all None, and
# evaluate() never lets sympy's own, real parse_expr touch `expr` at all,
# so a request that would otherwise freeze the server trying to materialize
# an astronomically large exact integer instead answers almost immediately.
DOMAIN_ERROR_TOO_LARGE = "result too large to compute"

_INFINITE_RESULTS = (zoo, oo, -oo)

# Bound to "ans" in local_dict whenever there is no history yet, so "ans"
# always resolves to something -- a Dummy is never equal to anything a user
# could type, so finding it in the parsed expression's free symbols
# afterwards unambiguously means the input used "ans" with no history to
# give it a value, rather than "ans" simply being treated as a free
# variable named "ans".
_UNDEFINED_ANS = Dummy("ans")


def _referenced_names(expr: str) -> set:
    """Return every identifier `expr` contains as a whole token.

    Plan step P26/S2, Bug #14 fix: generalizes P26/S1's single-name check
    (then named _references_ans) to every stored variable and function
    name too. evaluate() only attempts to rebuild a stored "ans", variable
    or function (each a possibly-failing step -- see `_rebuild_stored_value`
    and `_function_locals` above) when its name is in this set, so an
    expression that never mentions a given name can never be broken by that
    name's stored value or body being unsafe, or outright impossible, to
    rebuild -- "1+1" is never affected by an unrebuildable stored "a", no
    matter how "a" was stored.

    Shares graphcalc.grammar's own tokenizer (the same one called_names()
    and check_grammar() already use) so this matches token boundaries
    exactly the way the rest of the grammar does: "2ans" (implicit
    multiplication) counts as a reference to "ans", "answer" does not -- a
    plain substring/regex check on `expr` would get the first case
    backwards (the character before "ans" is the digit "2", not a letter,
    but "2" and "ans" are still two separate tokens).
    """
    return {text for group, text in _tokenize(expr) if group == "IDENT"}


def evaluate(
    expr: str,
    mode: str = "rad",
    last_entry: dict | None = None,
    variables: dict | None = None,
    functions: dict | None = None,
    symbols: list[str] | None = None,
) -> dict:
    """Parse and evaluate `expr`, returning the calc/evaluate response dict.

    Keys: expr, exact, decimal, complex, domain_error. `exact` is the
    simplified result's str(). `decimal` is a 12-significant-digit string
    for a real numeric result, else None. `complex` is a rectangular form
    {"real": str, "imag": str}, each a 12-significant-digit string, when
    the result has a nonzero imaginary part, else None.

    `domain_error` is None on success. When the math has no value -- a
    division by zero (1/0 -> zoo, or oo/-oo) or an indeterminate form
    (0/0 -> nan) -- `exact`, `decimal` and `complex` are all None instead,
    and `domain_error` holds a message: "division by zero" for zoo/oo/-oo,
    "undefined" for nan. The same None/None/None shape, with domain_error
    "result too large to compute", is also returned -- before sympy's own
    parse_expr ever runs on `expr` at all -- for a power such as "9^9^9"
    or "10^10^10" that graphcalc.limits.is_power_too_large estimates would
    need an unreasonable number of decimal digits to materialize exactly
    (plan step P28/S1, Bug #20 fix): letting sympy actually attempt that
    computation could freeze this calculator's single-threaded HTTP server
    for every other request, for minutes or far longer. The exact/decimal/
    complex formatting below this docstring also has its own backstop
    (plan step P28/S2, Bug #20 fix): a ValueError (Python's own int-to-str
    digit limit, "Exceeds the limit (4300 digits)...") or an OverflowError
    raised while building `exact`, `decimal` or `complex` -- for a result
    that size is_power_too_large's own text-only estimate never flagged --
    is caught there and reported as this same domain_error, never as the
    raw exception text.

    `last_entry` is graphcalc.state.CalcState.ans() -- {"exact": str,
    "srepr": str} for the last successful plain evaluation, or None when
    there is none yet (plan step P26/S1, Bug #14 fix). _referenced_names(expr)
    decides, before anything else, whether `expr` mentions "ans" as a whole
    token (never as a substring of another name such as "answer", and
    always counting an implicit-multiplication use such as "2ans"); only
    when it does is "ans" bound in local_dict at all, and the bind is the
    only place a *stored* ans can fail to come back: sympify(last_entry
    ["srepr"]) -- srepr(), not str() -- read back with plain sympify()'s own
    full sympy namespace, never the restricted local_dict/global_dict a
    user's own input parses with. That pairing matters: str() of a result
    built from a name this calculator deliberately never whitelists, such as
    "beta + 1" or "gamma", is ambiguous -- sympify()'s own namespace binds
    bare "beta" to the real Euler Beta function, not back to the Symbol this
    calculator actually meant -- and ambiguous enough that re-sympify()-ing
    it can outright raise (Symbol + FunctionClass has no "+"). srepr()'s
    "Symbol('beta')" has no such ambiguity: the name is a quoted string
    literal argument to the Symbol(...) constructor, never a bare identifier
    sympify() could resolve against its own namespace, so the rebuild always
    reconstructs the exact original object regardless of what "beta",
    "gamma", "zeta", "S", "N" or "Q" would otherwise mean bare. When `expr`
    does not mention "ans" at all, none of this runs -- an unrelated
    expression such as "1+1" can never be broken by a stored ans, safe to
    rebuild or not. When it does mention "ans" but there is no last_entry
    (or its "srepr" is missing), "ans" is instead bound to a private
    sentinel so it still parses as one name rather than being split into
    "a*n*s"; if that sentinel survives into the parsed expression's free
    symbols, evaluate raises CalcError("ans is undefined") instead of
    treating "ans" as a free variable. A plain "ans" request (expr.strip()
    == "ans", nothing else) answers with the stored exact (and, internally,
    srepr) string verbatim, never a freshly str()'d/srepr()'d
    recomputation of the rebuilt object -- guarding against the (believed
    impossible, but unproven) case that simplify() ever formats an
    already-simplified object two different ways, and keeping repeated
    "ans" recall a true fixed point.

    The returned dict also carries a private "_result_srepr" key -- srepr()
    of this call's own result, or None when domain_error is set -- so
    graphcalc.cli can thread it straight into CalcState.set_ans/set_variable/
    set_function for the *next* call's "ans", or for that same variable or
    function body, without re-deriving it (ambiguously) from the plain
    `exact` string. It is not part of this function's public, documented
    response shape: a caller that forwards this dict as an HTTP response
    body must pop it first.

    `variables` is a name -> value mapping (graphcalc.state's CalcState.
    variables(), typically; plan step P26/S2, Bug #14 fix). Each value is
    either the current CalcState shape, {"exact": str, "srepr": str |
    None}, or a plain exact-value string -- the shape every variable had
    before P26/S2, still accepted here for a state file written by an
    older version of this calculator, or a caller that builds the dict by
    hand (several unit tests do). Only a name _referenced_names(expr)
    finds in `expr` is ever bound into local_dict at all -- see
    _rebuild_stored_value's own docstring for why, and for which of
    "srepr"/"exact" it prefers; this is the same lazy, srepr-first rule
    `last_entry`/"ans" above already follows. A name is never split into
    letters (plan step P24/S1, Bug #7 fix), bound or not, so "2a" resolves
    to "2*5" when a's exact value is "5", the same way "2x" resolves to
    "2*x" when "x" is an unbound plain Symbol.

    `functions` is a name -> {"params": [...], "body": str, "body_srepr":
    str | None} mapping (graphcalc.state's CalcState.functions(),
    typically; plan step P7/S2, extended by P26/S2). _function_locals()
    rebuilds, as a fresh sympy Lambda(params, body), only a name
    _referenced_names(expr) finds in `expr` -- the same lazy rule
    `variables` above follows, and for the same reason: a function this
    calculator cannot safely rebuild must never break an expression that
    never calls it. The rebuilt Lambda is bound the same way, so "f(3)"
    calls it directly -- the same mechanism "sin(30)" already uses for a
    whitelisted name. Calling a bound function with the wrong number of
    arguments raises sympy's BadArgumentsError, caught below like any other
    parse/eval failure and turned into a CalcError, never left to
    propagate as a 500.

    `symbols` is a list of names (a function definition's own params) bound
    to plain sympy Symbol(name) instead, applied after `variables` so a
    param always wins over a stored variable of the same name when a
    function's own body is being parsed to define it.

    Before any of that, graphcalc.grammar.check_grammar(expr) runs a
    pre-parse grammar gate (plan step P23/S1, Bug #5 fix): parse_expr's own
    Python-flavoured tokenizer would otherwise accept Python comparison
    operators (<, >, <=, >=, ==, !=), %, //, the bitwise/shift operators
    (&, |, ~, <<, >>), Python-only numeric literals (0x10, 0b11, 0o7,
    1_000, 2j, 3J), and an extra argument to a built-in unary function
    (ln(e,2), sqrt(4,2)) -- none of which belong to this calculator's own
    grammar. The same gate also rejects any non-ASCII letter, digit, or
    numeral (plan step P27/S2, Bug #21 fix) -- a fullwidth digit ("２"), an
    Arabic-indic digit ("٣"), or a superscript/subscript numeral ("x²") --
    which Python's own Unicode-aware tokenizer would otherwise accept.
    A rejection there is turned into a CalcError here the same way any
    other parse/eval failure is, so it is still a 400, never a 500.

    Once local_dict is complete, graphcalc.grammar.called_names(expr) is
    checked against it alone (plan step P24/S3, Bug #7 fix; tightened by
    plan step P27/S1, Bug #21 fix, which dropped the "or in _GLOBAL_DICT"
    half of this check -- see the inline comment just above the loop that
    does this, further down in this function, for the full reasoning): a
    name called with "(" that is not in local_dict -- an uppercase variant
    of a whitelisted function such as "SIN", a real sympy name this
    calculator never whitelisted such as "zeta", or one of sympy's own
    internal constructors ("Integer", "Float", "Rational", "Symbol",
    "Function", "factorial") that parse_expr's transformations emit
    internally but that a user's literal text should never be able to
    reach by name -- raises CalcError ("unknown function '<name>'") before
    parse_expr ever sees it, rather than letting parse_expr's own
    auto_symbol/implicit_multiplication fallback silently turn the call
    into an implicit product between an unresolved Symbol and the
    parenthesised argument list (or, for an internal constructor, actually
    succeeding as if it were a normal call).

    Raises CalcError (never any other exception) for a syntax error, an
    unparseable expression, or an invalid mode.
    """
    if mode not in ("rad", "deg"):
        raise CalcError(f"invalid mode: {mode}")
    if not isinstance(expr, str) or not expr.strip():
        raise CalcError("missing parameter: expr")
    try:
        check_grammar(expr)
    except GrammarError as exc:
        raise CalcError(str(exc)) from exc

    # Power-size guard (plan step P28/S1, Bug #20 fix): checked before any
    # of the real parsing below, including the "bare ans" fast path above
    # it in the docstring's own ordering -- is_power_too_large has already
    # parsed `expr` on its own, with evaluate=False, by the time it
    # returns, so this never costs more than a second cheap parse on an
    # expression that turns out fine. A flagged `expr` short-circuits
    # straight to the same response shape a division-by-zero or an
    # indeterminate form gets -- exact/decimal/complex all None, a
    # domain_error set -- and sympy's own, real (eagerly-evaluating)
    # parse_expr, further down, never runs on it at all.
    if is_power_too_large(expr):
        return {
            "expr": expr,
            "exact": None,
            "decimal": None,
            "complex": None,
            "domain_error": DOMAIN_ERROR_TOO_LARGE,
            "_result_srepr": None,
        }

    local_dict = _deg_names() if mode == "deg" else _rad_names()
    stored_srepr = None
    try:
        # Lazy rebuild (plan step P26/S2, Bug #14 fix): a stored variable
        # or function is only ever rebuilt when `expr` actually references
        # its name, exactly the same rule already applied to "ans" below --
        # so a definition this calculator cannot safely rebuild (one stored
        # before this fix, or a hand-edited state file) can never break an
        # expression that never mentions it, such as "1+1".
        referenced = _referenced_names(expr)
        if variables:
            for name, value in variables.items():
                if name in referenced:
                    local_dict[name] = _rebuild_stored_value(value)
        if functions:
            local_dict.update(_function_locals(functions, referenced))
        if symbols:
            for name in symbols:
                local_dict[name] = Symbol(name)
        if "ans" in referenced:
            stored_srepr = last_entry.get("srepr") if last_entry is not None else None
            local_dict["ans"] = (
                sympify(stored_srepr) if stored_srepr is not None else _UNDEFINED_ANS
            )
        # A name called with "(" that is not in local_dict (the rad/deg
        # whitelist, a stored variable or function, a function definition's
        # own param, "ans") is unknown *and* undefined -- never a function
        # this calculator can call (plan step P24/S3, Bug #7 fix; tightened
        # by plan step P27/S1, Bug #21 fix). Rejected here, before
        # parse_expr ever runs, so an uppercase name such as "SIN" in
        # "SIN(pi/2)" (not the same name as the whitelisted, lowercase
        # "sin") or a real sympy name this calculator never whitelisted
        # ("zeta(2)") is a 400 with "unknown function '<name>'" -- never
        # left for parse_expr's own auto_symbol fallback, which would
        # otherwise wrap the call in a Function(...) that implicit_
        # multiplication's close-paren-before-open-paren rule immediately
        # downgrades back to a plain Symbol times the argument list (e.g.
        # "SIN(pi/2)" -> "pi*SIN/2") -- a name is matched exactly and
        # case-sensitively, never resolved by building a Function object
        # whose own str() (e.g. "SIN(...)") would contain the letter I.
        #
        # _GLOBAL_DICT is deliberately *not* checked here (Bug #21): it
        # holds only the internal constructors (Integer, Float, Rational,
        # Symbol, Function, factorial) that parse_expr's own transformations
        # emit from a generated AST node -- auto_number for a bare "2",
        # auto_symbol for a bare "x", factorial_notation for postfix "!" --
        # never from a name the user actually typed followed by "(" in the
        # source text. called_names(expr) only ever sees the latter, so
        # checking it against local_dict alone means "Integer(2)",
        # "Float(2)", "Rational(1,2)" and "factorial(5)" are all rejected
        # as unknown functions, while "5!" (factorial_notation's own
        # generated factorial(...) call, never present as the literal text
        # "factorial(") and "1/3+1/6" (Rational's own generated calls, same
        # reasoning) still evaluate normally.
        for name in called_names(expr):
            if name not in local_dict:
                raise CalcError(f"unknown function '{name}'")
        # A bare "ans" request (nothing else in `expr`) is a true fixed
        # point: reuse the previous call's own `exact`/srepr verbatim
        # instead of re-parsing/re-simplifying/re-str()-ing the rebuilt
        # object (plan step P26/S1, Bug #14 fix) -- see the `last_entry`
        # paragraph above for why a fresh str() could, in principle, ever
        # disagree with the string that was actually returned before.
        if expr.strip() == "ans" and stored_srepr is not None:
            result = local_dict["ans"]
            exact_override = last_entry["exact"]
        else:
            parsed = parse_expr(
                expr,
                transformations=_TRANSFORMATIONS,
                global_dict=_GLOBAL_DICT,
                local_dict=local_dict,
            )
            if _UNDEFINED_ANS in parsed.free_symbols:
                raise CalcError("ans is undefined")
            result = simplify(parsed)
            exact_override = None
    except CalcError:
        raise
    except Exception as exc:
        raise CalcError(f"invalid expression: {expr}") from exc

    exact = None
    decimal = None
    complex_value = None
    domain_error = None

    try:
        exact = exact_override if exact_override is not None else str(result)

        # Check for a domain error before any formatting: a result with no
        # value (a division by zero, or an indeterminate form) reports
        # exact/decimal/complex as None instead of trying to format zoo/nan.
        if result in _INFINITE_RESULTS:
            domain_error = DOMAIN_ERROR_DIVISION_BY_ZERO
            exact = None
        elif result is nan:
            domain_error = DOMAIN_ERROR_UNDEFINED
            exact = None
        elif not result.free_symbols and getattr(result, "is_number", False):
            re_part, im_part = N(result, 17).as_real_imag()
            if im_part == 0:
                decimal = format_decimal(result)
            else:
                complex_value = {
                    "real": format_decimal(re_part),
                    "imag": format_decimal(im_part),
                }
    except (ValueError, OverflowError):
        # Backstop for graphcalc.limits.is_power_too_large's own estimate
        # (plan step P28/S1) missing a result this large: that guard only
        # ever looks at literal Pow nodes in `expr`'s own text, so a result
        # that reaches the same astronomical size some other way -- a huge
        # stored variable or "ans" referenced here, a factorial, or
        # simplify() itself growing the value -- is never flagged there and
        # falls through to this formatting code instead. str(result) on an
        # Integer past sys.get_int_max_str_digits() raises exactly this
        # ValueError ("Exceeds the limit (4300 digits)..."); N()/format_
        # decimal's own float/Decimal conversions can raise either one for
        # a similarly huge magnitude. Both become this exact same clean
        # domain_error -- never the raw exception text, which is how the
        # forbidden "Exceeds the limit" wording used to leak into a 400
        # (plan step P28/S2, Bug #20 fix).
        exact = None
        decimal = None
        complex_value = None
        domain_error = DOMAIN_ERROR_TOO_LARGE

    # "_result_srepr": the srepr() this call's own result should be rebuilt
    # from, whether it is later recalled as "ans" (plan step P26/S1) or
    # stored as a variable's value or a function's body (plan step P26/S2)
    # -- never derived from the plain `exact` string (see the big paragraph
    # above for why that is ambiguous for a name such as "beta" or
    # "gamma"). The fixed-point branch above reuses the previously-stored
    # srepr verbatim, for the same reason it reuses `exact` verbatim. None
    # on a domain error: a result with no value is never stored as "ans", a
    # variable or a function body (graphcalc.cli only persists one when
    # domain_error is None). Private: graphcalc.cli must pop this key
    # before forwarding the rest of this dict as an HTTP response body.
    result_srepr = None if domain_error is not None else (
        stored_srepr if exact_override is not None else srepr(result)
    )

    return {
        "expr": expr,
        "exact": exact,
        "decimal": decimal,
        "complex": complex_value,
        "domain_error": domain_error,
        "_result_srepr": result_srepr,
    }
