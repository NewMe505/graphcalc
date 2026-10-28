"""HTTP-free calculator core: parse an expression, evaluate it with sympy.

evaluate() is the only thing graphcalc/cli.py calls; it never touches the
network. Parsing is deliberately locked down: global_dict and local_dict
only contain the constructors parse_expr's transformations emit and a
small whitelist of calculator names, so an expression string can never
reach a real Python builtin.
"""

from sympy import (
    Abs,
    E,
    Float,
    Function,
    I,
    Integer,
    N,
    Rational,
    Symbol,
    acos,
    asin,
    atan,
    cos,
    exp,
    log,
    pi,
    simplify,
    sin,
    sqrt,
    tan,
)
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from graphcalc.numfmt import format_decimal

_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)

# Only the sympy constructors parse_expr's transformations emit -- never the
# real Python builtins. Setting "__builtins__" to {} is what keeps eval()
# from silently getting the real ones back (the default when a global dict
# omits the key at all).
_GLOBAL_DICT = {
    "__builtins__": {},
    "Integer": Integer,
    "Float": Float,
    "Rational": Rational,
    "Symbol": Symbol,
    "Function": Function,
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


class CalcError(Exception):
    """A user-facing calculator error: bad syntax or an invalid parameter."""


def evaluate(expr: str, mode: str = "rad") -> dict:
    """Parse and evaluate `expr`, returning the calc/evaluate response dict.

    Keys: expr, exact, decimal, complex, domain_error. `exact` is the
    simplified result's str(). `decimal` is a 12-significant-digit string
    for a real numeric result, else None. `complex` is a formatted "a+bi"
    string when the result has a nonzero imaginary part, else None.
    `domain_error` is always None in this step -- it is set by later
    features for inputs that have no value (1/0, 0/0).

    Raises CalcError (never any other exception) for a syntax error, an
    unparseable expression, or an invalid mode.
    """
    if mode not in ("rad", "deg"):
        raise CalcError(f"invalid mode: {mode}")
    if not isinstance(expr, str) or not expr.strip():
        raise CalcError("missing parameter: expr")

    local_dict = _deg_names() if mode == "deg" else _rad_names()
    try:
        parsed = parse_expr(
            expr,
            transformations=_TRANSFORMATIONS,
            global_dict=_GLOBAL_DICT,
            local_dict=local_dict,
        )
        result = simplify(parsed)
    except CalcError:
        raise
    except Exception as exc:
        raise CalcError(f"invalid expression: {expr}") from exc

    exact = str(result)
    decimal = None
    complex_value = None
    domain_error = None

    if not result.free_symbols and getattr(result, "is_number", False):
        re_part, im_part = N(result, 17).as_real_imag()
        if im_part == 0:
            decimal = format_decimal(result)
        else:
            complex_value = f"{format_decimal(re_part)}+{format_decimal(im_part)}i"

    return {
        "expr": expr,
        "exact": exact,
        "decimal": decimal,
        "complex": complex_value,
        "domain_error": domain_error,
    }
