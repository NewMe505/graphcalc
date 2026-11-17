"""One-variable statistics for POST /api/stats/onevar (plan steps P16/S1,
P16/S2).

onevar(values) is the pure computation graphcalc/cli.py's
_handle_stats_onevar hands a stored list's values to, after reading them
out of the same graphcalc.state.CalcState the P15 list routes already use.
`values` is ordinarily the stored list's values exactly as graphcalc.lists.
validate_list_values left them: a non-empty list of strings, each one a
calculator expression already known to parse (but never evaluated) by
graphcalc.calc.evaluate -- the same contract every expression that
references a stored list (e.g. "2*L1+1") already relies on. Neither this
module nor its caller ever substitutes the evaluated result in a stored
value's place; _to_exact_number below does its own parsing. An empty
`values` -- never stored through PUT /api/lists/<name> itself, but
reachable through a hand-edited state file -- raises CalcError("list is
empty") (plan step P16/S2) rather than being computed on; see onevar()'s
own docstring below.

Each entry is first turned into an exact sympy number by _to_exact_number:
a plain numeric literal ("1", "-3", "1.5", "3/2") is parsed with sympy's
Rational(), which reads a decimal or fraction string straight into an
exact Rational/Integer rather than an inexact Float. A stored value that is
not plain-numeric (e.g. "sqrt(2)", "2+3") raises inside Rational() (a
TypeError for this constructor); this falls back to
nsimplify(sympify(value)), which parses it as a normal sympy expression and
leaves an already-exact value exactly as it is -- "keep stored exact
strings exact" -- rather than approximating it as a Float.

n, sum, mean, median, the sample standard deviation sx, the population
standard deviation sigma_x, min, max and the TI quartiles q1/q3 are all
computed from that list of exact sympy numbers, sorted once
(`sorted_numbers`) for median/min/max/quartiles -- sympy's Rational/Integer
support ordinary Python ordering, so sorted() needs no custom key.

TI quartile method (the one plan step P16/S1's planner notes specify): q1
and q3 are each the median of a "half" of sorted_numbers, found by
_ti_halves -- when n is odd, the overall median sits at the middle index
and is left out of *both* halves (e.g. n=5 -> halves of 2 and 2, not 2 and
3, or 2 and 3); when n is even, the list splits into two equal halves with
nothing left out (e.g. n=6 -> halves of 3 and 3). _median itself is the
plain rule: the middle element for an odd-length list, the mean of the two
middle elements for an even-length one -- used both for the overall median
and, on each half, for q1/q3.

sx and sigma_x both start from the same sum of squared deviations from the
mean (`sum_sq`); sx divides by n-1 (sample) and sigma_x divides by n
(population), each under a sqrt(). Neither this function nor any of its
helpers guards against a degenerate n=1 input -- _ti_halves gives each
half 0 elements (nothing left to put in them once the single element is
excluded as "the median"), and _median then indexes that empty half,
raising IndexError before sx's own n-1=0 division is ever reached. This
module does not catch that; graphcalc/cli.py's own catch-all turns
whatever onevar() raises into the usual JSON 400 anyway (this product's
"never a 500" rule), the same backstop every other math-performing
handler already relies on for an exception its own try/except does not
anticipate.

Every statistic except n is returned as {"exact": str(sympy.simplify(v)),
"decimal": graphcalc.numfmt.format_decimal(v)} (12 significant digits,
this module's shared formatter) -- the same {"exact","decimal"} pair shape
graphcalc.graph's analyze()/table() responses already use. sympy's own
Pow evaluation already rationalizes a quotient under a sqrt() on
construction (e.g. sqrt(Rational(5, 2)) is built as sqrt(10)/2 directly),
so the simplify() call in _stat is mostly a belt-and-suspenders step here,
not what produces that form.

regression(model, x, y) is POST /api/stats/regression's own pure
computation (plan step P17/S1), living in this module since it shares
onevar's "parse each entry to an exact sympy number, raise CalcError on
anything that does not fit" shape -- the only difference is the numbers
come straight off the request body ("x"/"y") instead of out of a stored
list. Unlike a stored list's values, "x" and "y" are validated the same
way PUT /api/lists/<name> validates a "values" array (graphcalc.lists.
validate_list_values, reused here rather than reinvented): a non-list, an
empty or oversized one, or a non-string/unparseable entry is rejected the
same way. Each surviving string is then parsed by _to_exact_number, the
same helper onevar() uses, and checked for is_real -- a value that parses
but is not a plain real number (a bare symbol such as "x", "oo", or "zoo"
from a "1/0" entry) is rejected here, since least-squares arithmetic on a
symbolic value would not raise cleanly on its own.

"linear" (y = a*x + b) and "quadratic" (y = a*x**2 + b*x + c) are both
implemented, dispatched through the small _FITS table keyed by model name
so regression()'s own validation/response-building does not need to know
which fit it is calling. An unrecognized model name is CalcError the same
as any other bad input. The linear fit solves the least-squares normal
equations exactly with the input's own exact sympy numbers (no Rational()
reconstruction needed -- xs/ys are already exact): a*Sxx + b*Sx = Sxy,
a*Sx + b*n = Sy, solved directly for a and b. A zero denominator (n*Sxx -
Sx**2, zero exactly when every x is equal, including the single-point n=1
case) is CalcError("regression requires at least two distinct x values")
rather than a ZeroDivisionError -- this guard is also what keeps the later
curve-building step from ever dividing by a zero x-range.

The quadratic fit (plan step P17/S2) solves its own 3x3 normal equations
-- a*S4 + b*S3 + c*S2 = Sx2y, a*S3 + b*S2 + c*S1 = Sxy, a*S2 + b*S1 + c*n =
Sy, where Sk is sum(x**k) and Sx2y/Sxy are sum(x**2*y)/sum(x*y) -- exactly,
via sympy.Matrix.solve() on the input's own exact Rational/Integer sums (no
float ever enters, same as the linear fit). A singular coefficient matrix
(det() == 0, which happens with fewer than three distinct x values) is
CalcError("regression requires at least three distinct x values") rather
than letting Matrix.solve() raise its own ValueError.

r2 = 1 - SS_res/SS_tot is shared by every model; SS_tot = 0 (every y equal)
is also CalcError, rather than a response with an undefined r2.

Every coefficient, r2, and every "points"/"curve" entry is rendered with
format_decimal(simplify(value), sig=12) by _regression_decimal -- the same
"simplify, then format" order _stat uses above -- with a literal "-0"
normalized to "0" as a last defensive step; an exact-arithmetic fit (this
module parses every input as an exact Rational/Integer, same as onevar)
never actually produces that sign on a true zero, but the normalization
costs nothing and matches the planner notes' "clean zeros" requirement
literally. "curve" samples 50 x values evenly spaced from min(x) to
max(x) inclusive (both endpoints exact, computed directly from the exact
x-range rather than plot()'s float-pinned last sample) and predicts y at
each with the fit's own predict function.
"""

