# Notes

- M1 Server skeleton, static UI shell and core evaluation merged by `scio build`: P1 passed, P2 passed, P3 passed, P4 failed, P4 failed, P4 passed; $16.4903.
Working notes SCIO and humans leave for the next session. Newest first.

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
