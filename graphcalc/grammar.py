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


# Numbers, as on a TI (owner revision, 2026-11-14/2026-11-15, plan step
# P29/S2): a run of digits with an optional decimal point somewhere in it,
# then an optional e-exponent. Either side of the point may be empty, but
# not both -- ".5" and "5." are both accepted (one bare dot alone, "."
# itself, has digits on neither side and is still rejected), and so is a
# leading-zero run of digits such as "0005", since \d+ places no limit on
# what those digits are. What stays rejected is exactly the shape the
# owner's 2026-11-15 revision calls out: a *second* "." anywhere in the
# literal ("1.2.3", "1..2", the trailing ".2" of "1.5e3.2") never matches
# either alternative below, because each one allows only one "." total.
# Checked against the permissive NUMBER group's matched text below, so a
# Python-only suffix (the "_" of "1_000", or the "j"/"J" of "2j"/"3J") is
# told apart from a genuinely allowed number instead of silently splitting
# into an allowed number token plus an allowed identifier token (e.g.
# "1_000" as NUMBER "1" + IDENT "_000"). normalize_numbers() (below) then
# rewrites whatever this regex accepts into text Python's own tokenizer can
# actually compile -- see its own docstring for why that extra step exists.
_STRICT_NUMBER_RE = re.compile(r"^(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")

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
#
# NUMBER itself reads as the longest run of digits and dots (owner revision,
# 2026-11-15, plan step P29/S1): it may start with either a digit or a bare
# "." (so a later, still-unwidened _STRICT_NUMBER_RE below is the thing that
# tells ".5"/"5." apart from "1.2.3"/"1..2"/"."), then greedily consumes a
# run of "[\d._]" -- digits, dots and underscores together, not just
# digits -- so a second "." right after the first is swallowed into the
# same token instead of starting a second NUMBER match. Without this, "1.2"
# would stop there and leave a bare ".3" for the regex to retry from
# scratch; since a bare "." is not (yet) its own token, the *old* pattern
# happened to reject that specific case too, but only by accident, via the
# tokenizer's generic "disallowed character" fallback on the stray ".": once
# a leading "." becomes legal (so NUMBER can match ".3" on its own), that
# accident stops working and "1.2.3" would instead silently tokenize as two
# NUMBERs side by side -- read as the implied product "1.2 * .3" -- which is
# exactly the regression this longest-run rule exists to prevent. The
# optional exponent is widened to match: "[eE][+-]?" followed by its own run
# of "[\d._]" (at least one character, same as the plain digit run the old
# pattern required there), so the trailing ".2" of "1.5e3.2" is absorbed
# into the very same token rather than left over as a second one. Requiring
# at least one character after "e"/"E" is what keeps implied multiplication
# by a name starting with "e" working ("2ex" still stops NUMBER at "2" and
# leaves "ex" to match IDENT, exactly like "2pi" stops at "2" and leaves
# "pi"), and is also why "2pi" is unaffected: "p" matches neither "[\d._]"
# nor the "e"/"E" lookahead that starts the exponent, so NUMBER still stops
# at "2" either way. Last comes the existing optional j/J suffix, unchanged.
_TOKEN_RE = re.compile(
    r"""
    (?P<HEX>0[xX][0-9a-fA-F]+)
  | (?P<BIN>0[bB][01]+)
  | (?P<OCT>0[oO][0-7]+)
  | (?P<NUMBER>[\d.][\d._]*(?:[eE][+-]?[\d._]+)?(?:[jJ](?!\w))?)
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
    that is not in local_dict with "unknown function '<name>'" -- a 400,
    raised before parse_expr ever runs. (Plan step P27/S1, Bug #21 fix:
    evaluate() used to also accept a name that was a key of its own
    global_dict -- the internal sympy constructors parse_expr's
    transformations emit from a generated AST node, never from literal
    user text -- which let "Integer(2)", "Float(2)", "Rational(1,2)" and
    "factorial(5)" all evaluate instead of being rejected; evaluate() now
    checks local_dict alone, so this function's own return value does not
    need to change, only what the caller does with it.) Without the
    local_dict check, sympy's own parser -- lacking any whitelist entry to
    call -- falls back to auto_symbol's generic "undefined name follow by
    (" handling: it wraps the name in a call to the *Function* constructor
    (never left bound, because the very next step, implicit_
    multiplication's own close-paren-before-open-paren rule, downgrades
    that right back to a plain Symbol and inserts a "*"), so "SIN(pi/2)"
    would otherwise silently become the implicit product "pi*SIN/2" instead
    of the 400 a call on an unknown name should be. This function only
    reports the name was *called*; it has no opinion on whether that name
    turns out to be known -- the caller decides that by checking its own
    local_dict.
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
    suffix), an extra argument to one of the calculator's built-in unary
    functions (ln(e,2), sqrt(4,2)), and any non-ASCII letter, digit, or
    numeral such as a fullwidth digit, an Arabic-indic digit, or a
    superscript/subscript numeral (e.g. "２+２", "x²" -- plan step P27/S2,
    Bug #21 fix; see _check_ascii_only, called from _tokenize). Does
    nothing (returns None) for grammar the calculator does accept,
    including postfix "!", a top-level "name:=expr" definition, and
    implied multiplication.
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


# Splits a NUMBER token _STRICT_NUMBER_RE has already accepted into its four
# pieces -- the digits before the point, the point itself, the digits after
# it, and the e-exponent -- each optional on its own (never all absent at
# once; that is exactly what _STRICT_NUMBER_RE itself refuses to match), so
# _normalize_number_literal can rebuild the pieces Python's tokenizer needs
# without re-deriving the same digit-and-dot structure a second time.
_NUMBER_PARTS_RE = re.compile(r"^(?P<int>\d*)(?P<dot>\.)?(?P<frac>\d*)(?P<exp>[eE][+-]?\d+)?$")


def _normalize_number_literal(text: str) -> str:
    """Rewrite one grammar-approved NUMBER token into Python-safe text.

    Python's own tokenizer accepts a bare leading dot (".5") and a bare
    trailing dot ("5.") exactly as sympy's parse_expr does -- neither needs
    rewriting to parse -- but it raises a SyntaxError on a leading-zero
    integer literal ("0005": "leading zeros in decimal integer literals are
    not permitted"), confirmed directly against this Python's own
    parse_expr, not assumed. This function's real job is dodging that one
    case; the ".5"/"5." rewrites below are done anyway, for every literal
    shape _STRICT_NUMBER_RE accepts, so normalize_numbers' output is always
    an ordinary digits-point-digits literal, never one with an empty side,
    regardless of which accepted shape the user actually typed.

    `text` is assumed to already satisfy _STRICT_NUMBER_RE (check_grammar's
    own job, run first); a `text` that does not match _NUMBER_PARTS_RE's
    looser digit/dot/exponent shape at all -- e.g. one of the owner's
    2026-11-15 malformed examples, "1.2.3" -- is returned unchanged rather
    than mangled, since check_grammar would have already rejected it before
    normalize_numbers ever runs on real input.
    """
    match = _NUMBER_PARTS_RE.match(text)
    if match is None:
        return text
    integer_part = match.group("int") or ""
    dot = match.group("dot") or ""
    frac_part = match.group("frac") or ""
    exp_part = match.group("exp") or ""

    if integer_part:
        # "0005" -> "5"; "0" and "00" both collapse to the single digit "0",
        # never to "" -- an empty integer part would only be correct when a
        # "." follows (the ".5" case, handled by the next branch instead).
        integer_part = integer_part.lstrip("0") or "0"
    elif dot:
        # A leading "." with nothing before it (".5") gets an explicit "0"
        # in front, exactly as the plan step asks.
        integer_part = "0"

    if dot and not frac_part:
        # A bare trailing "." with nothing after it ("5.", or the "5." of
        # "5.e3") gets an explicit "0" after it, so the dot is never left
        # dangling between two non-digits.
        frac_part = "0"

    return integer_part + dot + frac_part + exp_part


def normalize_numbers(expr: str) -> str:
    """Rewrite every NUMBER token in `expr` into Python-safe text (plan
    step P29/S2).

    graphcalc.calc.evaluate calls this on the string check_grammar has
    already approved, before handing it to sympy's parse_expr: check_grammar
    only ever confirms a NUMBER token's *shape* is one this grammar accepts
    (_STRICT_NUMBER_RE), never rewrites the token itself, and some shapes it
    accepts -- a leading-zero digit run such as "0005" -- raise a plain
    Python SyntaxError once parse_expr's own tokenizer sees them, rather
    than the clean 400 a malformed expression gets. Rewriting ahead of that
    call turns "0005" into "5", so parse_expr sees exactly the same literal
    a user who had typed "5" in the first place would have produced, and
    does the same normalization to ".5" -> "0.5" and "5." -> "5.0" even
    though Python's tokenizer already accepts those two shapes unchanged
    (confirmed directly), simply so every NUMBER token this function
    produces has the same digits-point-digits shape, never an empty side.

    Reuses _TOKEN_RE directly (not _tokenize, which raises on a character
    outside the grammar -- never expected here, since this only ever runs on
    a string check_grammar has already accepted) via finditer, so every
    character between two matched tokens -- always whitespace, for the same
    reason -- is copied through untouched rather than collapsed; only a
    NUMBER-group match's own text is ever rewritten, via
    _normalize_number_literal.
    """
    pieces = []
    last_end = 0
    for match in _TOKEN_RE.finditer(expr):
        pieces.append(expr[last_end : match.start()])
        text = match.group()
        if match.lastgroup == "NUMBER":
            text = _normalize_number_literal(text)
        pieces.append(text)
        last_end = match.end()
    pieces.append(expr[last_end:])
    return "".join(pieces)
