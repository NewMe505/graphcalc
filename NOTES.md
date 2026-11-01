# Notes

- M1 Server skeleton, static UI shell and core evaluation merged by `scio build`: P1 passed, P2 passed, P3 passed, P4 failed, P4 failed, P4 passed; $16.4903.
Working notes SCIO and humans leave for the next session. Newest first.

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
