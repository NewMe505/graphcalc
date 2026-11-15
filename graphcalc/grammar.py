"""Pre-parse grammar gate for graphcalc.calc.evaluate (plan step P23/S1).

Bug #5: sympy's parse_expr uses Python's own tokenizer under the hood, so it
silently accepts a lot more than this calculator's grammar -- Python
comparison operators (<, >, <=, >=, ==, !=), %, //, the bitwise/shift
operators (&, |, ~, <<, >>), Python-only numeric literals (0x10, 0b11, 0o7,
1_000, 2j, 3J), and an extra argument to one of the calculator's built-in
unary functions (ln(e,2), sqrt(4,2) -- sympy's own two-argument log(x, base)
happily accepts that even though this calculator's "ln"/"log" are always
one-argument). check_grammar(expr) runs a small regex tokenizer over `expr`
and rejects all of that *before* parse_expr ever sees the string, so
graphcalc.calc.evaluate turns the rejection into the usual CalcError -> 400,
never a 500 and never a silently-accepted Python expression outside the
calculator's own grammar.

What stays allowed: digits/decimal-point/e-exponent numbers, identifiers,
the operators + - * / ^ ** ( ) , ! := = (a bare "=" is allowed at the token
level -- "1==2" is rejected right here, at the tokenizer, because "==" is
its own two-character token; "1 = = 2" passes this tokenizer unchanged,
since each bare "=" is individually allowed, and is instead rejected two
steps later, inside graphcalc.calc.evaluate: parse_expr parses it into a
plain Python bool, not a sympy object, and the very next line's
`_UNDEFINED_ANS in parsed.free_symbols` check raises AttributeError on it
-- the same pre-existing fallback that already rejected "1==2"/"1 != 2"
before this fix, via evaluate's broad `except Exception` -> CalcError),
postfix "!" (5! -> 120 via sympy's factorial_notation), a top-level
"name:=expr" definition, and implied multiplication (2x, 2(x+1)).

The tokenizer is a single ordered regex (most specific alternative first):
every multi-character operator that shares a prefix with a shorter,
differently-classified one (":=" vs ":", "!=" vs "!", "==" vs "=", "//" vs
"/", "0x../0b../0o.." vs a plain number) is tried before the shorter one, so
e.g. "!=" is read as one rejected token, never as an allowed "!" followed by
an allowed "=". Any character the regex does not recognize at all (e.g.
"{", "}", "[", "]", "@") is rejected the same way.

This module also exports called_names(expr) (plan step P24/S3, Bug #7
fix), built on the same tokenizer: it returns every identifier in `expr`
immediately followed by "(", so graphcalc.calc.evaluate can reject a call
on a name its own whitelist/local_dict doesn't know -- an uppercase
variant of a built-in such as "SIN", or a real sympy name this calculator
never whitelisted, "zeta(2)" -- with "unknown function '<name>'" (-> 400)
before parse_expr ever sees it, rather than letting parse_expr's
auto_symbol fallback silently turn the call into an implicit product.

_tokenize() also rejects any non-ASCII character this grammar treats as a
letter, digit, or numeric symbol (plan step P27/S2, Bug #21 fix) -- see
_check_ascii_only's own docstring just below for why that check has to
run ahead of the tokenizer regex itself, not as one more alternative
inside it.
"""

import re
import unicodedata


class GrammarError(Exception):
    """Raised by check_grammar for a token or call outside the calculator's grammar.

    graphcalc.calc.evaluate imports this and turns it into the usual
    CalcError -> 400. This module never imports graphcalc.calc at load time
    -- calc.py imports *this* module, so that would be circular -- the
    unary-function whitelist below is instead fetched with a lazy import
    inside _unary_function_names(), done each time check_grammar runs.
    """


# Numbers: one or more digits, then an optional ".", with one or more
# digits required after it, then an optional e-exponent -- stricter than
# Python's own float grammar in both directions that matter here: a bare
# leading dot (".5") or a bare trailing dot ("5.") is NOT in this pattern
# (neither \d+ is optional), even though both are valid Python/sympy floats,
# so ".5" and "5." are rejected by this gate too (known gap, not an
# acceptance criterion P23 lists -- see NOTES.md). Checked against the
# permissive NUMBER group's matched text below, so a Python-only suffix
# (the "_" of "1_000", or the "j"/"J" of "2j"/"3J") is told apart from a
# genuinely allowed number instead of silently splitting into an allowed
# number token plus an allowed identifier token (e.g. "1_000" as NUMBER "1"
# + IDENT "_000").
_STRICT_NUMBER_RE = re.compile(r"^\d+(\.\d+)?([eE][+-]?\d+)?$")

