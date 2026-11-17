"""Graphing core for POST /api/graph/plot, POST /api/graph/window and
POST /api/graph/analyze (plan steps P10/S1, P11/S1 and P12/S1).

plot(body) and window(body) are the only things graphcalc/cli.py calls
from here; neither ever touches the network. plot() deliberately does
not re-implement the calculator's own
parsing/safety rules -- grammar restrictions, the no-sympy-constructors
guard, and the is_power_too_large freeze guard -- it reuses
graphcalc.calc.evaluate() for that, the exact same way a stored "f(x):=expr"
function definition already does: `symbols=["x"]` binds "x" to a plain
sympy Symbol, the same mechanism a function definition's own params use, so
"x" is a free variable in the parsed expression rather than one this module
has to special-case through its own copy of the grammar.

evaluate() itself raises graphcalc.calc.CalcError (never any other
exception) for a syntax error, an unknown function call, or an expression
flagged by the freeze guard; this module never catches that -- it
propagates out of plot() unchanged, so graphcalc.cli must turn *both*
GraphError and CalcError into a 400 for this route, not just GraphError.

"x is the only free variable" (plan step P10's planner notes) is, however,
a rule evaluate() itself has no opinion on -- it happily simplifies "x+y"
into the symbolic string "x + y" for a CAS-style query. This module adds
that check itself, in _parse_function, after evaluate() returns: any free
symbol other than "x" left in the simplified result is a GraphError, never
silently plotted as if it were zero.

analyze() (plan step P12/S1, extended by P12/S2) reuses the same
_parse_function and _evaluate_at this module already built for plot() --
"value" substitutes x directly; "zero" samples and bisects numerically,
then snaps the result to an exact sympy value when nsimplify finds one
that still solves the equation within tolerance. "minimum" and "maximum"
(P12/S2) instead sample densely for the best (lowest/highest) finite
value, refine it with golden-section search in the bracket around that
sample, then snap the refined x (and, independently, y) to an exact
sympy value the same way, but checked against "no worse than the refined
value" rather than "solves the equation". The two exception types
propagate out of analyze() exactly like they do out of plot(): a
GraphError for a bad request, or calc.CalcError unchanged from
_parse_function. "intersection" (P12/S3) parses both "f" and "g", then
reuses the exact same zero-finder on h = f - g; see analyze()'s own
docstring.
"""

import math

from sympy import Float, Symbol, nan, nsimplify, oo, sympify, zoo

from graphcalc.calc import evaluate
from graphcalc.numfmt import format_decimal

# Fixed, distinct colors for the four graphable slots (plan step P10's
# planner notes: "Fixed distinct colors for f1-f4"). Picked from a standard
# categorical chart palette so each is easy to tell apart at a glance; the
# exact shades are not part of any acceptance criterion, only that every
# slot's color differs from every other slot's.
SERIES_COLORS = {
    "f1": "#1f77b4",  # blue
    "f2": "#d62728",  # red
    "f3": "#2ca02c",  # green
    "f4": "#9467bd",  # purple
}

# "bounded samples" (plan step P10's planner notes): at least 2, so
# "evenly spaced x values ... including both ends" always has two distinct
# ends to include; at most 10,000, generously more than any browser canvas
# needs, so a client cannot force this single-threaded server into building
# (and parsing/substituting into) an unbounded list.
MIN_SAMPLES = 2
MAX_SAMPLES = 10_000

_X = Symbol("x")


class GraphError(Exception):
    """A user-facing graph error: a bad function slot, window, or sample count.

    graphcalc.calc.CalcError (bad syntax, an unknown function call, or an
    oversized power) can also escape plot() unchanged -- see this module's
    own docstring -- so graphcalc.cli must treat both exception types as a
    400 for POST /api/graph/plot.
    """


def _parse_function(expr_text):
    """Return a sympy expression for `expr_text`, with "x" its only allowed
    free variable, or None when the expression is unconditionally undefined
    (e.g. "1/0", which never mentions "x" at all).

    Reuses graphcalc.calc.evaluate(expr_text, mode="rad", symbols=["x"]) for
    the actual parse+simplify -- the same grammar check, freeze guard,
    no-sympy-constructors whitelist, and restricted parse_expr call a stored
    function definition's body already goes through. Can raise CalcError,
    uncaught (see the module docstring).

    evaluate()'s own "_result_srepr" is None only when its domain_error is
    set, which only happens when the *whole* simplified result -- not one
    sample of it -- is itself zoo/oo/-oo/nan, i.e. the expression has no "x"
    in it at all and is unconditionally undefined. There is nothing to
    substitute into in that case, so every sample for this function is
    null; a genuinely x-dependent domain issue (e.g. "1/x" at x=0) is never
    caught here at all -- it still parses to the symbolic "1/x", and is only
    ever discovered per-sample, in _evaluate_at below.

    srepr() (not evaluate()'s plain "exact" string) is sympify()'d back into
    a real sympy object, the same rebuild graphcalc.calc._rebuild_stored_value
    and _function_locals already use and for the same reason: a bare name
    such as "beta" in a plain str() round-trip can resolve against sympy's
    own namespace instead of staying the free Symbol the user meant, while
    srepr()'s quoted Symbol('beta') constructor argument never can.
    """
    result = evaluate(expr_text, mode="rad", symbols=["x"])
    result_srepr = result.get("_result_srepr")
    if result_srepr is None:
        return None
    parsed = sympify(result_srepr)
    extra = parsed.free_symbols - {_X}
    if extra:
        name = sorted(str(symbol) for symbol in extra)[0]
        raise GraphError(f"unknown variable in function: {name!r}")
    return parsed


