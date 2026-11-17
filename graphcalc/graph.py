"""Graphing core for POST /api/graph/plot and POST /api/graph/window
(plan steps P10/S1 and P11/S1).

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
"""

import math

from sympy import Float, Symbol, nan, oo, sympify, zoo

from graphcalc.calc import evaluate

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