from sympy import Matrix, Rational, nsimplify, simplify, sqrt, sympify

from graphcalc.calc import CalcError
from graphcalc.lists import validate_list_values
from graphcalc.numfmt import format_decimal


def _to_exact_number(value: str):
    """Parse one stored list value string into an exact sympy number.

    Rational(value) handles every plain numeric literal this calculator's
    own grammar accepts as a list entry -- an integer, a signed integer, a
    decimal ("1.5"), or a fraction ("3/2") -- turning each into an exact
    Rational/Integer instead of an inexact Float. A value that is not
    plain-numeric (e.g. "sqrt(2)", "2+3") raises a TypeError inside
    Rational(); this falls back to nsimplify(sympify(value)) for that case,
    which parses it as a normal sympy expression and leaves an
    already-exact value exactly as it is (nsimplify only ever rewrites an
    inexact Float into a nearby exact closed form -- it is never lossy for
    a value that is already exact).
    """
    try:
        return Rational(value)
    except (TypeError, ValueError):
        return nsimplify(sympify(value))


def _stat(value) -> dict:
    """Wrap one computed statistic as {"exact": str, "decimal": str}.

    `value` is simplified once (sympy.simplify) before being rendered both
    ways, so "exact" always reads in its simplest closed form and
    "decimal" is format_decimal() (12 significant digits) of that same
    simplified value, not the pre-simplified one.
    """
    simplified = simplify(value)
    return {"exact": str(simplified), "decimal": format_decimal(simplified)}


