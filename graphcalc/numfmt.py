"""Shared decimal formatter: positional notation, N significant digits.

Used anywhere a result needs a 12-significant-digit decimal string instead
of sympy's exact symbolic form -- the calculator, the grapher, stats and
regression all share this one routine so "12 significant digits, no
trailing zeros, no exponent notation" means the same thing everywhere.
"""

from decimal import Decimal, localcontext

from sympy import N


def format_decimal(value, sig=12):
    """Render `value` as a positional decimal string with `sig` significant digits.

    `value` is evaluated through sympy's N() with a few guard digits beyond
    `sig` (so the final rounding step is accurate), then rounded to exactly
    `sig` significant digits and printed in fixed-point (never exponent)
    notation for normal magnitudes. Trailing zeros, and a trailing '.', are
    stripped: 0.5 -> "0.5", 1/3 -> "0.333333333333", 32 -> "32".
    """
    guard = sig + 5
    approx = N(value, guard)
    digits = Decimal(str(approx))
    with localcontext() as ctx:
        ctx.prec = sig
        digits = +digits  # unary plus rounds the value to the context's precision
    text = format(digits, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