def _evaluate_at(parsed, x_value):
    """Return parsed(x_value) as a plain float, or None for a gap.

    None (-> JSON null) covers everything the acceptance criteria call out:
    a non-real result (e.g. sqrt of a negative number), an infinite one
    (division by zero -> sympy's zoo/oo/-oo), and nan (an indeterminate
    form). `parsed` is None for a function _parse_function already found
    unconditionally undefined -- every sample is null then, without doing
    any substitution at all.

    Substituting a sympy Float (not a plain Python float, and not the
    original Integer/Rational `x_value` might otherwise look like) is what
    makes "1/x" at x=0 resolve to the symbolic zoo instead of raising
    Python's own ZeroDivisionError -- sympy's Pow(0, -1) is defined as zoo,
    a deliberate symbolic result, but only when the 0 it sees is a sympy
    object, not a raw Python float division.

    Wrapped in one broad except so a substitution/evalf failure this module
    did not anticipate is also a gap, never a 500 propagating out of the
    whole request -- graphcalc.cli's own catch-all is the last line of
    defense for everything else in the request, but one bad sample should
    not need to fall all the way back to that either.
    """
    if parsed is None:
        return None
    try:
        value = parsed.subs(_X, Float(x_value)).evalf()
    except Exception:
        return None
    if value in (zoo, oo, -oo) or value == nan:
        return None
    if not getattr(value, "is_real", False):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _evaluate_exact_at(parsed, x_value):
    """Return parsed(x_value) still as a sympy expression (not narrowed to
    a plain float), or None for a gap -- used only by analyze()'s
    "intersection" operation (plan step P12/S3).

    The gap rules are the same ones _evaluate_at applies (a non-real
    result, an infinite zoo/oo/-oo, or nan), checked the same way, via
    evalf(). The difference is what gets returned on success: `x_value`
    here can itself already be an exact sympy value (e.g. the Integer 1
    _snap_root snapped an intersection's x to), and substituting *that*
    straight into `parsed` -- the way _snap_extremum's own "candidate_y =
    parsed.subs(_X, candidate_x)" already does for minimum/maximum --
    keeps y exact too (e.g. f(1) substituted into "x**2" is exactly the
    Integer 1, not a rounded double). _evaluate_at cannot be reused for
    this: it always wraps its x_value in a plain-precision Float first
    (so "1/x" at x=0 reads as sympy's symbolic zoo rather than a Python
    ZeroDivisionError), which loses that exactness, and raises outright
    for an exact irrational like sqrt(2) (sympy's Float() constructor
    only accepts an already-numeric argument, not a general expression).
    format_decimal rounds an exact sympy value to its 12 significant
    digits exactly as well as it rounds a plain float, so there is no
    reason to narrow to double precision before formatting when the exact
    value is already in hand.
    """
    if parsed is None:
        return None
    try:
        candidate = parsed.subs(_X, x_value)
        value = candidate.evalf()
    except Exception:
        return None
    if value in (zoo, oo, -oo) or value == nan:
        return None
    if not getattr(value, "is_real", False):
        return None
    try:
        float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return candidate