def _median(sorted_numbers: list):
    """The median of an already-sorted list of exact sympy numbers.

    The middle element for an odd-length list; the mean of the two middle
    elements for an even-length one. Used both for the overall median and,
    on each TI-method half _ti_halves returns, for q1/q3.
    """
    count = len(sorted_numbers)
    mid = count // 2
    if count % 2 == 1:
        return sorted_numbers[mid]
    return (sorted_numbers[mid - 1] + sorted_numbers[mid]) / 2


def _ti_halves(sorted_numbers: list) -> tuple:
    """Split sorted_numbers into the TI method's lower/upper halves.

    When `sorted_numbers` has an odd length, the overall median sits at the
    middle index and is left out of *both* halves (plan step P16/S1's
    planner notes): e.g. [1,2,3,4,5] -> ([1,2], [4,5]), never a half that
    still includes the middle element. When the length is even, the list
    splits into two equal halves with nothing left out: [1,2,3,4,5,6] ->
    ([1,2,3], [4,5,6]).
    """
    count = len(sorted_numbers)
    mid = count // 2
    if count % 2 == 1:
        return sorted_numbers[:mid], sorted_numbers[mid + 1 :]
    return sorted_numbers[:mid], sorted_numbers[mid:]


def onevar(values: list) -> dict:
    """Compute one-variable statistics for a stored list's values.

    `values` is expected to be a non-empty list of stored list-entry
    strings (see this module's own docstring for the contract graphcalc/
    cli.py's _handle_stats_onevar relies on before calling this -- it is
    still this handler's job to reject a missing or undefined list before
    ever calling onevar(), since there is no values list at all in those
    cases). An empty `values` -- reachable through a hand-edited state
    file even though PUT /api/lists/<name> itself never stores one, see
    graphcalc.lists.validate_list_values -- raises CalcError("list is
    empty") here instead of being left to _handle_stats_onevar's own
    catch-all to turn whatever ZeroDivisionError/IndexError the division
    by n below would otherwise raise into a less specific 400.

    Returns {"n": int, "mean", "median", "sum", "sx", "sigma_x", "min",
    "q1", "q3", "max"}, each of the latter nine an {"exact","decimal"}
    pair (see _stat).
    """
    if not values:
        raise CalcError("list is empty")
    numbers = [_to_exact_number(value) for value in values]
    n = len(numbers)
    sorted_numbers = sorted(numbers)

    total = sum(numbers)
    mean = total / n
    median = _median(sorted_numbers)

    sum_sq = sum((x - mean) ** 2 for x in numbers)
    sx = sqrt(sum_sq / (n - 1))
    sigma_x = sqrt(sum_sq / n)

    lower_half, upper_half = _ti_halves(sorted_numbers)
    q1 = _median(lower_half)
    q3 = _median(upper_half)

    return {
        "n": n,
        "mean": _stat(mean),
        "median": _stat(median),
        "sum": _stat(total),
        "sx": _stat(sx),
        "sigma_x": _stat(sigma_x),
        "min": _stat(sorted_numbers[0]),
        "q1": _stat(q1),
        "q3": _stat(q3),
        "max": _stat(sorted_numbers[-1]),
    }


# POST /api/stats/regression (plan step P17/S1).

# 50 points across the data x-range -- "the curve has 50 points" (planner
# notes), not configurable by the request the way graph.py's plot()
# "samples" is.
CURVE_POINTS = 50