# Tried in this order -- longest/most specific alternative first -- so a
# multi-character token is never misread as two shorter ones:
#   HEX/BIN/OCT  before NUMBER, so "0x10"/"0b11"/"0o7" are never read as the
#                allowed number "0" followed by an allowed identifier
#   ":="         before the stray ":" that "{1:2}" contains
#   "!="         before the postfix "!" that "5!" uses
#   "=="         before the bare "=" this grammar otherwise allows
#   "//"         before the "/" this grammar otherwise allows
#
# The trailing "[jJ]" of NUMBER carries a negative lookahead, "(?!\w)", so it
# is only consumed when no identifier character follows: "2j"/"3J" alone
# still match NUMBER with the "j"/"J" included (and are then rejected below
# by _STRICT_NUMBER_RE, which has no "j"/"J" in its grammar), but implied
# multiplication by a name that happens to start with "j"/"J" -- "2job",
# "3Jane" -- instead stops NUMBER at "2"/"3" and leaves "job"/"Jane" to match
# IDENT, exactly like "2x" or "2y" does.
_TOKEN_RE = re.compile(
    r"""
    (?P<HEX>0[xX][0-9a-fA-F]+)
  | (?P<BIN>0[bB][01]+)
  | (?P<OCT>0[oO][0-7]+)
  | (?P<NUMBER>\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?(?:[jJ](?!\w))?)
  | (?P<IDENT>[A-Za-z_]\w*)
  | (?P<ASSIGN>:=)
  | (?P<LE><=)
  | (?P<GE>>=)
  | (?P<EQ>==)
  | (?P<NE>!=)
  | (?P<SHL><<)
  | (?P<SHR>>>)
  | (?P<FLOORDIV>//)
  | (?P<POW>\*\*)
  | (?P<OP>[+\-*/^(),!<>=%&|~:{}\[\]])
    """,
    re.VERBOSE,
)

# Single characters the OP group can match that this grammar actually
# allows; everything else the OP group matches (<, >, %, &, |, ~, a stray
# :, {, }, [, ]) is a rejected token. "=" itself is allowed on purpose (see
# the module docstring): a bare "=" is let through so parse_expr's own
# failure to parse "1 = = 2" is what rejects it, not this tokenizer.
_ALLOWED_OP_CHARS = frozenset("+-*/^(),!=")

# Token groups that are always rejected outright regardless of the matched
# text -- every Python comparison/bitwise-shift/floor-division operator and
# Python-only numeric-literal prefix this calculator's grammar has no use
# for.
_REJECTED_GROUPS = frozenset(
    {"HEX", "BIN", "OCT", "LE", "GE", "EQ", "NE", "SHL", "SHR", "FLOORDIV"}
)


def _unary_function_names():
    """The calculator's built-in one-argument function names.

    graphcalc.calc._rad_names() is the parser's own whitelist of constants
    and functions; pi/e/E/I are constants, not callables, so they are
    excluded here. The rest -- sqrt, sin, cos, tan, asin, acos, atan, ln,
    log, exp, abs -- each take exactly one argument in this calculator,
    even though sympy's own two-argument log(x, base) would otherwise let
    an extra argument ("ln(e,2)", "sqrt(4,2)") silently through.

    Imported lazily, not at module load time, because graphcalc.calc
    imports this module -- a module-level import here would be circular.
    """
    from graphcalc.calc import _rad_names

    return frozenset(_rad_names()) - {"pi", "e", "E", "I"}


def _check_ascii_only(expr: str) -> None:
    """Raise GrammarError for any non-ASCII letter, digit, or numeric symbol
    in `expr` (plan step P27/S2, Bug #21 fix).

    _TOKEN_RE's IDENT group is "[A-Za-z_]\\w*" and its NUMBER group starts
    with "\\d" -- but Python's own "\\w"/"\\d" are Unicode-aware by default,
    not the ASCII-only [A-Za-z0-9_] this grammar's docstring implies: a
    fullwidth digit ("２"), an Arabic-indic digit ("٣"), a non-Latin or
    accented letter, and a superscript/subscript numeral ("x²", "₂") are
    all str.isalnum() (so "\\w" matches them) and "２"/"٣" are both
    str.isdigit() (so "\\d" matches them) too. Left unchecked, the regex
    silently reads "２+２" as two NUMBER tokens, "x²" as one IDENT token
    "x²", and so on -- never the tokenizer's own "disallowed character"
    rejection, because the regex *did* match, just not on the grammar this
    calculator actually defines.

    Run once, ahead of the per-character tokenizer loop below, rather than
    folded into _TOKEN_RE as one more alternative: a non-ASCII character
    that *is* part of a larger regex match (the "²" inside "x²"'s one IDENT
    token) would never be inspected on its own by that loop at all, since
    the loop only advances by whole matches, never character by character
    within one.

    isdigit()/isalpha()/isnumeric() alone already cover every case above
    (confirmed: "²".isdigit() and "₂".isnumeric() are both True), but the
    category check is kept too, exactly as the plan step asks (Nd/No for a
    digit/numeral, any "L*" for a letter) as a second, independent net --
    belt-and-suspenders against a Unicode character whose isdigit/isalpha/
    isnumeric answers do not happen to match its own category. A symbol
    with no letter/digit/numeral meaning at all (e.g. "√", category "Sm")
    is not raised here -- this grammar has no pass-through mapping for it
    either, so it still reaches the ordinary "disallowed character"
    rejection below, via _TOKEN_RE simply failing to match it.
    """
    for ch in expr:
        if ord(ch) < 128:
            continue
        category = unicodedata.category(ch)
        if (
            ch.isdigit()
            or ch.isalpha()
            or ch.isnumeric()
            or category in ("Nd", "No")
            or category.startswith("L")
        ):
            raise GrammarError(f"disallowed character in expression: {ch!r}")


