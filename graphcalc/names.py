"""The reserved-name check shared by every feature that defines a name.

check_not_constant(name) raises graphcalc.calc.CalcError -- the same
exception graphcalc.cli turns into a 400 -- when `name` is one of the
calculator's built-in constants or functions (pi, e, E, I, i, oo, nan, and
the trig/log/exp/sqrt/abs whitelist graphcalc.calc.evaluate already parses
expressions with). This module has no production caller yet: P5 adds it
only so P7's `name:=expr` variable/function definitions can call it ("pi:=3"
answers 400 with "cannot redefine constant pi"); there is no `:=` syntax
until then, so nothing in P5 can trigger it outside the tests below that
call check_not_constant directly.

RESERVED_NAMES is built from graphcalc.calc's own parser whitelist (never a
hand-copied duplicate of it) plus the handful of spellings (lowercase "i",
"oo", "nan") a CAS user would also expect to be reserved, so the two stay in
sync if the whitelist ever grows.
"""

from graphcalc.calc import CalcError, _rad_names

RESERVED_NAMES = frozenset(_rad_names()) | {"i", "oo", "nan"}


def check_not_constant(name: str) -> None:
    """Raise CalcError if `name` is a reserved constant or function name.

    Does nothing (returns None) for any other name, including a plain
    free variable like "x".
    """
    if name in RESERVED_NAMES:
        raise CalcError(f"cannot redefine constant {name}")