def _xy_to_numbers(values, label: str) -> list:
    """Validate and parse one of the request's "x"/"y" arrays.

    Reuses graphcalc.lists.validate_list_values for the exact same
    structural/per-entry check PUT /api/lists/<name> already applies to a
    "values" array: `values` must be a non-empty, non-oversized list of
    strings, each one a calculator expression graphcalc.calc.evaluate can
    parse. Every surviving string is then parsed into an exact sympy number
    by _to_exact_number (the same helper onevar() uses above), and checked
    for is_real -- a value that parses but is not a plain real number (a
    bare symbol such as "x" itself, "oo", or "zoo" from a "1/0" entry) is
    rejected here with CalcError, since the least-squares arithmetic below
    has no other way to raise cleanly on a symbolic value.

    `label` ("x" or "y") is only used to make a bad entry's message say
    which array it came from.
    """
    validate_list_values(values)
    numbers = [_to_exact_number(value) for value in values]
    for value, number in zip(values, numbers):
        if number.is_real is not True:
            raise CalcError(f"{label} value is not a real number: {value!r}")
    return numbers


def _fit_linear(xs: list, ys: list) -> tuple:
    """Least-squares fit y = a*x + b, solved exactly from the normal
    equations a*Sxx + b*Sx = Sxy, a*Sx + b*n = Sy.

    `xs`/`ys` are already exact sympy numbers (see _xy_to_numbers), so every
    sum below (and the a/b it produces) stays an exact Rational/Integer --
    no float ever enters this computation. The shared denominator
    n*Sxx - Sx**2 is zero exactly when every x value is equal (including
    the single-point n=1 case, where Sxx and Sx*Sx/n are trivially equal);
    that is CalcError rather than a silent ZeroDivisionError, and it is
    also what guarantees the x-range this function's caller later builds
    "curve" from (min(xs)..max(xs)) is never a single degenerate point.

    Returns ({"a": exact, "b": exact}, predict) where predict(x) = a*x + b.
    """
    n = len(xs)
    sx = sum(xs)
    sxx = sum(value * value for value in xs)
    sy = sum(ys)
    sxy = sum(x_value * y_value for x_value, y_value in zip(xs, ys))

    denom = n * sxx - sx * sx
    if denom == 0:
        raise CalcError("regression requires at least two distinct x values")
    a = (n * sxy - sx * sy) / denom
    b = (sxx * sy - sx * sxy) / denom

    def predict(x_value):
        return a * x_value + b

    return {"a": a, "b": b}, predict


def _fit_quadratic(xs: list, ys: list) -> tuple:
    """Least-squares fit y = a*x**2 + b*x + c, solved exactly from the 3x3
    normal equations a*S4 + b*S3 + c*S2 = Sx2y, a*S3 + b*S2 + c*S1 = Sxy,
    a*S2 + b*S1 + c*n = Sy (plan step P17/S2).

    `xs`/`ys` are already exact sympy numbers (see _xy_to_numbers), so every
    power sum below stays an exact Rational/Integer -- no float ever enters
    this computation, the same as _fit_linear above. The coefficient matrix
    is singular (det() == 0) with fewer than three distinct x values
    (including every xs value equal, or exactly two distinct values); that
    is CalcError rather than letting Matrix.solve() raise its own
    ValueError for a non-invertible matrix.

    Returns ({"a": exact, "b": exact, "c": exact}, predict) where
    predict(x) = a*x**2 + b*x + c.
    """
    n = len(xs)
    s1 = sum(xs)
    s2 = sum(value * value for value in xs)
    s3 = sum(value**3 for value in xs)
    s4 = sum(value**4 for value in xs)
    sy = sum(ys)
    sxy = sum(x_value * y_value for x_value, y_value in zip(xs, ys))
    sx2y = sum(x_value * x_value * y_value for x_value, y_value in zip(xs, ys))

    matrix = Matrix([[s4, s3, s2], [s3, s2, s1], [s2, s1, n]])
    if matrix.det() == 0:
        raise CalcError("regression requires at least three distinct x values")
    a, b, c = matrix.solve(Matrix([sx2y, sxy, sy]))

    def predict(x_value):
        return a * x_value**2 + b * x_value + c

    return {"a": a, "b": b, "c": c}, predict