def _tokenize(expr):
    """Yield (group_name, matched_text) for every token in `expr`.

    Raises GrammarError for any character the tokenizer regex cannot match
    at all -- e.g. "{", "}", "[", "]", "@", or any other symbol outside the
    calculator's grammar -- and, before any of that (see
    _check_ascii_only), for any non-ASCII letter, digit, or numeral, even
    one that is only part of a larger token the regex would otherwise
    match whole (e.g. the "²" inside "x²").
    """
    _check_ascii_only(expr)
    pos = 0
    length = len(expr)
    while pos < length:
        if expr[pos].isspace():
            pos += 1
            continue
        match = _TOKEN_RE.match(expr, pos)
        if match is None:
            raise GrammarError(f"disallowed character in expression: {expr[pos]!r}")
        yield match.lastgroup, match.group()
        pos = match.end()


def _has_top_level_comma(tokens, open_paren_index):
    """True if the "(" at `open_paren_index` has a top-level "," before its
    matching ")" -- i.e. the call it opens is given more than one argument.

    Nested parentheses are tracked by depth, so "sqrt(sin(1,2))" (an inner
    call's own extra argument) does not make this function return True for
    the outer "sqrt(" -- check_grammar's own per-token loop catches the
    inner "sin(1,2)" separately -- and "sqrt((1+2)*3)" (no comma at all) is
    correctly left alone.
    """
    depth = 1
    for group, text in tokens[open_paren_index + 1 :]:
        if group == "OP" and text == "(":
            depth += 1
        elif group == "OP" and text == ")":
            depth -= 1
            if depth == 0:
                return False
        elif group == "OP" and text == "," and depth == 1:
            return True
    return False


def called_names(expr: str) -> set:
    """Return every identifier immediately followed by "(" in `expr`.

    Shares check_grammar's own tokenizer (plan step P24/S3, Bug #7 fix):
    this is how graphcalc.calc.evaluate tells a genuine call -- "sin(x)" on
    one of this calculator's own built-ins, or "f(3)" on a user-stored
    function -- from a call-looking expression on a name the evaluator does
    not otherwise know, such as the uppercase "SIN(pi/2)" or a real sympy
    name this calculator never whitelisted, "zeta(2)".

    evaluate() calls this *after* building its final local_dict (the
    rad/deg whitelist, stored variables and functions, a function
    definition's own params, "ans"), then rejects any name this returns
    that is in neither local_dict nor its own global_dict with "unknown
    function '<name>'" -- a 400, raised before parse_expr ever runs.
    Without that check, sympy's own parser -- lacking any whitelist entry
    to call -- falls back to auto_symbol's generic "undefined name follow
    by (" handling: it wraps the name in a call to the *Function*
    constructor (never left bound, because the very next step,
    implicit_multiplication's own close-paren-before-open-paren rule, downgrades
    that right back to a plain Symbol and inserts a "*"), so "SIN(pi/2)"
    would otherwise silently become the implicit product "pi*SIN/2" instead
    of the 400 a call on an unknown name should be. This function only
    reports the name was *called*; it has no opinion on whether that name
    turns out to be known -- the caller decides that by checking its own
    local_dict and global_dict.
    """
    tokens = list(_tokenize(expr))
    names = set()
    for index, (group, text) in enumerate(tokens):
        if (
            group == "IDENT"
            and index + 1 < len(tokens)
            and tokens[index + 1] == ("OP", "(")
        ):
            names.add(text)
    return names


def check_grammar(expr: str) -> None:
    """Raise GrammarError if `expr` uses anything outside the calculator's grammar.

    Runs before graphcalc.calc.evaluate's sympy parse: rejects Python
    comparison/bitwise/shift/floor-division operators, Python-only numeric
    literals (hex/bin/oct, underscore digit grouping, a j/J imaginary
    suffix), and an extra argument to one of the calculator's built-in
    unary functions (ln(e,2), sqrt(4,2)). Does nothing (returns None) for
    grammar the calculator does accept, including postfix "!", a top-level
    "name:=expr" definition, and implied multiplication.
    """
    tokens = list(_tokenize(expr))
    unary_functions = _unary_function_names()

    for index, (group, text) in enumerate(tokens):
        if group in _REJECTED_GROUPS:
            raise GrammarError(f"disallowed operator: {text!r}")
        if group == "NUMBER" and not _STRICT_NUMBER_RE.match(text):
            raise GrammarError(f"disallowed number literal: {text!r}")
        if group == "OP" and text not in _ALLOWED_OP_CHARS:
            raise GrammarError(f"disallowed token: {text!r}")
        if (
            group == "IDENT"
            and text in unary_functions
            and index + 1 < len(tokens)
            and tokens[index + 1] == ("OP", "(")
            and _has_top_level_comma(tokens, index + 1)
        ):
            raise GrammarError(f"too many arguments to {text}")
