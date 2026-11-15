"""Shared number formatters: decimal notation and clean exact text.

`format_decimal` renders a value as a 12-significant-digit decimal string
instead of sympy's exact symbolic form -- the calculator, the grapher,
stats and regression all share this one routine so "12 significant
digits, no trailing zeros, no exponent notation" means the same thing
everywhere. `clean_float_exact` renders a sympy ``Float`` as a clean,
un-padded decimal string for the separate `exact` field (plan step P31) --
a different job (no rounding, no significant-digit limit), but kept in
this module since both exist to make a number read the way a user typed
or expects it, not the way sympy's own str()/N() happens to print it.
"""

from decimal import Decimal, localcontext

from sympy import N


def clean_float_exact(value):
    """Render a sympy ``Float`` as a clean, un-padded decimal string.

    sympy's own ``str()`` of a ``Float`` pads the mantissa out to the
    value's working precision (15 decimal digits by default), so a
    user-typed literal like "1.5" prints as "1.50000000000000" and "1e5"
    prints as "100000.000000000" -- never what the `exact` field of an
    evaluate response should show for a decimal literal (plan step P31).
    This strips that padding -- trailing fractional zeros, then a trailing
    "." -- so "1.50000000000000" -> "1.5" and "100000.000000000" ->
    "100000", without rounding away any significant digit the Float
    actually carries (unlike `format_decimal`, which rounds to `sig`
    significant digits for the separate `decimal` field).

    For every magnitude this calculator's Float literals and results
    actually reach, sympy's own `str()` already uses plain fixed-point
    notation ("123.456", "100000000000000000000."), and this function
    never introduces exponent notation for those. Only the rare magnitude
    where sympy's own `str()` already switches to scientific notation
    (e.g. "1.00000000000000e-10") carries an "e"/"E" here; that mantissa is
    cleaned the same way and the exponent is re-printed as a plain int
    (no "+", no leading zeros), matching `format_decimal`'s own exponent
    style.
    """
    text = str(value)
    mantissa, sep, exponent = text.partition("e")
    if not sep:
        mantissa, sep, exponent = text.partition("E")
    if "." in mantissa:
        mantissa = mantissa.rstrip("0").rstrip(".")
    if sep:
        return f"{mantissa}e{int(exponent)}"
    return mantissa


def format_decimal(value, sig=12):
    """Render `value` as a decimal string with `sig` significant digits.

    `value` is evaluated through sympy's N() with a few guard digits beyond
    `sig` (so the final rounding step is accurate), then rounded to exactly
    `sig` significant digits and printed in fixed-point notation for normal
    magnitudes. Trailing zeros, and a trailing '.', are stripped: 0.5 ->
    "0.5", 1/3 -> "0.333333333333", 32 -> "32".

    A value whose integer part would need more than `sig` digits (absolute
    value >= 10**sig) is printed instead in scientific notation with `sig`
    significant digits, no trailing zeros in the mantissa, and a lowercase
    'e' with no '+' and no leading zeros in the exponent:
    2**100 -> "1.26765060023e30".
    """
    guard = sig + 5
    approx = N(value, guard)
    digits = Decimal(str(approx))
    with localcontext() as ctx:
        ctx.prec = sig
        digits = +digits  # unary plus rounds the value to the context's precision
    if digits.adjusted() >= sig:
        mantissa, _, exponent = format(digits, "E").partition("E")
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{mantissa}e{int(exponent)}"
    text = format(digits, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
