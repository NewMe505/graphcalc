# Notes

- M6 Disk-persisted state and graph plot/window API merged by `scio build`: P9 passed, P10 passed, P11 passed; $9.2876.
- M5 Number literals, decimal exacts, history and wrapping merged by `scio build`: P29 passed, P33 passed, P31 passed, P32 passed; $9.3290.
- M4 Evaluator hardening: names, Unicode, freezes, literals merged by `scio build`: P27 failed, P27 passed, P28 passed, P29 skipped (reopened by the owner's 2026-11-15 revision and fixed in M5 -- see the P29/S1 and P29/S2 notes below), P30 passed; $13.4294.
- M3 Evaluator grammar, naming and robustness fixes merged by `scio build`: P23 passed, P24 passed, P25 passed, P26 failed, P26 failed, P26 failed, P26 passed; $30.6874.
- M2 Calculator errors, history, variables and tab UI merged by `scio build`: P5 passed, P6 passed, P7 failed, P7 passed, P8 failed, P8 passed; $17.0970.
- M1 Server skeleton, static UI shell and core evaluation merged by `scio build`: P1 passed, P2 passed, P3 passed, P4 failed, P4 failed, P4 passed; $16.4903.
Working notes SCIO and humans leave for the next session. Newest first.

- P9 (2026-11-15): disk-persisted state. `graphcalc/state.py`,
  `graphcalc/history.py`, `graphcalc/cli.py`, `.gitignore`,
  `tests/test_p9_state_persistence.py`.
  - Schema: `graphcalc.state.CalcState` is now the single store for
    `"variables"` (name -> exact str, plus a parallel `"variable_sreprs"`
    map for P26/S2's srepr rebuild), `"functions"` (name ->
    `{"params": [...], "body": str}`, plus `"function_sreprs"`), `"ans"`
    (`{"exact": str, "srepr": str}` or absent), `"history"` (a plain list
    of `{"expr", "exact", "decimal"}` entries, oldest first -- the same
    shape `graphcalc.history.HistoryStore` already used), and `"lists"`
    (name -> values; empty `{}` until P15 adds CRUD for it, kept here now
    so this on-disk shape and `POST /api/state/reset` do not change again
    then). `graphcalc.history.StateBackedHistoryStore` implements the
    existing `HistoryStore` ABC on top of `CalcState.history()`/
    `append_history()`/`clear_history()`, so one JSON file backs both
    variables/functions and history.
  - `--state PATH` (default `./graphcalc_state.json`) and `--in-memory`:
    `graphcalc/cli.py`'s `main()` builds `CalcState(None if args.in_memory
    else args.state)`; a path builds a `StateBackedHistoryStore` on top of
    it, `--in-memory` builds a plain `InMemoryHistoryStore` instead, so
    nothing ever touches disk. `CalcState._save()` writes atomically
    (`tempfile.mkstemp` in the same directory, then `os.replace`) after
    every change, with no path meaning `_save()` is a no-op -- so the
    state file parses as valid JSON after every change (F2) and
    `--in-memory` creates no file at all (part of F3).
  - Bug #14 fix, load-time: `CalcState.__init__` never raises on a bad
    state file -- missing, unreadable, invalid JSON, a non-object top
    level, or any individual field of the wrong type (e.g. `"variables"`
    stored as a string) all fall back to that field's own empty default
    (`_coerce_dict`/`_coerce_list`) rather than propagating. A load
    failure never writes; the next real change overwrites the garbage
    with a valid file. Evaluation is never blocked by a corrupt file.
  - `POST /api/state/reset` -> 200 `{"status": "reset"}` (F3):
    `graphcalc/cli.py::_handle_state_reset` calls the new
    `CalcState.reset()`, which empties variables, functions,
    variable/function sreprs, lists, history and ans in one call and one
    atomic `_save()` (not a sequence of partial writes), then calls
    `history_store.clear()` too (needed for a `--in-memory` run's
    `InMemoryHistoryStore`, which `CalcState.reset()` cannot reach; a
    no-op for `StateBackedHistoryStore`, whose `clear()` just re-touches
    the `"history"` `CalcState.reset()` already emptied).
  - `.gitignore` now lists `graphcalc_state.json` (F4), proven directly by
    `test_p9_gitignore_lists_state_file` reading `.gitignore` from the
    repo root.
  - Tested in `tests/test_p9_state_persistence.py`: F2 end-to-end through
    a real server (define a variable, define a function, a plain
    evaluation, a history clear, a full reset -- the file stays valid
    JSON with the right keys after each); three bad-state-file shapes
    (unparseable text, a JSON list at the top level, a JSON object with a
    wrong-type field) each load without raising and still allow
    evaluation; F1 through two real `python -m graphcalc --state S`
    subprocesses in sequence on the same file; F3 through a real
    `POST /api/state/reset` (both the API response and the file on disk)
    and, separately, a real `--in-memory` subprocess proving reset writes
    no file either; F4 as described above.
- P32 (2026-11-14, owner revision "definitions in history"): `graphcalc/
  cli.py`, `tests/test_p32_definitions_in_history.py`. Before this fix,
  `_handle_calc_evaluate`'s `"name:=expr"`/`"f(x):=expr"` definition
  branches stored a successful result only in the HTTPServer's
  `graphcalc.state.CalcState` (via `set_variable`/`set_function`), never in
  the `graphcalc.history.HistoryStore` a plain `evaluate()` success is
  appended to -- so `GET /api/calc/history` never showed a definition at
  all, even right after one succeeded, and the planner notes flagged this
  as a gap against P6/P30 (`ans` must stay tied to the last *plain*
  result, which this fix does not change). Fix: both definition branches
  now also call `_history_store(handler).append(...)` whenever
  `result["exact"] is not None` (i.e. no `domain_error` on the right-hand
  side) -- the same condition that already gates storing into
  `CalcState` -- with `{"expr": <original "name:=expr"/"f(x):=expr"
  text>, "exact": response["exact"], "decimal": response["decimal"]}`,
  reading both fields off the `response` dict this handler is about to
  send rather than off the raw `calc.evaluate` result, so for a function
  definition the history entry's `"exact"` is the already-caret-converted
  body (`"x^2 + 1"`), matching what the client actually saw, never the
  stored `"**"` form. A rejected definition --
  `names.check_not_constant`'s 400 (`"pi:=3"`, `"ans:=5"`) or a
  `domain_error` right-hand side (`"a:=1/0"`) -- returns before either
  branch's append runs, so it adds nothing, same rule a plain `evaluate()`
  400/`domain_error` already followed. `"ans"` is untouched by this change:
  `CalcState.set_ans` is still only ever called from the plain-evaluate
  branch (P26/S1, P30), never from a definition's right-hand-side
  evaluation, so defining a variable or function never changes what
  `"ans"` recalls. Added `tests/test_p32_definitions_in_history.py`: the
  F1 acceptance case itself (`"a:=5"` then `"f(x):=x^2+1"`, asserting the
  last two history entries match each response's own `"exact"`/
  `"decimal"` in order), the F2 case (`"pi:=3"` -> 400, history stays
  empty), a multi-param function definition, that a defined variable is
  still usable (and still substituted correctly) after being recorded in
  history, and that a rejected redefinition of a reserved constant leaves
  the history empty. Full suite: 282 passed, 4 skipped. No plan drift, no
  design question: additive, two one-line `_history_store(handler).append`
  calls inside existing branches, no change to `graphcalc/history.py`'s
  interface or `graphcalc/state.py`.
- P31 (2026-11-15, owner revision "clean exact for decimals"): `graphcalc/
  calc.py`, `graphcalc/numfmt.py`, `tests/test_p31_clean_decimal_exact.py`,
  `tests/test_evaluate_grammar.py`. Before this fix, `evaluate()`'s `exact`
  field for a decimal literal was always plain `str(result)`; sympy's own
  `str()` of a `Float` pads the mantissa out to its working precision (15
  decimal digits by default), so `{"expr":"1.5"}` answered exact
  `"1.50000000000000"` instead of the clean `"1.5"` a TI-Nspire CAS user
  typed, and `{"expr":"1e5"}` answered `"100000.000000000"` instead of
  `"100000"`. Fix: new `graphcalc/numfmt.py::clean_float_exact(value)`
  strips the trailing fractional zeros (and the trailing `"."` for an
  integral value) from a `Float`'s `str()`, reusing the same mantissa/
  exponent split `format_decimal`'s scientific-notation branch already
  uses so the rare Float whose own `str()` is already in `e`-notation
  (e.g. very small magnitudes) gets the same cleanup, re-printed with
  `format_decimal`'s own exponent style (lowercase `e`, no `+`, no leading
  zeros). `calc.evaluate` now branches on `result.is_Float` before
  building `exact`: only a `Float` result goes through
  `clean_float_exact`; a `Rational` (`"1/3"`), an `Integer` (`10**1000`),
  or a symbolic result all keep plain `str(result)` exactly as before --
  confirmed directly, not just by acceptance text, since this is the same
  number handling P29 touched and the planner notes specifically asked to
  recheck P3/P4/P5/P25/P28 (all still pass; `10^1000` still answers
  decimal `"1e1000"`, P25's scientific threshold is on `Integer`, never a
  `Float`, so it was never at risk). One existing-test fix, not drift: P29's
  own `test_p29_accept_evaluate_mixed_implied_mult`/`_explicit_mult`
  (`.5x` with `x:=4`, and `2*.5`) asserted the padded `"2.00000000000000"`/
  `"1.00000000000000"` as *current* behavior, not as a spec requirement --
  both results are Floats (`.5` is a decimal literal), so this fix changes
  what they assert to the clean `"2"`/`"1"`, annotated in place with why.
  Added `tests/test_p31_clean_decimal_exact.py`: the F1 cases (`"1.5"` ->
  exact/decimal `"1.5"`, `"1e5"` -> exact `"100000"`), the F2 case (`"1/3"`
  -> exact `"1/3"`), and a regression that `"10^1000"` still answers
  decimal `"1e1000"`. Full suite: 272 passed, 4 skipped. No plan drift, no
  design question: additive, formatting-only, one new branch in one
  existing function.
- P33 (2026-11-15, Bug #27 fix): `graphcalc/static/style.css`,
  `tests/test_p33_wrapping.py`. Static files only, per the planner notes --
  no touch to `graphcalc/static/app.js` or any server Python module. Root
  cause per issue #27: no stylesheet rule anywhere gave the page a break
  opportunity inside a long unbroken run of characters, so any server text
  echoed verbatim into the DOM (a history entry's result, a variable's
  value, a function's body, or an error line that echoes a long bad input)
  widened its block and, with it, the whole page -- `{"expr":"10^1000"}`'s
  1,001-digit exact value made the Calculator tab 8,963px wide in a 1280px
  window. Fix: added `overflow-wrap: anywhere` (plus `word-break:
  break-word` as a fallback for a browser that doesn't know
  `overflow-wrap: anywhere`) to the existing `body` rule in `style.css`.
  Deliberately on `body`, not on `#calc-history`/`#calc-vars`/`#calc-error`
  individually, both because `.tab-panel` inherits it (CSS Grid/Flexbox note
  from the planner -- min-width:0 on a flex/grid child -- turned out to be
  moot here: `.tab-panel` is plain `display: block`, and `.tabs` is the only
  flex container, holding short fixed-text tab buttons, not server-echoed
  text) and because F3 asks for the rule on `body` or `.tab-panel` by name,
  so every tab, including Graphs/Lists & Statistics/CAS which don't exist
  yet, inherits the same protection for free. Added
  `tests/test_p33_wrapping.py`: four Playwright-driven checks (real
  Chromium, 1280x900 viewport, `document.documentElement.scrollWidth <=
  window.innerWidth` after submitting each of F1/F2's four expressions) plus
  one plain static-content regex check of `GET /static/style.css` for F3,
  skipped via `pytest.importorskip("playwright.sync_api")` if Playwright
  isn't installed. All five pass; full suite 236 passed, 1 skipped. No plan
  drift, no design question.
- P30 (2026-11-14, owner revision "ans:=5 refused"): `graphcalc/names.py`,
  `tests/test_p30_ans_reserved.py`. "ans" is not one of
  `calc._rad_names()`'s constants/functions -- it gets its own dedicated,
  non-variable storage slot in `graphcalc.state.CalcState`
  (`set_ans`/`ans`/`clear_ans`), separate from the `variables` map -- so
  before this step, `{"expr":"ans:=5"}` fell through to the ordinary
  `"name:=expr"` path and silently stored a *second*, unrelated "ans" in
  `CalcState.variables` (never read back, since `calc.evaluate` always
  prefers the dedicated ans slot over a same-named stored variable) while
  leaving the real stored answer untouched -- confusing, since the 200
  response looked like a normal definition. Fix: one-line change,
  `graphcalc.names.RESERVED_NAMES` now adds `"ans"` on top of
  `_rad_names()` and `{"i", "oo", "nan"}`, so the existing
  `check_not_constant(name)` call `cli._handle_calc_evaluate` already runs
  for every `"name:=expr"`/`"f(params):=expr"` definition (before any
  evaluation or storage) now also rejects "ans" -- 400
  `{"error": "cannot redefine constant ans"}`, exactly like `"pi:=3"`.
  Added `tests/test_p30_ans_reserved.py`: a direct unit test on
  `check_not_constant("ans")`, the F1 acceptance case itself (`"2+2"` then
  `"ans:=5"` -> 400, then `"ans"` still -> exact `"4"`), a check that the
  rejected assignment left both `GET /api/calc/vars` (`{"variables": {},
  "functions": {}}`) and `GET /api/calc/history` (still just the one
  `"2+2"` entry) untouched, and `"ans(x):=1"` (function-definition syntax)
  rejected the same way. Full suite still passes (see test run below). No
  plan drift, no design question: purely additive, no existing caller of
  `RESERVED_NAMES`/`check_not_constant` needed to change.
- P28/S3 (2026-11-14, Bug #20 fix): docs/tests only, no code change.
  Acceptance text asks that `{"expr":"10^1000"}` "still" give decimal
  `"1e1000"` after S1/S2's guard and backstop landed -- it already did:
  `graphcalc/numfmt.py::format_decimal` has built its scientific-notation
  branch from sympy's own `N()`/`Decimal` since P25, never from a plain
  `float()` call, so a magnitude past `sys.float_info.max`
  (`~1.7976931348623157e308`, where `float(Integer(10)**400)` would itself
  raise `OverflowError`) was never actually at risk -- confirmed by direct
  reading, not assumed. Added
  `test_format_decimal_past_float_range_builds_scientific_form_without_float`
  (`Integer(10)**400` -> `"1e400"`, `Integer(10)**1000` -> `"1e1000"`, and
  the negative case `-1e1000`), a stripping/sign check
  (`test_format_decimal_past_float_range_strips_trailing_zeros_and_dot`,
  also pinning a non-power-of-ten mantissa, `12 * 10**3990` ->
  `"1.2e3991"`), and a small-magnitude regression guard
  (`test_format_decimal_existing_small_number_result_unaffected`) to
  `tests/test_p28_freeze.py`. `test_p28_10_to_the_1000_still_gives_decimal_
  1e1000`/`..._over_http` (already added in S1) continue to cover the
  acceptance expr itself. No plan drift, no design question.
- P28/S2 (2026-11-14, Bug #20 fix): `graphcalc/calc.py`, `graphcalc/cli.py`,
  `graphcalc/limits.py` (comments only), `tests/test_p28_freeze.py`. S1's
  `is_power_too_large` guard only ever sizes up a literal `Pow` node in
  `expr`'s own text, so `{"expr":"2^10000000"}` (~3,010,300 digits, well
  past `MAX_POWER_DIGITS`) was already caught there -- but that guard is
  not the *only* way a result can get that large: a stored variable or
  "ans" used as a base/exponent, a factorial chain, or `simplify()` itself
  growing a value are all invisible to a text-only pre-check, and the
  resulting `str(result)` past `sys.get_int_max_str_digits()` (4300) raises
  Python's own `ValueError` ("Exceeds the limit (4300 digits)...") --
  `graphcalc.cli`'s catch-all then wrapped that as `"unexpected error:
  Exceeds the limit..."`, exactly the wording this plan step's acceptance
  criteria ban, regardless of a 200/400 status. Fix, two parts: (1) wrapped
  `calc.evaluate`'s `exact`/`decimal`/`complex` formatting block (the
  `str(result)` call and the `N()`/`format_decimal` calls that follow it)
  in its own `try/except (ValueError, OverflowError)`, reporting the same
  `DOMAIN_ERROR_TOO_LARGE` ("result too large to compute") domain_error
  used for a guard-caught power, never the raw exception text -- a true
  backstop, independent of S1's guard ever firing at all (verified directly:
  `test_p28_formatting_backstop_catches_value_error_when_guard_bypassed`
  monkeypatches `calc.is_power_too_large` to always return `False` and
  confirms `{"expr":"2^10000000"}` still answers the clean domain_error
  within budget, never the raw `ValueError` text). (2) `graphcalc.cli`'s own
  catch-all message changed from `"unexpected error: {exc}"` to `"request
  failed: {exc}"` as a second line of defense for any other exception this
  handler did not anticipate (`test_p28_server_catchall_error_text_has_no_
  unexpected_error_wording` forces `calc.evaluate` to raise a plain
  `RuntimeError` and confirms the word "unexpected" never appears). Also
  added `test_p28_2_to_the_10000000_raw_response_body_has_no_forbidden_
  wording_over_http`, which scans the *raw* HTTP response bytes (never
  `json.loads()`'d first) for either forbidden phrase, so the check covers
  the literal bytes sent over the wire, not just whichever JSON field
  happens to get inspected. `graphcalc/limits.py` itself is unchanged code
  (comments only, explaining why `MAX_POWER_DIGITS` staying well below 4300
  is still the first line of defense even with this backstop in place).
  No plan drift, no design question.
- P28/S1 attempt 2 (2026-11-14, Bug #20 fix): fixed a regression attempt 1's
  `graphcalc/limits.py::is_power_too_large()` introduced in
  `test_p24_multiletter_sec_deg_no_constant` and
  `test_p24_bare_names_no_constant` (both turned a clean 200 into a 400
  `"unexpected error: 'function' object has no attribute 'atoms'"`). Root
  cause: `is_power_too_large`'s own `parse_expr(expr, ..., evaluate=False)`
  call never passed `global_dict=_GLOBAL_DICT` (the module already defined
  that restricted dict, just never used it), so it defaulted to sympy's
  entire real namespace -- a bare `"sec"`, `"deg"`, `"S"`, `"N"` or `"Q"`
  then resolved to the real sympy function/singleton of that name instead
  of becoming a free `Symbol`, and `.atoms(Pow)` raised `AttributeError` on
  those (none is a sympy `Basic`). Fixed by passing `global_dict=
  _GLOBAL_DICT` to that call, adding an `isinstance(parsed, Basic)` guard,
  and wrapping the whole parse-and-walk body in one `try/except Exception:
  return False` (not just the parse step) so this guard can never itself
  turn a valid request into a crash, matching the plan step's own "treat
  any non-numeric or symbolic part as unknown and allow it" rule. Also
  lowered `MAX_POWER_DIGITS` from `10**5` to `4_000`: Python's own default
  integer-to-string conversion limit (`sys.get_int_max_str_digits()`, 4300
  on 3.11+) made `calc.evaluate`'s later `str(result)` call raise
  `ValueError("Exceeds the limit (4300 digits)...")` for a result between
  the old threshold and 4300 digits -- confirmed with `{"expr":
  "2^20000"}` (~6,021 digits) -- which `cli.py`'s catch-all then turned
  into exactly the forbidden `"unexpected error: Exceeds the limit..."`
  wording the acceptance criteria ban. 4,000 keeps margin below 4300 for
  this guard's own float-arithmetic imprecision while `{"expr":
  "10^1000"}` (1001 digits) still passes. Added
  `test_p28_2_to_the_20000_flagged_before_pythons_own_str_digit_limit` to
  `tests/test_p28_freeze.py`; `tests/test_p28_freeze.py` and
  `tests/test_p24_names.py` were otherwise unchanged from attempt 1. Full
  suite: 221 passed, 1 skipped. Known limitation, in-spec for S1: a stored
  variable used as a power's base/exponent bypasses this guard entirely
  (e.g. defining `a:=9` then evaluating `{"expr":"a^a^a"}`) -- the guard's
  own second parse sees a bare `Symbol`, not the stored value, so it is
  "unknown" and let through unflagged, then `calc.evaluate`'s real,
  evaluating `parse_expr` binds `a` to 9 and computes the tower exactly.
  The plan step's own rule ("any non-numeric or symbolic part" is unknown
  and always allowed) covers this; a future step would need to size up a
  referenced variable's *stored value*, not just the bare name, to close
  it.
- P27/S3 (2026-11-14, Bug #21 fix): `tests/test_p27_evaluator_hardening.py`
  (docs only this step; the code was already in place from P27/S2 below).
  Scope: send a `"name:=expr"`/`"f(params):=expr"` definition through the
  same two checks a plain expression already gets (S1's callable allowlist,
  S2's non-ASCII tokenizer rejection), run on the *whole raw input* --
  name, parameter list and body together -- and do it before any change to
  the in-memory vars or the on-disk state file, so a rejected definition
  leaves the stored vars byte-for-byte unchanged. Mechanism: S2's
  `re.ASCII` flag on `calc._DEFINITION_RE`/`_FUNCTION_DEFINITION_RE` already
  gives this for free -- a non-ASCII character in the name or a param
  (`"x²:=4"`, `"a２:=1"`, `"f(x²):=1"`) makes neither regex match at all, so
  `graphcalc.cli._handle_calc_evaluate` never takes the "definition" branch
  (never calls `CalcState.set_variable`/`set_function`) and instead falls
  through to a plain `calc.evaluate(expr, ...)` call on the *original,
  unsplit* string, which rejects the non-ASCII character itself via
  `check_grammar`/`_check_ascii_only` the same way any other expression
  does -- 400, before `parse_expr` ever runs. Added
  `test_p27_unicode_definition_superscript_in_name_is_400`,
  `test_p27_unicode_definition_fullwidth_digit_in_name_is_400`,
  `test_p27_unicode_function_definition_superscript_in_param_is_400` and
  `test_p27_unicode_rejected_definitions_do_not_change_stored_vars` (the
  last one POSTs all three, then confirms `GET /api/calc/vars` still
  answers `{"variables": {}, "functions": {}}`). Full suite (P23-P26
  included) still passes: 214 passed, 1 skipped.
- P27/S2 (2026-11-14, Bug #21 fix): `graphcalc/grammar.py`,
  `graphcalc/calc.py`, `tests/test_p27_evaluator_hardening.py`
  (undocumented until this step). Bug #21's other half:
  `{"expr":"２+２"}` (U+FF12 fullwidth digits), `{"expr":"٣+1"}` (U+0663
  Arabic-indic digit) and `{"expr":"x²"}` (U+00B2 superscript two) each
  evaluated successfully instead of answering 400. Root cause:
  `graphcalc.grammar._TOKEN_RE`'s `IDENT`/`NUMBER` groups are built on
  Python's own `\w`/`\d`, which are Unicode-aware by default (not the
  ASCII-only `[A-Za-z0-9_]`/`[0-9]` the grammar's docstring implies), so
  the regex happily matched "２+２" as two `NUMBER` tokens and "x²" as one
  `IDENT` token `"x²"` -- never reaching any rejection. Fix: new
  `grammar._check_ascii_only(expr)` scans every character ahead of the
  tokenizer loop (not folded into `_TOKEN_RE` as one more alternative,
  since a non-ASCII character that is only *part* of a larger match, like
  the "²" inside "x²", would never be inspected on its own once the regex
  had already consumed it) and raises for any non-ASCII letter, digit, or
  numeral (`isdigit()`/`isalpha()`/`isnumeric()`, plus a Unicode-category
  check on `Nd`/`No`/`L*` as a second net). Also added `re.ASCII` to
  `calc._DEFINITION_RE`/`_FUNCTION_DEFINITION_RE` (see P27/S3 above for why
  that part matters for a definition's name/params specifically, not just
  its body). New tests `test_p27_unicode_expr_raises_calc_error` (unit,
  parametrized) and the three `test_p27_unicode_expr_*_is_400` HTTP tests.
- P27/S1 (2026-11-14, Bug #21 fix): `graphcalc/calc.py`,
  `tests/test_p27_evaluator_hardening.py`. Bug #21 was that
  `{"expr":"Integer(2)"}`, `{"expr":"Float(2)"}`, `{"expr":"Rational(1,2)"}`
  and `{"expr":"factorial(5)"}` each evaluated successfully instead of
  answering 400. Root cause: `evaluate()`'s pre-parse "unknown function"
  check (`called_names(expr)` against `local_dict`, added for Bug #7/P24)
  also let a call through when the name was a key of `_GLOBAL_DICT` --
  the internal sympy constructors (`Integer`, `Float`, `Rational`,
  `Symbol`, `Function`, `factorial`) that `parse_expr`'s transformations
  (`auto_number`, `auto_symbol`, `factorial_notation`) emit from a
  *generated* AST node, never from literal text the user typed. Fix: drop
  the "or in `_GLOBAL_DICT`" half of that check, so a called name must be
  in `local_dict` regardless. `_GLOBAL_DICT` itself (what gets passed as
  `parse_expr`'s own `global_dict`) is untouched -- those constructors stay
  reachable for the transformations, just never via a name the user typed
  followed by `"("`, since `called_names()` only tokenizes the literal
  source text, never the generated AST. Verified `"5!"` -> exact `"120"`
  and `"1/3+1/6"` -> exact `"1/2"` still work (factorial_notation's and
  Rational's own generated calls, not literal "factorial("/"Rational(" in
  the source text), and the full suite (P23-P26 included) still passes.
  Out of scope for this step (left for a later P27 step per the plan):
  the Unicode-digit/letter/superscript tokenizer rejections.
- P26 (2026-11-14, Bug #14 fix): `graphcalc/calc.py`, `graphcalc/state.py`,
  `graphcalc/cli.py`, `tests/test_state_robustness.py`. Bug #14 was that a
  stored "ans", variable, or function could break a *later, unrelated*
  evaluation. Root cause: before this fix, a stored value was always rebuilt
  by plain `sympify()` of its `exact`/"**"-notation string -- sympy's own
  full namespace, not this calculator's restricted whitelist
  (`graphcalc.calc._rad_names()`). A name this calculator deliberately never
  whitelists -- `"beta"`, `"gamma"`, `"zeta"`, `"S"`, `"N"`, `"Q"` -- is a
  real sympy function/singleton in that namespace, not just a free `Symbol`,
  so re-`sympify()`-ing a stored value such as `"beta + 1"` raises
  (`TypeError: unsupported operand type(s) for +: 'FunctionClass' and
  'One'`); for "ans", that rebuild additionally ran *unconditionally* on
  every `evaluate()` call (S1), so storing `"beta + 1"` as "ans" broke the
  very next, unrelated `"1+1"`.
  Fix, two parts: (1) storage format -- alongside the existing plain
  `exact`/`body` string, `CalcState` now also persists that value's sympy
  `srepr()`: "ans" gained a `{"exact": str, "srepr": str}` shape (replacing
  the plain string history previously recalled "ans" from); variables and
  functions gained parallel top-level `"variable_sreprs"` (name -> srepr or
  `null`) and `"function_sreprs"` (name -> body srepr or `null`) maps
  alongside the unchanged `"variables"`/`"functions"`. `srepr()`'s
  `Symbol('beta')` is a quoted string literal constructor argument, never a
  bare name `sympify()` could resolve against its own namespace, so
  `sympify(srepr_string)` always reconstructs the *exact* original object
  regardless of what the name would otherwise mean bare. A name stored
  before this fix, or loaded from a hand-edited file, has `srepr=None` --
  `calc._rebuild_stored_value`/`_function_locals` then fall back to the old
  plain-`sympify()` rebuild for that one name, same as always. (2) laziness
  -- `calc.evaluate` now only ever attempts to rebuild a stored "ans",
  variable, or function (`calc._referenced_names`, generalizing S1's
  single-name "ans" check to every stored name) when the expression
  actually references that name as a whole token. A definition this
  calculator cannot safely rebuild can therefore only ever break a request
  that actually uses it; `"1+1"` is never affected by any stored "a", "f" or
  "g", no matter how badly any of them is stored, or how unrebuildable an
  "ans" is. A bare `"ans"` request is a true fixed point: it now reuses the
  previous call's own `exact`/`srepr` verbatim instead of re-`str()`-ing a
  freshly rebuilt object. `graphcalc.calc.evaluate`'s private
  `"_result_srepr"` return key threads the freshly-computed `srepr()`
  straight into `CalcState.set_ans`/`set_variable`/`set_function` for the
  *next* call, without re-deriving it (ambiguously) from the plain `exact`
  string; `graphcalc/cli.py` pops it from the response dict before sending
  it, under that exact key name (an earlier attempt at this fix left
  `cli.py` popping a stale `"_ans_srepr"` key from a prior rename in
  `calc.py`, so `ans_srepr` was always `None` and every rebuild silently
  fell back to the unsafe path -- worth remembering if this key gets
  renamed again: grep every popper, not just the definer).
  No plan drift: the plan step's file list named `graphcalc/evaluator.py`;
  no such module exists in this repo, and none was created -- the logic it
  describes (`evaluate()`, `parse_definition()`,
  `parse_function_definition()`) lives in `graphcalc/calc.py`, confirmed by
  direct reading, so that file is what changed instead.
  One judgment call, recorded rather than left implicit: F2's acceptance
  text (`"f(x):=beta(x)"` then `"1+1"` -> 200 `"2"`) does not require
  `"f(x):=beta(x)"` to itself succeed, and this fix does not make it
  succeed -- `"beta"` stays outside `graphcalc.calc._rad_names()`'s
  whitelist, so `called_names` (P24/S3) still rejects calling it with 400
  `"unknown function 'beta'"`, the same way it already rejects `"zeta(2)"`.
  Widening that whitelist would itself be P24/S3 drift. What F2 needs, and
  what `tests/test_state_robustness.py` checks, is that the failed attempt
  stores nothing and leaves `"1+1"` unaffected; a function body that
  references `"beta"` *without* calling it (`"g(x):=beta*x"`) stores fine
  and exercises the same srepr-rebuild machinery, used to also prove the
  reload case (a value/body missing its srepr -- an old-format or
  hand-edited state file -- degrades to a 400 for *that* name only, never a
  500, and never for an unrelated expression).
- P25 (2026-11-05, decimal formatting): `graphcalc/numfmt.py`. Before this
  fix, `format_decimal` always rounded to 12 significant digits with
  `Decimal`'s context precision, then printed with `format(digits, "f")` --
  fixed-point only. Decimal's context rounding keeps the original exponent,
  so a value needing more than 12 integer digits (e.g. `2**100`, 31 digits)
  came back as the 12 rounded digits followed by the right number of
  literal zeros (`"1267650600230000000000000000000"`-shaped), not a
  12-significant-digit value -- and the existing "strip trailing zeros"
  step never fired because a whole number has no `"."` in fixed-point text.
  Fix: after rounding, check the rounded `Decimal`'s `adjusted()` (the
  position of its leading digit); once that reaches `sig` (12), format with
  `format(digits, "E")` instead, strip trailing zeros from the mantissa the
  same way the fixed-point path already strips them, and rebuild as
  `f"{mantissa}e{int(exponent)}"` -- `int()` on the exponent drops the `+`
  and any leading zeros `Decimal`'s `"E"` format would otherwise print.
  `2**100` -> decimal `"1.26765060023e30"`. The threshold is exactly `sig`
  digits: a 12-digit integer (`10**11`) still prints fixed-point; a
  13-digit one (`10**12`) already switches (`"1e12"`). Every magnitude
  `format_decimal` already handled correctly (small fractions, exact
  integers under 12 digits) is untouched -- the new branch only runs when
  `adjusted() >= sig`. Added `tests/test_p25_scientific_notation.py`: the
  F1 acceptance case over HTTP, plus unit tests on `format_decimal` directly
  for the exact-12-digit/13-digit boundary, a negative large value, a
  mantissa that must not pad out with trailing zeros, and a regression
  check on the small-magnitude values from earlier steps. No plan drift, no
  design question: formatting-only change, one function, no caller needed
  updating.
- P24 (2026-11-05, Bug #7 fix): `graphcalc/calc.py`, `graphcalc/grammar.py`.
  Bug #7 was that `_TRANSFORMATIONS` used sympy's bundled
  `implicit_multiplication_application`, whose first step, `split_symbols`,
  breaks any identifier not already in `local_dict`/`global_dict` into one
  symbol per letter and re-resolves each letter on its own -- so `"rate"`
  evaluated to `"E*a*r*t"` (its `"e"` silently became the whitelisted
  constant `E`), `"sec"` to `"E*c*s"`, `"deg"` to `"E*d*g"`, and
  `"SIN(pi/2)"` (not a whitelisted name) to `"I*pi*N*S/2"` -- never the
  single multi-letter name a TI-Nspire CAS user typed.
  Fix (S1): `_TRANSFORMATIONS` now keeps only `implicit_multiplication`,
  `implicit_application` and `function_exponentiation` from the bundle --
  `split_symbols` is dropped entirely, so a run of letters/digits/
  underscores (`graphcalc/grammar.py`'s own `_TOKEN_RE` IDENT group) always
  parses as exactly one `Symbol`, mapped through `_rad_names()`/
  `_deg_names()` when whitelisted, through `variables`/`functions`/a
  function definition's own params when user-defined, and otherwise left
  as a plain `Symbol(name)` -- `rate`, `xy`, `sec`, `deg` and `S`/`N`/`Q`
  (real sympy singletons this calculator never whitelists) all come back
  as themselves, with no stray `E`/`I`. Implied multiplication (`2x`,
  `2pi`, `2sin(pi/6)`) and `e`/`E`/`I` as standalone names are unaffected,
  since those come from `implicit_multiplication`/`implicit_application`
  and `_rad_names()`, not `split_symbols`.
  S3 closed a second hole the same root cause left open: without
  `split_symbols`, an unknown name called with `"("` (`"SIN(pi/2)"`, or a
  real sympy name this calculator never whitelisted, `"zeta(2)"`) would
  otherwise fall to `parse_expr`'s own `auto_symbol` fallback, which wraps
  it in a `Function` call that `implicit_multiplication`'s close-paren-
  before-open-paren rule immediately downgrades back to a plain `Symbol`
  times the argument list -- `"SIN(pi/2)"` silently becoming `"pi*SIN/2"`
  instead of a 400. New `graphcalc/grammar.py::called_names(expr)` shares
  `check_grammar`'s own tokenizer to return every identifier immediately
  followed by `"("`; `calc.evaluate` now checks each one against the
  completed `local_dict` and against `_GLOBAL_DICT` *before* calling
  `parse_expr`, raising `CalcError("unknown function '<name>'")` (-> 400)
  for anything in neither. New `tests/test_p24_names.py`, including
  `test_p24_bare_names_no_constant` (S2: `sec`, `deg`, `S`, `N`, `Q` as
  plain Symbols, plus `E`/`I` still resolving as constants on their own)
  and the F1-F4 acceptance cases. No plan drift, no design question: the
  fix is additive (drop one transformation, add one pre-parse check) and
  every existing P5-P23 test (implied multiplication, `ans`, variables,
  functions, the P23 grammar gate) kept passing unchanged.
- P23 (2026-11-05, Bug #5 fix): `graphcalc/grammar.py`, new. Bug #5 was that
  `graphcalc.calc.evaluate`'s sympy `parse_expr` call -- built on Python's
  own tokenizer -- silently accepted a lot more than this calculator's
  grammar. `check_grammar(expr)` now runs before every `parse_expr` call
  (both the plain-expression and the `name:=expr`/`f(x):=expr` definition
  paths in `graphcalc/cli.py`) and raises `grammar.GrammarError`, caught in
  `calc.evaluate` and re-raised as the usual `CalcError` -> 400, never a 500.
  The accepted grammar, spelled out for the next session:
  - Numbers: digits, an optional decimal point with digits after it, an
    optional `e`/`E` exponent -- exactly Python's float grammar. No hex
    (`0x10`), no binary (`0b11`), no octal (`0o7`), no underscore digit
    grouping (`1_000`), no imaginary suffix (`2j`, `3J`).
  - Operators: `+ - * / ^ ** ( ) , !`. No comparison (`< > <= >= == !=`), no
    `%`, no `//`, no bitwise/shift (`& | ~ << >>`). A bare `=` is let through
    at the token level on purpose -- `parse_expr`'s own failure to parse two
    bare `=` tokens is what rejects `"1 = = 2"`, and `"=="` is tokenized and
    rejected as its own two-character token, so `"1==2"` is rejected here
    instead.
  - Postfix `!` (`5!` -> `120`, via sympy's `factorial_notation`), top-level
    `name:=expr` definitions, and implied multiplication (`2x`, `2(x+1)`)
    all stay allowed, exactly as before this fix.
  - A call to one of the calculator's built-in one-argument functions
    (`sqrt`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `ln`, `log`, `exp`,
    `abs` -- `graphcalc.calc._rad_names()` minus the constants `pi`/`e`/`E`/`I`)
    is rejected if it has more than one top-level, comma-separated argument
    (`ln(e,2)`, `sqrt(4,2)`); a call to any other name (e.g. a user-defined
    function `f(x,y):=...`) is left alone, since this grammar gate has no
    way to know a user function's own arity and `calc.evaluate`'s existing
    "wrong number of arguments" check already handles that case.
  - Everything else the tokenizer doesn't recognize at all (`{`, `}`, `[`,
    `]`, `@`, ...) is rejected too, so `"{1:2}"` and `"(1,2)"` both still
    answer 400 (the latter via `parse_expr` itself refusing a bare tuple,
    same as before this fix -- `check_grammar` lets a lone `,` through so a
    function call's own argument separator keeps working).
  Implemented across three steps: S1 added the tokenizer and the rejected
  operator/literal groups; S2 added `test_grammar_literals_*`-named tests
  pinning the six Python-only-literal inputs plus an implied-multiplication
  guard for names starting with `j`/`J` (`2job`, `3Jane`); S3 added the
  per-function arity count (`_has_top_level_comma`, depth-tracked past
  nested parens) and the `test_grammar_arity_*`-named tests for `ln(e,2)`/
  `sqrt(4,2)` plus a guard that `sqrt(4)` still answers exact `"2"`. See
  `graphcalc/grammar.py`'s own module and function docstrings for the
  tokenizer's ordering rules (why HEX/BIN/OCT must be tried before NUMBER,
  why `:=`/`!=`/`==`/`//` must be tried before their shorter prefixes) and
  `tests/test_evaluate_grammar.py`'s docstring for the full test-naming
  rationale.
- P8 (2026-10-31): Calculator tab UI, in `graphcalc/static/index.html` and
  `graphcalc/static/app.js` only, per the plan's file list. Added the six
  ids PRODUCT.md pins inside `tab-calculator`: `calc-input`, `calc-mode`
  (a `rad`/`deg` `<select>`), `calc-submit`, `calc-history`, `calc-vars`,
  `calc-error`. `app.js` wires them with plain `fetch()` on relative paths,
  no external resources: submitting (click `calc-submit`, or Enter in
  `calc-input`) POSTs `{"expr", "mode"}` to `/api/calc/evaluate`; a 400 or a
  `domain_error` puts the message in `calc-error` and stops there; a clean
  result instead re-fetches `GET /api/calc/history` and `GET /api/calc/vars`
  and rebuilds `calc-history`/`calc-vars` from scratch each time, so the UI
  can never drift from server state by patching incrementally. Both
  acceptance criteria are static-content checks, not behavioral ones --
  there is no in-process JS engine in this test suite -- so
  `tests/test_calc_ui.py` starts a real `graphcalc.cli.Handler` server and
  checks `GET /`'s parsed element ids and `GET /static/app.js`'s literal
  path strings; the fetch round-trips themselves are left to the
  acceptance suite / a real browser, noted in the test file's own
  docstring. No design decision and no plan drift: P5-P7 had already shipped
  every endpoint this tab calls, so no `graphcalc/cli.py` or route change
  was needed.
- P7/S3 (2026-10-31): `GET /api/calc/vars` in `graphcalc/cli.py`.
  `_handle_calc_vars_get` reads the HTTPServer's `graphcalc.state.CalcState`
  (same `_state(handler)` helper S1 added) and answers 200
  `{"variables": {name: exact}, "functions": {name: {"params", "body"}}}`.
  Concretely, after `"a:=5"` and the S2 function-definition syntax
  `"f(x):=x^2+1"` (or `"f(x,y):=expr"` for more than one param), `GET
  /api/calc/vars` answers exactly
  `{"variables": {"a": "5"}, "functions": {"f": {"params": ["x"], "body":
  "x^2 + 1"}}}`; redefining `pi`, `e` or `I` (as either a variable or a
  function name) still answers 400 `{"error": "cannot redefine constant
  <name>"}` and leaves this response unchanged.
  Both the variable values and the function bodies are run through
  `calc.to_caret` -- the same formatter S2's function-definition response
  already uses -- so a stored `"x**2 + 1"` prints as `"x^2 + 1"` here too
  (pinned by `test_calc_vars_caret_for_variables`,
  since S1/S2's own tests only ever exercised a caret-free value like `"5"`
  for a variable). No new design decision: `names.check_not_constant`
  already rejects `pi`/`e`/`I` (and the rest of `RESERVED_NAMES`) *before*
  `calc.evaluate` or `CalcState.set_variable`/`set_function` ever run (S1's
  `_handle_calc_evaluate` calls it first thing inside the
  `parse_definition`/`parse_function_definition` branches), so state is
  already guaranteed unchanged on a rejected definition -- this step only
  adds `test_calc_vars_redefining_e_or_i_rejected` and
  `test_calc_vars_pi_still_evaluates` to pin that explicitly for `e` and `I`,
  alongside `pi` (already covered by `test_calc_vars_redefining_pi_rejected`,
  renamed from S1's `test_redefining_pi_is_rejected` so every test proving
  this step's acceptance criteria -- the vars listing and the `pi`/`e`/`I`
  rejection -- is collectible with `-k calc_vars`). `vars` itself is read-only -- it never
  evaluates or stores anything, so it has no `check_not_constant` call of
  its own.
- P7/S1 (2026-10-31): `"name:=expr"` variable definitions. New
  `graphcalc/calc.py::parse_definition(expr)` (an anchored
  `^\s*(ident)\s*:=\s*(.+?)\s*$` regex) returns `(name, rhs)`, or `None` for
  anything else -- including `"f(x):=expr"`, whose `"("` right after the
  name can never match this pattern, so function definitions are cleanly
  left for a later step. `calc.evaluate` gained a `variables: dict | None`
  parameter, merged into `local_dict` via plain `sympify()` (never
  `_rad_names()`/`_deg_names()`, which remaps `log`/degrees and would
  corrupt a stored value, same reasoning as `ans` in P6/S2's notes) -- a
  bound name is never split by `split_symbols`, so `"2a"` resolves to
  `"2*5"` once `a` is stored.
  Plan drift, noted explicitly rather than left silent:
  - The plan's file list named `graphcalc/server.py`; this repo's HTTP
    handler is `graphcalc/cli.py` (NOTES.md already recorded this same
    mismatch for P2/S3). All server-side wiring landed in `cli.py`.
  - The plan asked to store variables "in the same persisted state object
    as history." That is not literally what landed: history
    (`graphcalc/history.py`'s `HistoryStore`) and the new
    `graphcalc/state.py::CalcState` are two separate objects, each held on
    the `HTTPServer` instance (`.history_store` and `.state`). Unifying
    them means editing `history.py`, which is outside this step's file
    list, and PRODUCT.md already charters that unification, plus the
    `--state` CLI flag, atomic-write detail and `.gitignore` entry, as a
    separate feature (P9). `CalcState` only does what P7 itself needs:
    an in-memory `{"variables", "functions"}` dict, optionally mirrored to
    an explicitly-given JSON file path (load on construction, atomic
    `os.replace` write-through on every change). With no path -- the
    default for `build_server(port)` and what `--in-memory` relies on --
    it never touches disk, so the acceptance/hidden-suite run creates no
    stray file. There is no `--state` flag yet; a test that wants the
    "survives a restart" behavior builds two `CalcState`/server instances
    on the same explicit path by hand (`test_variable_survives_server_
    restart_on_same_state_file` in `tests/test_calc_definitions.py`).
  `cli.py::_handle_calc_evaluate` now checks `calc.parse_definition` first:
  `names.check_not_constant(name)` (already added by P5/S3 for exactly
  this) rejects a reserved name before anything is evaluated (`"pi:=3"` ->
  400 `"cannot redefine constant pi"`, and critically, nothing gets stored
  -- storing it first would shadow the real `pi` in every later
  expression's `local_dict` merge); only a right-hand side with no
  `domain_error` is stored, so `"a:=1/0"` answers 200 with the domain error
  and leaves `a` undefined. A definition is deliberately not appended to
  the history store, so it cannot be recalled via `ans`; PRODUCT.md's `ans`
  examples are all plain evaluations.
- P6/S3 (2026-10-31): `DELETE /api/calc/history` in `graphcalc/cli.py`.
  `_handle_calc_history_delete` calls `_history_store(handler).clear()`
  (already implemented by S1's `InMemoryHistoryStore.clear()`) then answers
  200 `{"history": []}`, same shape as a fresh store. Wired as
  `Handler.do_DELETE`, matching only `CALC_HISTORY_PATH` exactly, 404 JSON
  otherwise -- `BaseHTTPRequestHandler` has no default `do_DELETE`, so
  without this method a DELETE request would 501, not 404 or 500; this is
  the first route this product serves outside GET/POST. No new design
  decision: S2 already made "ans" raise `CalcError("ans is undefined")`
  whenever `_history_store(handler).last()` is `None`, which is exactly the
  state DELETE restores, so clearing the store and re-evaluating "ans"
  exercises that same existing path -- confirmed by
  `test_history_delete_and_ans_undefined` (evaluate "2+3", DELETE -> 200
  `{"history": []}`, GET -> `{"history": []}`, evaluate "ans" -> 400
  `{"error": "ans is undefined"}`). Also folded the history/"ans" feature
  (S1-S3) into `CHANGELOG.md`, which S1/S2 had left undocumented there.
- P6/S2 (2026-10-31): "ans" substitution in `graphcalc/calc.py`'s `evaluate`.
  New `last_entry: dict | None` parameter; cli.py's `_handle_calc_evaluate`
  now passes `_history_store(handler).last()` into it -- this one-line
  `cli.py` change was outside S2's declared file list (`calc.py`,
  `tests/test_history.py`) but is required for the feature to reach the
  HTTP path at all, so it's noted here as plan drift rather than silent.
  Pitfall that cost a design pass: `_TRANSFORMATIONS` includes
  `implicit_multiplication_application`, which bundles `split_symbols` --
  an *unbound* `ans` (not in local_dict) parses as `Symbol('ans')` only
  until `split_symbols` sees no binding for it and splits it into
  `a*n*s` (`calc.evaluate("ans*2")` returned `exact == "2*a*n*s"` before
  this fix). So "ans" must always be bound in `local_dict`: to
  `sympify(last_entry["exact"])` when history has an entry, or to a
  private `Dummy("ans")` sentinel (`calc._UNDEFINED_ANS`) when it does
  not. A bound name is never auto-symboled/split, so "ans" stays one
  token either way, and binding via `local_dict` (not a string
  substitution before parsing) is also what makes it match only as a
  whole token -- "answer" tokenizes as one identifier regardless. When
  the sentinel survives into the parsed expression's `free_symbols`,
  `evaluate` raises `CalcError("ans is undefined")` (-> 400) from inside
  the same `try` that already re-raises `CalcError` unchanged. `exact`
  is reparsed with sympy's own `sympify`, not through `_rad_names()` /
  `_deg_names()` -- that whitelist remaps `log` to log10 and would
  double-convert degrees, so reusing it to read back a stored `exact`
  would corrupt it. Known gap, not covered by any acceptance criterion
  (verified by hand, `calc.evaluate("ans-ans")` with no `last_entry`):
  `"ans-ans"` does *not* raise "ans is undefined". `parse_expr` combines
  the two identical `_UNDEFINED_ANS` `Dummy` instances into `Integer(0)`
  while building the expression tree, before `evaluate` ever checks
  `free_symbols`, so the sentinel is already gone and the call quietly
  returns `exact: "0"`. The `free_symbols` check only catches a sentinel
  that survives to the parsed expression, not every syntactic use of
  "ans" -- worth knowing if a later step wants "did the input mention
  ans" rather than "does ans remain undefined in the result".
- P5/S3 (2026-10-31): the free-symbol and mode/expr validation this step
  asked for ("2x" -> exact "2*x", decimal null; an invalid or non-string
  `mode`, and a missing or non-string `expr`, 400; a syntax error 400 never
  500) all already worked from S1/S2's `graphcalc/calc.py` --
  `standard_transformations` already includes `auto_symbol`, so an
  undefined name becomes a `Symbol` for free, and `evaluate`'s
  `mode not in ("rad", "deg")` check already rejects any non-string value
  too. Added `tests/test_p5_symbols_mode.py` to pin all of that down
  explicitly rather than leaving it implicit. The only new code is
  `graphcalc/names.py`: `check_not_constant(name)` raises `calc.CalcError`
  (-> 400, message `"cannot redefine constant <name>"`) for a reserved
  name. `RESERVED_NAMES` is built from `calc._rad_names()` (never a
  hand-copied list) plus `"i"`, `"oo"`, `"nan"`, so it tracks the parser's
  whitelist if that ever grows. This is where P7 will call it from before
  letting `name:=expr` define a variable or function (`"pi:=3"` -> 400
  `"cannot redefine constant pi"`).
  - Complex format (from P5/S1, for reference): `complex` is
    `{"real": str, "imag": str}`, each run through the same
    `numfmt.format_decimal` used for `decimal`, set only when the result's
    imaginary part is nonzero; `exact` stays sympy's own `str()`
    regardless.
  - `domain_error` rules (from P5/S2, for reference): `zoo`/`oo`/`-oo` ->
    `"division by zero"` (`calc.DOMAIN_ERROR_DIVISION_BY_ZERO`); `nan` ->
    `"undefined"` (`calc.DOMAIN_ERROR_UNDEFINED`); either way `exact`,
    `decimal` and `complex` all report `null` instead of trying to format
    a valueless result.
- P2/S3 attempt 2 (2026-10-27): `test_static_security_escapes_allowed_extension`
  (added attempt 1; points a traversal at a sibling `.js` file so the
  `is_relative_to(STATIC_DIR.resolve())` check, not the extension allowlist,
  is what stops it) failed on Windows because its fixture wrote the "inside"
  file with `Path.write_text(...)`, which translates `\n` to `\r\n` in text
  mode -- the server was serving the file correctly, the fixture's bytes were
  wrong. Fixed by writing the fixture with `Path.write_bytes(b"...")`. No
  server code changed. Lesson: any test asserting exact file bytes must write
  its fixtures with `write_bytes`/`open(..., "wb")`, never `write_text`.
- P2/S3 (2026-10-27): hardened the `/static/<name>` route in `graphcalc/cli.py`.
  The decoded name is now checked for a NUL byte, a backslash, or an absolute
  segment before any filesystem access, and the resolved candidate must be
  `is_relative_to` `STATIC_DIR.resolve()` or it 404s with a JSON error. Added
  `test_static_security_traversal` (raw, unnormalized request paths over
  `http.client`: `/static/../server.py`, `/static/%2e%2e/server.py`,
  `/static/..%2fserver.py`, `/static/%2e%2e%5cserver.py`), plus
  `test_unknown_routes_are_json_404_not_500` and
  `test_static_security_no_external_urls` (regex-scans `/`, `/static/app.js`,
  `/static/style.css` for any `http(s)://` URL and asserts it points at
  127.0.0.1). The repo has no `graphcalc/server.py`; the HTTP handler and
  static route live in `graphcalc/cli.py` (see S1's notes/history) -- this
  step's "server.py" references are the traversal target string, not a file
  to create.
- Bootstrapped by `scio new` (2026-10-27): walking skeleton, CI, smoke test.
