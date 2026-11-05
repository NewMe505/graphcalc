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

from graphcalc.grammar import GrammarError, check_grammar
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
_DEFINITION_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*:=\s*(.+?)\s*$")


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
_FUNCTION_DEFINITION_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*\(\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*\)\s*:=\s*(.+?)\s*$"
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


def _function_locals(functions: dict) -> dict:
    """Build {name: Lambda(params_as_Symbols, body)} for every stored function.

    `functions` is graphcalc.state.CalcState.functions()'s mapping: name ->
    {"params": [str, ...], "body": <plain sympy str, "**" notation>}. Each
    Lambda is rebuilt fresh from the stored strings every call -- including
    right after a disk reload, since CalcState only ever stores plain
    strings, never a Lambda object itself.
    """
    built = {}
    for name, spec in functions.items():
        params = tuple(Symbol(p) for p in spec["params"])
        body = sympify(spec["body"])
        built[name] = Lambda(params, body)
    return built


class CalcError(Exception):
    """A user-facing calculator error: bad syntax or an invalid parameter."""


# The two domain_error messages: zoo/oo/-oo (a division by zero) vs. nan (an
# indeterminate form such as 0/0). Kept as module constants so other
# features (and tests) can check against the exact wording.
DOMAIN_ERROR_DIVISION_BY_ZERO = "division by zero"
DOMAIN_ERROR_UNDEFINED = "undefined"

_INFINITE_RESULTS = (zoo, oo, -oo)

# Bound to "ans" in local_dict whenever there is no history yet, so "ans"
# always resolves to something -- a Dummy is never equal to anything a user
# could type, so finding it in the parsed expression's free symbols
# afterwards unambiguously means the input used "ans" with no history to
# give it a value, rather than "ans" simply being treated as a free
# variable named "ans".
_UNDEFINED_ANS = Dummy("ans")


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
    "undefined" for nan.

    `last_entry` is the history store's most recent successful entry (its
    dict with an "exact" key), or None when the history is empty. The token
    "ans" is bound to sympify(last_entry["exact"]) -- via local_dict, so it
    is only ever matched as a whole identifier, never as a substring of
    another name such as "answer". With no history, "ans" is instead bound
    to a private sentinel so it still parses as one name rather than being
    split into "a*n*s"; if that sentinel survives into the parsed
    expression's free symbols, evaluate raises CalcError("ans is undefined")
    instead of treating "ans" as a free variable.

    `variables` is a name -> exact-value-string mapping (graphcalc.state's
    CalcState.variables(), typically) bound into local_dict the same way --
    each value is reparsed with plain sympify(), never through
    _rad_names()/_deg_names() (that whitelist remaps "log" to log10 and
    would double-convert degrees). A name is never split into letters (plan
    step P24/S1, Bug #7 fix), bound or not, so "2a" resolves to "2*5" when
    a's exact value is "5", the same way "2x" resolves to "2*x" when "x" is
    an unbound plain Symbol.

    `functions` is a name -> {"params": [...], "body": str} mapping
    (graphcalc.state's CalcState.functions(), typically; plan step P7/S2).
    _function_locals() rebuilds each one as a fresh sympy Lambda(params,
    body) and binds it the same way, so "f(3)" calls the Lambda directly --
    the same mechanism "sin(30)" already uses for a whitelisted name. Calling
    a bound function with the wrong number of arguments raises sympy's
    BadArgumentsError, caught below like any other parse/eval failure and
    turned into a CalcError, never left to propagate as a 500.

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
    grammar. A rejection there is turned into a CalcError here the same way
    any other parse/eval failure is, so it is still a 400, never a 500.

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

    local_dict = _deg_names() if mode == "deg" else _rad_names()
    if variables:
        for name, value in variables.items():
            local_dict[name] = sympify(value)
    try:
        if functions:
            local_dict.update(_function_locals(functions))
        if symbols:
            for name in symbols:
                local_dict[name] = Symbol(name)
        local_dict["ans"] = (
            sympify(last_entry["exact"]) if last_entry is not None else _UNDEFINED_ANS
        )
        parsed = parse_expr(
            expr,
            transformations=_TRANSFORMATIONS,
            global_dict=_GLOBAL_DICT,
            local_dict=local_dict,
        )
        if _UNDEFINED_ANS in parsed.free_symbols:
            raise CalcError("ans is undefined")
        result = simplify(parsed)
    except CalcError:
        raise
    except Exception as exc:
        raise CalcError(f"invalid expression: {expr}") from exc

    exact = str(result)
    decimal = None
    complex_value = None
    domain_error = None

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

    return {
        "expr": expr,
        "exact": exact,
        "decimal": decimal,
        "complex": complex_value,
        "domain_error": domain_error,
    }