def _finite_number(container, key, label):
    """Return container[key] as a float, or raise GraphError.

    Shared by _window_bound (label "window parameter", for plot()'s own
    window) and window()'s own "factor"/"dx"/"dy" body parameters (plan
    step P11/S1) -- the same two rules apply to all of them:

    A bool is rejected even though Python's bool is an int subclass --
    {"xmin": true, ...} should 400, not silently become 1.0.

    math.isfinite rejects inf/-inf/nan too: Python's json module accepts
    the bare (unquoted) tokens Infinity, -Infinity and NaN as a
    non-standard, but on-by-default, extension, so a literal request body
    of {"xmin": Infinity, ...} decodes to a real Python float('inf')
    rather than failing to parse at all -- a non-finite bound must still
    400, the same as a missing or non-numeric one, since a "less than"
    comparison built on it can mistakenly "pass" with an infinite value.
    """
    value = container.get(key) if isinstance(container, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GraphError(f"missing or invalid {label}: {key}")
    value = float(value)
    if not math.isfinite(value):
        raise GraphError(f"{label} must be finite: {key}")
    return value


def _window_bound(window, key):
    """Return window[key] as a float, or raise GraphError.

    See _finite_number for the two rules this enforces (non-bool number,
    finite).
    """
    return _finite_number(window, key, "window parameter")


def _plain_number(value):
    """Return `value` as an int when it is a whole number, else as a float.

    Plan step P11's planner notes: "Return plain numbers (ints when
    whole)." window()'s own arithmetic (halving/doubling a span, adding a
    pan delta) is plain float math throughout, so a result that is
    mathematically a whole number -- e.g. the acceptance criteria's own
    -5.0 from zooming -10..10 in by a factor of 2 -- would otherwise
    round-trip through JSON as -5.0, not the -5 the criteria list. math.
    isfinite guards int(value) itself: int() on an infinite or nan float
    raises, but window()'s own inputs are already validated finite before
    any arithmetic happens, so this is a defensive check, not a path any
    acceptance criterion reaches.
    """
    if math.isfinite(value) and value == int(value):
        return int(value)
    return value


def window(body):
    """Build the POST /api/graph/window response dict for `body` (plan
    step P11/S1).

    `body` is {"action": "zoom_in" | "zoom_out" | "pan" | "standard",
    "factor", "dx", "dy", "window"}. Returns {"xmin", "xmax", "ymin",
    "ymax"} as plain numbers (see _plain_number).

    "standard" ignores every other key and always answers the fixed
    -10..10 window on both axes (PRODUCT.md's own wording for P11),
    before any window/factor/dx/dy validation runs.

    Every other action first resolves the window to operate on:
    "window" missing (absent or JSON null) defaults to that same standard
    -10..10 window -- this is what lets the acceptance criteria's own pan
    example, {"action":"pan","dx":1,"dy":-2} with no "window" key at all,
    read as "on the standard window" -- otherwise "window" must be an
    object with finite, non-bool xmin/xmax/ymin/ymax (_window_bound) with
    xmin < xmax and ymin < ymax, the same rules plot() enforces on the
    same shape.

    "zoom_in"/"zoom_out" then needs a "factor": a finite, non-bool,
    strictly positive number (_finite_number plus its own > 0 check) --
    zero or a negative factor would collapse or invert the window, never
    a sensible zoom. Zooms about the window's own center: factor 2 halves
    (zoom_in) or doubles (zoom_out) each axis's half-span, recentered on
    the unchanged (xmin+xmax)/2 and (ymin+ymax)/2.

    "pan" needs "dx" and "dy": finite, non-bool numbers (_finite_number),
    added straight onto xmin/xmax (dx) and ymin/ymax (dy) -- a pure
    translation, so the window's width and height are unchanged.

    Any other "action" value (including a missing one) is a GraphError,
    a 400 for graphcalc.cli -- "an unknown action returns 400" (PRODUCT.md
    P11's own acceptance criterion).
    """
    if not isinstance(body, dict):
        raise GraphError("invalid request body")

    action = body.get("action")
    if action == "standard":
        return {"xmin": -10, "xmax": 10, "ymin": -10, "ymax": 10}
    if action not in ("zoom_in", "zoom_out", "pan"):
        raise GraphError(f"unknown action: {action!r}")

    raw_window = body.get("window")
    if raw_window is None:
        xmin, xmax, ymin, ymax = -10.0, 10.0, -10.0, 10.0
    elif isinstance(raw_window, dict):
        xmin = _window_bound(raw_window, "xmin")
        xmax = _window_bound(raw_window, "xmax")
        ymin = _window_bound(raw_window, "ymin")
        ymax = _window_bound(raw_window, "ymax")
        if xmin >= xmax:
            raise GraphError("window xmin must be less than xmax")
        if ymin >= ymax:
            raise GraphError("window ymin must be less than ymax")
    else:
        raise GraphError("window must be an object")

    if action in ("zoom_in", "zoom_out"):
        factor = _finite_number(body, "factor", "factor")
        if factor <= 0:
            raise GraphError("factor must be positive")
        scale = (1.0 / factor) if action == "zoom_in" else factor
        xcenter = (xmin + xmax) / 2.0
        ycenter = (ymin + ymax) / 2.0
        xhalf = (xmax - xmin) / 2.0 * scale
        yhalf = (ymax - ymin) / 2.0 * scale
        xmin, xmax = xcenter - xhalf, xcenter + xhalf
        ymin, ymax = ycenter - yhalf, ycenter + yhalf
    else:  # pan
        dx = _finite_number(body, "dx", "dx")
        dy = _finite_number(body, "dy", "dy")
        xmin, xmax = xmin + dx, xmax + dx
        ymin, ymax = ymin + dy, ymax + dy

    return {
        "xmin": _plain_number(xmin),
        "xmax": _plain_number(xmax),
        "ymin": _plain_number(ymin),
        "ymax": _plain_number(ymax),
    }


def plot(body):
    """Build the POST /api/graph/plot response dict for `body`.

    `body` is {"functions": {"f1".."f4": expr}, "window": {"xmin", "xmax",
    "ymin", "ymax"}, "samples": int}. Returns {"x": [float, ...], "series":
    {name: {"color": "#rrggbb", "y": [float | None, ...]}}}.

    Raises GraphError for:
    - a missing/non-dict "functions", or a key in it other than "f1".."f4"
      (SERIES_COLORS' own keys) -- covers both an empty functions mapping
      and "a fifth function" (plan step P10's acceptance criteria): any
      slot name outside f1-f4, including a literal "f5", is rejected before
      any parsing happens.
    - a function's expression not being a string (plan step P10/S3), e.g.
      {"f1": 5} -- also rejected before any parsing happens, so this is a
      GraphError, not the CalcError("missing parameter: expr")
      graphcalc.calc.evaluate would otherwise raise for the same input.
    - a missing/non-dict "window", or a missing/non-numeric/non-finite
      xmin/xmax/ymin/ymax (see _window_bound).
    - xmin >= xmax (the acceptance criteria's own wording), or ymin >= ymax
      (plan step P10/S3, the same rule applied to the other axis).
    - a missing/non-int "samples", or one outside [MIN_SAMPLES, MAX_SAMPLES].

    graphcalc.calc.CalcError can also escape unchanged, from _parse_function
    -- see the module docstring. Both exception types are 400s, handled by
    graphcalc.cli, never 500s.

    The x values are `samples` evenly spaced floats from xmin to xmax,
    including both ends: the last one is pinned to the exact float `xmax`
    rather than left to accumulate floating-point drift from repeated
    addition.
    """
    if not isinstance(body, dict):
        raise GraphError("invalid request body")

    functions = body.get("functions")
    if not isinstance(functions, dict) or not functions:
        raise GraphError("missing parameter: functions")
    for name, expr_text in functions.items():
        if name not in SERIES_COLORS:
            raise GraphError(f"unknown function slot: {name!r}")
        if not isinstance(expr_text, str):
            raise GraphError(f"function {name} must be a string")

    window = body.get("window")
    if not isinstance(window, dict):
        raise GraphError("missing parameter: window")
    xmin = _window_bound(window, "xmin")
    xmax = _window_bound(window, "xmax")
    ymin = _window_bound(window, "ymin")
    ymax = _window_bound(window, "ymax")
    if xmin >= xmax:
        raise GraphError("window xmin must be less than xmax")
    if ymin >= ymax:
        raise GraphError("window ymin must be less than ymax")

    samples = body.get("samples")
    if isinstance(samples, bool) or not isinstance(samples, int):
        raise GraphError("missing parameter: samples")
    if samples < MIN_SAMPLES or samples > MAX_SAMPLES:
        raise GraphError(f"samples must be between {MIN_SAMPLES} and {MAX_SAMPLES}")

    step = (xmax - xmin) / (samples - 1)
    xs = [xmin + index * step for index in range(samples)]
    xs[-1] = xmax

    series = {}
    for name, expr_text in functions.items():
        parsed = _parse_function(expr_text)
        series[name] = {
            "color": SERIES_COLORS[name],
            "y": [_evaluate_at(parsed, value) for value in xs],
        }

    return {"x": xs, "series": series}


# POST /api/graph/analyze (plan step P12/S1).

ANALYZE_OPERATIONS = ("value", "zero", "minimum", "maximum", "intersection")

# "no zero or intersection: 200 with domain_error" (plan step P12's planner
# notes): this exact wording is also the acceptance criterion's own text
# for "zero of x^2+1 on [-5,5]". DOMAIN_ERROR_NO_VALUE is this module's own
# choice for "value"'s analogous gap (e.g. "1/x" at x=0) -- not called out
# by name in any acceptance criterion, but "a gap returns domain_error
# instead of y" (the planner notes) still needs some message, not None.
DOMAIN_ERROR_NO_ZERO = "no zero in interval"
DOMAIN_ERROR_NO_VALUE = "no value at that point"

# "scan [lower, upper] for sign changes or near-zero samples" (planner
# notes): 400 evenly spaced samples is generous enough to catch a sign
# change on any interval an acceptance criterion or a reasonable user would
# type, while staying far short of plot()'s own MAX_SAMPLES -- this is a
# fixed-cost scan a single request pays once, not something a client size
# controls.
_ZERO_SCAN_INTERVALS = 400
# A sample within this of zero is treated as a root outright, before any
# bisection -- catches a root that sits exactly on (or extremely near) a
# scan point, including a double root such as "x^2" at x=0 that never
# actually changes sign.
_ZERO_NEAR_ZERO_TOLERANCE = 1e-7
# After bisection (or a near-zero sample, or an nsimplify snap), the
# candidate root is only accepted when |f(candidate)| is within this of
# zero -- the guard that turns a sign change straddling a pole (e.g. "1/x"
# on [-1,1], which crosses from negative to positive *through* an
# undefined point, never an actual zero) back into "no zero found", since
# the function's value near a pole is huge, never small.
_ZERO_RESIDUAL_TOLERANCE = 1e-6
# 100 bisections on even the widest realistic [lower, upper] interval
# narrows the bracket far past double-precision float resolution; the
# early-exit below (bracket width under 1e-13) means this count is a safe
# ceiling, not something every call actually spends in full.
_BISECTION_ITERATIONS = 100

# "minimum"/"maximum" (plan step P12/S2): the same "sample densely, then
# refine" shape as "zero" above, but hunting for the best (lowest/highest)
# finite sample instead of a sign change. Reuses the same scan count as
# _ZERO_SCAN_INTERVALS -- a fixed-cost scan a single request pays once,
# not something a client's input can grow.
_EXTREMUM_SCAN_INTERVALS = 400
# Golden-section search on the bracket around the best sample. 100
# iterations on even the widest realistic bracket narrows it far past
# double-precision resolution; the early-exit below (bracket width under
# 1e-14) means this count is a safe ceiling, not something every call
# actually spends in full -- the same shape as _BISECTION_ITERATIONS.
_GOLDEN_SECTION_ITERATIONS = 100
# An nsimplify snap of an extremum's x (or, failing that, its bare y) is
# only accepted when it is no worse than this, compared to the refined
# numeric value it would replace -- "no worse" rather than "near zero",
# since an extremum has no equation to re-solve the way a root does (see
# _snap_root). Matches _ZERO_RESIDUAL_TOLERANCE's own magnitude: both
# exist to separate "numerical noise in the last few bits" from "nsimplify
# proposed something that is not actually equivalent".
_EXTREMUM_SNAP_TOLERANCE = 1e-6
# "minimum"/"maximum" (plan step P12's planner notes): "If f has no finite
# values on the interval, return a domain_error constant and null x/y."
# The operation's own name is substituted in, so the message reads "no
# minimum in interval" or "no maximum in interval" -- the same shape as
# DOMAIN_ERROR_NO_ZERO's "no zero in interval", just parameterized since
# this one constant covers both operations.
DOMAIN_ERROR_NO_EXTREMUM_TEMPLATE = "no {operation} in interval"

# "intersection" (plan step P12/S3): "run the S1 zero-finder on h = f - g
# ... when no root exists, return domain_error with x and y null" (planner
# notes). A distinct constant from DOMAIN_ERROR_NO_ZERO, even though "zero"
# of h would read identically, because this is "intersection"'s own
# domain_error for "intersection"'s own request -- a client that posted
# {"operation": "intersection", ...} should see a message that says so,
# not "no zero in interval" for an "f" and "g" it never asked to be
# compared against 0.
DOMAIN_ERROR_NO_INTERSECTION = "no intersection in interval"


def _require_expr(body, key):
    """Return body[key] as a non-empty-type-checked string, or raise
    GraphError.

    Shared by analyze()'s "f" (always required) and "g" (required only
    for "intersection"). Both are only ever handed to _parse_function next,
    which goes through graphcalc.calc.evaluate -- a non-string value (None
    because the key is missing entirely, or the wrong JSON type, e.g.
    {"f": 5}) must never reach that call at all: evaluate() would instead
    raise its own, differently-worded CalcError ("missing parameter:
    expr"), the same distinction plot()'s own per-slot string check draws
    (see this module's own plot(), and its docstring).
    """
    value = body.get(key)
    if value is None:
        raise GraphError(f"missing parameter: {key}")
    if not isinstance(value, str):
        raise GraphError(f"{key} must be a string")
    return value


def _bisect_root(parsed, lower, upper, f_lower, f_upper):
    """Narrow [lower, upper] -- a bracket already known to straddle a sign
    change, with f_lower/f_upper the (nonzero) samples at each end -- to a
    single root by bisection, then return it as a plain float, or None.

    None covers two cases, both deliberate: a midpoint sample that is
    itself a gap (_evaluate_at returns None, e.g. the bracket straddles
    "1/x"'s pole at x=0 exactly) stops the bisection immediately rather
    than bisecting around a hole it cannot evaluate through; and a
    bracket that does converge, but to a point where |f| is not actually
    within _ZERO_RESIDUAL_TOLERANCE of zero (the pole case the module
    constant's own docstring describes, when the midpoint samples happen
    to land off the exact pole), is rejected by the residual check at the
    end rather than reported as a false root.
    """
    for _ in range(_BISECTION_ITERATIONS):
        mid = (lower + upper) / 2.0
        f_mid = _evaluate_at(parsed, mid)
        if f_mid is None:
            return None
        if f_mid == 0:
            lower = upper = mid
            break
        if (f_mid < 0) == (f_lower < 0):
            lower, f_lower = mid, f_mid
        else:
            upper, f_upper = mid, f_mid
        if upper - lower < 1e-13:
            break
    root = (lower + upper) / 2.0
    residual = _evaluate_at(parsed, root)
    if residual is None or abs(residual) > _ZERO_RESIDUAL_TOLERANCE:
        return None
    return root


def _scan_for_root(parsed, lower, upper):
    """Return a root of `parsed` in [lower, upper] as a plain float, or
    None when the scan finds none.

    `_ZERO_SCAN_INTERVALS` evenly spaced samples (including both ends) are
    taken first. Any sample within `_ZERO_NEAR_ZERO_TOLERANCE` of zero is
    returned immediately, leftmost first -- this is what catches a double
    root (e.g. "x^2" at x=0) that a sign-change scan alone would miss
    entirely, since the function never actually goes negative. Only when
    no sample itself reads as a root does this fall back to scanning
    consecutive sample pairs for an actual sign change (skipping any pair
    with a gap sample), bisecting the first one found with _bisect_root.
    A sign change can still fail to yield a root (see _bisect_root's own
    docstring, the pole case); the scan then keeps looking at the next
    pair rather than stopping there.
    """
    step = (upper - lower) / _ZERO_SCAN_INTERVALS
    xs = [lower + index * step for index in range(_ZERO_SCAN_INTERVALS + 1)]
    xs[-1] = upper
    ys = [_evaluate_at(parsed, value) for value in xs]

    for x_value, y_value in zip(xs, ys):
        if y_value is not None and abs(y_value) <= _ZERO_NEAR_ZERO_TOLERANCE:
            return x_value

    for index in range(len(xs) - 1):
        f_lower, f_upper = ys[index], ys[index + 1]
        if f_lower is None or f_upper is None:
            continue
        if (f_lower < 0) != (f_upper < 0):
            root = _bisect_root(parsed, xs[index], xs[index + 1], f_lower, f_upper)
            if root is not None:
                return root
    return None


def _snap_root(parsed, root):
    """Try to replace a numeric `root` (a plain float) with a simpler exact
    sympy value (e.g. sqrt(2), or the Integer 2), or return None.

    sympy's nsimplify(Float(root), rational=False) is what the planner
    notes mean by "snap the root to an exact value" -- it looks for a
    simple closed form (an integer, a small rational, a recognizable
    constant or radical) close to the float. "rational=False" lets it
    recognize a form like sqrt(2) rather than only ever rounding to the
    nearest fraction. The snap is only ever used when the snapped value,
    substituted back into `parsed`, still gives |f| within
    _ZERO_RESIDUAL_TOLERANCE of zero -- nsimplify can propose a value close
    to the float that does not actually solve the equation, and that must
    never corrupt an otherwise-good numeric root. Any failure along the
    way (nsimplify itself, the substitution, or a non-finite/non-real
    residual) is also treated as "no snap available", not an error --
    analyze() falls back to the plain float root instead.
    """
    try:
        snapped = nsimplify(Float(root), rational=False)
    except Exception:
        return None
    try:
        residual = float(parsed.subs(_X, snapped).evalf())
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(residual) or abs(residual) > _ZERO_RESIDUAL_TOLERANCE:
        return None
    return snapped


def _golden_section_minimize(func, a, b, iterations=_GOLDEN_SECTION_ITERATIONS):
    """Minimize `func` over [a, b] by golden-section search, returning the
    minimizing x as a plain float.

    `func` already folds in the sign flip "maximum" needs (see
    _find_extremum, which is the only caller) and already turns a gap
    into +inf, so this never has to special-case either -- it only ever
    sees a plain float in, a plain float out, the contract plain
    golden-section search assumes. Iterates a fixed number of times
    (_GOLDEN_SECTION_ITERATIONS, ample for double-precision resolution on
    any realistic bracket) with an early exit once the bracket itself is
    narrower than double precision can usefully subdivide -- the same
    shape as _bisect_root's own loop.
    """
    if a > b:
        a, b = b, a
    golden_ratio = (math.sqrt(5.0) - 1.0) / 2.0
    c = b - golden_ratio * (b - a)
    d = a + golden_ratio * (b - a)
    f_c = func(c)
    f_d = func(d)
    for _ in range(iterations):
        if b - a < 1e-14:
            break
        if f_c < f_d:
            b, d, f_d = d, c, f_c
            c = b - golden_ratio * (b - a)
            f_c = func(c)
        else:
            a, c, f_c = c, d, f_d
            d = a + golden_ratio * (b - a)
            f_d = func(d)
    return (a + b) / 2.0


def _snap_extremum(parsed, x_value, y_value, is_minimum):
    """Return (x_display, y_display) for an extremum already refined to
    `x_value`/`y_value` (plain floats), snapping each to a simpler exact
    sympy value with nsimplify when the snap is "no worse than" (planner
    notes) the numeric value it would replace.

    x and y are snapped independently, for two different reasons:

    x's snap is only accepted when f at the snapped x -- recomputed
    exactly, by substituting the snapped sympy value straight into
    `parsed` rather than evalf-ing first -- is not worse than `y_value`
    within _EXTREMUM_SNAP_TOLERANCE: no larger for a minimum, no smaller
    for a maximum. An extremum has no equation to re-solve the way a root
    does (_snap_root's own residual-near-zero check); "no worse" is the
    closest equivalent. A snap that is an actual improvement (closer to
    the true extremum than the golden-section refinement itself landed)
    is also accepted, not just an exact tie.

    When x's snap is accepted, y is then recomputed from that exact x --
    e.g. x=1 substituted into "x**2-2*x" is exactly -1, no further
    rounding needed -- so y is already exact and is returned as-is,
    without a separate nsimplify pass.

    When x's snap is not available (nsimplify failed, or it changed the
    value for the worse), y is instead snapped on its own, as a bare
    number with nothing to re-evaluate it against but the float itself:
    accepted only when the snapped value's own float evalf is within
    _EXTREMUM_SNAP_TOLERANCE of `y_value`.

    Never raises and never returns None for either half of the pair --
    an unsnapped value falls back to the plain float it was given.
    """
    snapped_x = None
    snapped_y = None
    try:
        candidate_x = nsimplify(Float(x_value), rational=False)
    except Exception:
        candidate_x = None
    if candidate_x is not None:
        try:
            candidate_y = parsed.subs(_X, candidate_x)
            candidate_y_float = float(candidate_y.evalf())
        except Exception:
            candidate_y_float = None
        if candidate_y_float is not None and math.isfinite(candidate_y_float):
            worse = (
                candidate_y_float > y_value + _EXTREMUM_SNAP_TOLERANCE
                if is_minimum
                else candidate_y_float < y_value - _EXTREMUM_SNAP_TOLERANCE
            )
            if not worse:
                snapped_x, snapped_y = candidate_x, candidate_y

    if snapped_x is not None:
        return snapped_x, snapped_y

    try:
        candidate_only_y = nsimplify(Float(y_value), rational=False)
        candidate_only_y_float = float(candidate_only_y.evalf())
    except Exception:
        return x_value, y_value
    if (
        math.isfinite(candidate_only_y_float)
        and abs(candidate_only_y_float - y_value) <= _EXTREMUM_SNAP_TOLERANCE
    ):
        return x_value, candidate_only_y
    return x_value, y_value


def _find_extremum(parsed, lower, upper, is_minimum):
    """Return (x_display, y_display) for the minimum (is_minimum=True) or
    maximum of `parsed` on [lower, upper], or None when `parsed` has no
    finite value anywhere on the interval (plan step P12/S2's own
    "domain_error constant and null x/y" case).

    `_EXTREMUM_SCAN_INTERVALS` evenly spaced samples, including both ends
    (the planner notes' "sample densely ... and include both endpoints"),
    pick out the best (lowest/highest) finite sample. The bracket handed
    to golden-section search is the nearest finite sample on each side of
    that best one -- ordinarily its immediate scan neighbours, but a gap
    sample (e.g. a pole) on one side is skipped in favour of the next
    finite sample further out, rather than handing golden-section a bound
    it cannot evaluate at all.

    Golden-section search (_golden_section_minimize) then refines within
    that bracket, minimizing `parsed` itself for a minimum or its
    negation for a maximum, with any gap sampled during the search
    treated as +inf (i.e. never the best point) rather than aborting the
    search. If that refinement ever comes back no better than the best
    scan sample already found -- a gap at the refined point, or numerical
    noise -- the scan sample is kept instead; refinement can only improve
    on the scan, never regress it.

    The refined (x, y) pair is finally snapped to an exact value with
    _snap_extremum before being returned.
    """
    step = (upper - lower) / _EXTREMUM_SCAN_INTERVALS
    xs = [lower + index * step for index in range(_EXTREMUM_SCAN_INTERVALS + 1)]
    xs[-1] = upper
    ys = [_evaluate_at(parsed, value) for value in xs]

    best_index = None
    for index, y_value in enumerate(ys):
        if y_value is None:
            continue
        if best_index is None:
            best_index = index
        elif (y_value < ys[best_index]) if is_minimum else (y_value > ys[best_index]):
            best_index = index

    if best_index is None:
        return None

    left = xs[best_index]
    for index in range(best_index - 1, -1, -1):
        if ys[index] is not None:
            left = xs[index]
            break
    right = xs[best_index]
    for index in range(best_index + 1, len(xs)):
        if ys[index] is not None:
            right = xs[index]
            break

    sign = 1.0 if is_minimum else -1.0

    def signed(x_value):
        y_value = _evaluate_at(parsed, x_value)
        return math.inf if y_value is None else sign * y_value

    refined_x, refined_y = xs[best_index], ys[best_index]
    if left != right:
        candidate_x = _golden_section_minimize(signed, left, right)
        candidate_y = _evaluate_at(parsed, candidate_x)
        if candidate_y is not None:
            better = (candidate_y < refined_y) if is_minimum else (candidate_y > refined_y)
            if better:
                refined_x, refined_y = candidate_x, candidate_y

    return _snap_extremum(parsed, refined_x, refined_y, is_minimum)


def analyze(body):
    """Build the POST /api/graph/analyze response dict for `body` (plan
    steps P12/S1 and P12/S2).

    `body` is {"operation": "value"|"zero"|"minimum"|"maximum"|
    "intersection", "f": expr, "g": expr (intersection only), "x" (value
    only), "lower", "upper" (every other operation)}. Returns
    {"operation", "x", "y", "domain_error"}, with "x"/"y" each a
    numfmt.format_decimal string (12 significant digits) or None, and
    "domain_error" a message or None.

    Validates, in order, before anything is parsed:
    - "operation" must be one of ANALYZE_OPERATIONS, else GraphError
      ("bad operation ... 400", planner notes).
    - "f" is always required, as a string (_require_expr) -- "missing
      parameter ... 400".
    - "g" is required (also via _require_expr) only when "operation" is
      "intersection".
    - "x" is required, as a finite non-bool number (_finite_number), only
      for "value".
    - "lower" and "upper" are required, each a finite non-bool number, for
      every other operation, with lower < upper (same rule, and same
      GraphError wording, as window()'s own xmin < xmax) -- "lower >=
      upper ... 400".

    "f" (and "g", for "intersection") is then parsed with _parse_function,
    the same evaluator-backed parse plot() uses -- so graphcalc.calc.
    CalcError (bad syntax, an unknown function call, or an expression the
    freeze guard flags) can also escape analyze() unchanged, exactly as it
    can escape plot(); graphcalc.cli must treat both exception types as a
    400 here too.

    "value" substitutes "x" into "f" with _evaluate_at; a gap (division by
    zero, a non-real result, and so on) answers 200 with "y" None and
    "domain_error" DOMAIN_ERROR_NO_VALUE, "x" still the formatted input --
    "a gap returns domain_error instead of y" (planner notes): only "y" is
    replaced.

    "zero" scans [lower, upper] for a root with _scan_for_root, refines it
    by bisection, and snaps it to an exact value with _snap_root when one
    is found. No root in the interval is not a GraphError -- it answers
    200 with "x" and "y" both None and "domain_error" DOMAIN_ERROR_NO_ZERO
    ("No zero or intersection: 200 with domain_error", planner notes). A
    root's own "y" is always "0" (numfmt.format_decimal(0)): by
    construction a root's y-value is zero, so there is no reason to format
    whatever float residual bisection's own last sample happened to leave,
    which can carry meaningless floating-point noise.

    "minimum" and "maximum" (plan step P12/S2) find the best (lowest/
    highest) value of "f" on [lower, upper] with _find_extremum: a dense
    scan refined by golden-section search, snapped to an exact value the
    same way "zero" does. No finite value anywhere on the interval (e.g.
    "f" a constant gap such as "1/0", or exactly as undefined as that at
    every sampled point) is not a GraphError either -- it answers 200
    with "x" and "y" both None and "domain_error"
    DOMAIN_ERROR_NO_EXTREMUM_TEMPLATE filled in with the operation's own
    name ("no minimum in interval" / "no maximum in interval"), the same
    200-with-domain_error shape as "zero"'s own no-root case.

    "intersection" (plan step P12/S3) parses "g" the same way "f" is
    parsed, then runs the exact same _scan_for_root/_snap_root pair
    "zero" uses above, but on h = f - g instead of on f directly -- an
    intersection of f and g is exactly a zero of their difference. No
    root in the interval is, the same as "zero"'s own no-root case, a 200
    with "x" and "y" both None and "domain_error" set, here to
    DOMAIN_ERROR_NO_INTERSECTION ("no intersection in interval") rather
    than DOMAIN_ERROR_NO_ZERO, since this is "intersection"'s own request,
    not "zero"'s. Unlike "zero" (whose root's own y is always exactly 0,
    by construction), "y" here is f's (or, failing that, g's) actual
    value at the found x, recovered with _evaluate_exact_at so that an
    exact snapped x (e.g. the Integer 1) yields an exact y too, not one
    narrowed to double precision first.
    """
    if not isinstance(body, dict):
        raise GraphError("invalid request body")

    operation = body.get("operation")
    if operation not in ANALYZE_OPERATIONS:
        raise GraphError(f"unknown operation: {operation!r}")

    f_text = _require_expr(body, "f")
    g_text = _require_expr(body, "g") if operation == "intersection" else None

    if operation == "value":
        x_value = _finite_number(body, "x", "x")
    else:
        lower = _finite_number(body, "lower", "lower")
        upper = _finite_number(body, "upper", "upper")
        if lower >= upper:
            raise GraphError("lower must be less than upper")

    if operation == "value":
        parsed_f = _parse_function(f_text)
        y_value = _evaluate_at(parsed_f, x_value)
        if y_value is None:
            return {
                "operation": operation,
                "x": format_decimal(x_value, sig=12),
                "y": None,
                "domain_error": DOMAIN_ERROR_NO_VALUE,
            }
        return {
            "operation": operation,
            "x": format_decimal(x_value, sig=12),
            "y": format_decimal(y_value, sig=12),
            "domain_error": None,
        }

    if operation == "zero":
        parsed_f = _parse_function(f_text)
        root = _scan_for_root(parsed_f, lower, upper)
        if root is None:
            return {
                "operation": operation,
                "x": None,
                "y": None,
                "domain_error": DOMAIN_ERROR_NO_ZERO,
            }
        snapped = _snap_root(parsed_f, root)
        x_display = snapped if snapped is not None else root
        return {
            "operation": operation,
            "x": format_decimal(x_display, sig=12),
            "y": format_decimal(0, sig=12),
            "domain_error": None,
        }

    if operation in ("minimum", "maximum"):
        parsed_f = _parse_function(f_text)
        extremum = _find_extremum(parsed_f, lower, upper, operation == "minimum")
        if extremum is None:
            return {
                "operation": operation,
                "x": None,
                "y": None,
                "domain_error": DOMAIN_ERROR_NO_EXTREMUM_TEMPLATE.format(operation=operation),
            }
        x_display, y_display = extremum
        return {
            "operation": operation,
            "x": format_decimal(x_display, sig=12),
            "y": format_decimal(y_display, sig=12),
            "domain_error": None,
        }

    # operation == "intersection" (plan step P12/S3): see docstring above.
    parsed_f = _parse_function(f_text)
    parsed_g = _parse_function(g_text)
    h = parsed_f - parsed_g if parsed_f is not None and parsed_g is not None else None
    root = _scan_for_root(h, lower, upper)
    if root is None:
        return {
            "operation": operation,
            "x": None,
            "y": None,
            "domain_error": DOMAIN_ERROR_NO_INTERSECTION,
        }
    snapped = _snap_root(h, root)
    x_display = snapped if snapped is not None else root
    y_display = _evaluate_exact_at(parsed_f, x_display)
    if y_display is None:
        y_display = _evaluate_exact_at(parsed_g, x_display)
    if y_display is None:
        return {
            "operation": operation,
            "x": format_decimal(x_display, sig=12),
            "y": None,
            "domain_error": DOMAIN_ERROR_NO_VALUE,
        }
    return {
        "operation": operation,
        "x": format_decimal(x_display, sig=12),
        "y": format_decimal(y_display, sig=12),
        "domain_error": None,
    }
