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
"""

from sympy import Rational, nsimplify, simplify, sqrt, sympify

from graphcalc.calc import CalcError
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