# Keyed by the request's "model" value; each entry is a _fit_linear-shaped
# function (xs, ys) -> (coefficients, predict).
_FITS = {"linear": _fit_linear, "quadratic": _fit_quadratic}


def _regression_decimal(value) -> str:
    """Render one regression coefficient/r2/points-or-curve entry as a
    12-significant-digit decimal string.

    Same "simplify, then format_decimal" order _stat uses above. A literal
    "-0" is normalized to "0" as a last defensive step -- this module's
    exact Rational/Integer arithmetic never actually produces that sign on
    a true zero (unlike a float computation would), but the planner notes
    ask for "clean zeros ('0', not '-0' ...)" literally, so this is cheap
    insurance rather than something expected to ever actually trigger.
    """
    text = format_decimal(simplify(value), sig=12)
    return "0" if text == "-0" else text


def regression(model, x: list, y: list) -> dict:
    """Compute a least-squares regression fit for POST /api/stats/regression.

    `model` must be a key of _FITS ("linear" or "quadratic"); anything else
    -- including a non-string -- is CalcError(f"unknown model: ...").
    `x` and `y` are each validated
    and parsed by _xy_to_numbers (see its own docstring); a mismatched
    length between them is CalcError here, checked only after both have
    already been validated individually, so a structurally bad `x` or `y`
    is still reported as that specific problem rather than a generic
    length mismatch.

    The fit itself (_FITS[model]) raises CalcError for a degenerate input
    (e.g. every x value equal); this function does not catch that, the
    same backstop-by-the-caller pattern onevar() uses for its own
    IndexError. r2 = 1 - SS_res/SS_tot is computed from the fit's own
    predict function; SS_tot = 0 (every y value equal, making r2
    undefined) is CalcError rather than a response with a meaningless r2.

    Returns {"model", "coefficients": {name: decimal str, ...}, "r2":
    decimal str, "points": [[x decimal, y decimal], ...], "curve": [[x
    decimal, y decimal], ...]}. "points" holds the original ("x","y") pairs
    in request order; "curve" holds CURVE_POINTS (50) pairs evenly spaced
    from min(x) to max(x) inclusive (both endpoints exact, unlike
    graph.py's plot() which pins only its last float sample), each paired
    with the fit's predicted y. Every decimal string is _regression_decimal
    (12 significant digits, clean zeros).
    """
    if not isinstance(model, str) or model not in _FITS:
        raise CalcError(f"unknown model: {model!r}")

    xs = _xy_to_numbers(x, "x")
    ys = _xy_to_numbers(y, "y")
    if len(xs) != len(ys):
        raise CalcError("x and y must have the same length")

    coefficients, predict = _FITS[model](xs, ys)

    mean_y = sum(ys) / len(ys)
    ss_tot = sum((y_value - mean_y) ** 2 for y_value in ys)
    if ss_tot == 0:
        raise CalcError("regression requires y values that are not all equal")
    ss_res = sum((y_value - predict(x_value)) ** 2 for x_value, y_value in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot

    xmin, xmax = min(xs), max(xs)
    step = (xmax - xmin) / (CURVE_POINTS - 1)
    curve_xs = [xmin + index * step for index in range(CURVE_POINTS)]

    return {
        "model": model,
        "coefficients": {name: _regression_decimal(value) for name, value in coefficients.items()},
        "r2": _regression_decimal(r2),
        "points": [[_regression_decimal(x_value), _regression_decimal(y_value)] for x_value, y_value in zip(xs, ys)],
        "curve": [[_regression_decimal(x_value), _regression_decimal(predict(x_value))] for x_value in curve_xs],
    }
