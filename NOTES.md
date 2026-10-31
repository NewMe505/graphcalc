# Notes

- M1 Server skeleton, static UI shell and core evaluation merged by `scio build`: P1 passed, P2 passed, P3 passed, P4 failed, P4 failed, P4 passed; $16.4903.
Working notes SCIO and humans leave for the next session. Newest first.

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
