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
sync if the whitelist ever grows. "ans" is added on top of that (plan step
P30, owner revision 2026-11-14): it is not one of calc._rad_names()'s
constants/functions, but graphcalc.calc.evaluate and graphcalc.state.
CalcState both give it its own dedicated, non-variable storage slot (the
last plain evaluation's result -- see CalcState.set_ans/ans/clear_ans), so
"ans:=5" must never be accepted as an ordinary "name:=expr" variable
definition: that would silently create a *second*, unrelated "ans" entry in
CalcState's `variables` map (never read back, since evaluate() always
prefers the dedicated ans slot when a referenced name is "ans" -- see
calc.evaluate's own local_dict-building order) while leaving the real stored
answer untouched. Rejecting it outright here -- before any evaluation or
storage happens, via the same check_not_constant() every other reserved name
already goes through -- keeps "ans:=5" a 400 with "cannot redefine constant
ans" and leaves both the history and the real "ans" slot exactly as they
were.
"""

from graphcalc.calc import CalcError, _rad_names

RESERVED_NAMES = frozenset(_rad_names()) | {"i", "oo", "nan", "ans"}


def check_not_constant(name: str) -> None:
    """Raise CalcError if `name` is a reserved constant or function name.

    Does nothing (returns None) for any other name, including a plain
    free variable like "x".
    """
    if name in RESERVED_NAMES:
        raise CalcError(f"cannot redefine constant {name}")
