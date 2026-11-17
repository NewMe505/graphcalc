"""Named list name/value validation for /api/lists (plan step P15/S1).

LIST_NAME_RE and validate_list_name() give graphcalc/cli.py's /api/lists
route handlers a single, shared definition of what a list name is --
[A-Za-z][A-Za-z0-9_]{0,15}, checked with fullmatch so an extra trailing
character (e.g. a 17-character name) or a disallowed character anywhere in
the name (e.g. "L-1", "1L", "_L") is rejected the same way an empty name is.

validate_list_values() is the companion check for a PUT request's "values"
field: it must be a JSON array of strings, neither empty nor longer than
MAX_LIST_VALUES, and every string in it must be a calculator expression
graphcalc.calc.evaluate can parse -- the same grammar this calculator's
whole /api/calc/evaluate route already enforces (plan steps P23/S1, P27/S1,
P27/S2), so a value such as "abc+" is rejected here exactly the same way it
would be rejected as a bare expression.

Both helpers raise graphcalc.calc.CalcError -- never a bespoke exception --
so graphcalc/cli.py's /api/lists handlers can catch exactly the one
exception type every other route already turns into a 400, never a 500.

Values are stored (graphcalc.state.CalcState.set_list) as the original
strings, unevaluated -- validate_list_values only ever *checks* that each
one parses; it never substitutes the evaluated result in its place (plan
step P26's "stored data never breaks later evaluations" rule: a stored list
is just as inert on disk as a stored variable's "exact" string is, and is
only ever actually evaluated -- element by element, in whatever mode an
expression referencing the list is evaluated in -- by a later feature).
"""

import re

from graphcalc.calc import CalcError, evaluate

# [A-Za-z][A-Za-z0-9_]{0,15}: a letter, then up to 15 more letters/digits/
# underscores -- at most 16 characters total. Checked with fullmatch (see
# validate_list_name below), so a name with an extra trailing character is
# rejected outright rather than silently matched up to its first 16
# characters and left there.
LIST_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,15}")

# "reject empty or oversized input" (plan step P15/S1's planner notes): at
# least one value, so a stored list always has something in it, and at most
# this many, generously more than any Lists & Statistics screen needs, so a
# client cannot force this single-threaded server into storing (and later
# re-evaluating, element by element) an unbounded list -- the same
# reasoning as graphcalc.graph's own MAX_SAMPLES/MAX_ROWS.
MAX_LIST_VALUES = 1000


def validate_list_name(name) -> None:
    """Raise CalcError unless `name` is a string fully matching LIST_NAME_RE.

    fullmatch (not match) is what rejects a name that is one character too
    long -- "[A-Za-z][A-Za-z0-9_]{0,15}" alone would otherwise just stop
    matching at 16 characters and leave the rest of e.g. a 17-character name
    unconsidered, rather than rejecting the name outright. A non-string
    `name` (should never happen for a path-segment-derived name, but this is
    also called directly by tests and could be reused elsewhere) is
    rejected the same way, never passed to fullmatch at all.
    """
    if not isinstance(name, str) or LIST_NAME_RE.fullmatch(name) is None:
        raise CalcError(f"invalid list name: {name!r}")


def validate_list_values(values) -> None:
    """Raise CalcError unless `values` is a well-formed PUT /api/lists/<name>
    "values" field.

    `values` must be a JSON array (a non-list -- missing entirely, i.e.
    payload.get("values") is None, or the wrong JSON type such as a string
    or object -- is rejected first, with the same CalcError type a bad
    per-entry expression raises below, so graphcalc/cli.py's PUT handler
    never needs to tell the two cases apart itself), non-empty, and no
    longer than MAX_LIST_VALUES.

    Every entry must then be a string -- a non-string entry (e.g. a bare
    JSON number) is rejected before it ever reaches evaluate(), which would
    otherwise raise its own, differently-worded CalcError("missing
    parameter: expr") for the same input, since evaluate() treats a
    non-string `expr` as "missing" (plan step P15/S1: "a non-string gives
    400" either way, just with a clearer message here) -- and must parse as
    a calculator expression: graphcalc.calc.evaluate(value) is called and
    its result discarded, the exact same parse, grammar gate (P23/S1,
    P27/S1, P27/S2) and freeze guard (P28/S1) a plain /api/calc/evaluate
    request already goes through, so "abc+" raises the same
    CalcError("invalid expression: abc+") here that it would from that
    route. Only the entry's *syntax* is checked -- a value that parses but
    has no defined value (e.g. "1/0", a domain_error rather than a
    CalcError) is not rejected here, since evaluate() itself does not raise
    for that; the stored value stays the original string regardless (see
    this module's own docstring), not whatever evaluate() computed.
    """
    if not isinstance(values, list):
        raise CalcError("missing parameter: values")
    if not values:
        raise CalcError("values must not be empty")
    if len(values) > MAX_LIST_VALUES:
        raise CalcError(f"values must have at most {MAX_LIST_VALUES} entries")
    for value in values:
        if not isinstance(value, str):
            raise CalcError(f"each list value must be a string: {value!r}")
        evaluate(value)
