# Changelog

## [Unreleased]
### Added
- Walking skeleton: package, `--version`, smoke test, CI (SCIO bootstrap).
- `GET /` serves the static UI shell: one HTML page with the four tab panels
  (`tab-calculator`, `tab-graphs`, `tab-lists`, `tab-cas`) and a `graph-canvas`
  canvas, plus plain `app.js`/`style.css` -- no build step, no external
  resources.
- `GET /static/<name>` serves `graphcalc/static/*` with an explicit content
  type for `.js` (`application/javascript`), `.css` (`text/css`) and `.html`;
  any other extension, or a missing file, answers a JSON 404. The static
  files ship as package data (`pyproject.toml`'s `package-data`).
- `POST /api/calc/evaluate` evaluates an arithmetic expression with sympy:
  `+ - * / ^`, parentheses and implied multiplication (e.g. `"2(3+1)^2"`).
  Answers 200 with `{"expr","exact","decimal","complex","domain_error"}`;
  `decimal` is a 12-significant-digit string with no trailing zeros
  (`"1/3"` -> `"0.333333333333"`), and `complex`/`domain_error` stay `null`
  until later features set them. A parse error or an invalid `mode` answers
  400 `{"error": <message>}`; a missing `expr` answers 400 with
  `"missing parameter: expr"`. The handler never answers a 500. Added
  `graphcalc/calc.py` (the parser/evaluator, separate from HTTP) and
  `graphcalc/numfmt.py` (the shared 12-significant-digit decimal formatter,
  reused by later features).
- `POST /api/calc/evaluate` (P5): a non-real result now answers `exact` as
  sympy's own `str()` (e.g. `"sqrt(-4)"` -> `"2*I"`) plus a rectangular
  `complex` form `{"real","imag"}`, each a 12-significant-digit string
  (`"ln(-1)"` -> `complex {"real":"0","imag":"3.14159265359"}`); a real
  result keeps `complex` `null` as before. A result with no value answers
  200 with `exact`, `decimal` and `complex` all `null` and a `domain_error`
  string instead: `"division by zero"` for a division by zero (`"1/0"` ->
  `zoo`, or `oo/-oo`), a non-null message for an indeterminate form (`"0/0"`
  -> `nan`). An undefined name parses as a sympy `Symbol` via implicit
  multiplication (`"2x"` -> exact `"2*x"`); when the result still has free
  symbols, `decimal` (and `complex`) stay `null` instead of being formatted.
  `mode` accepts only `"rad"` or `"deg"` (missing keeps the existing
  default); any other value, including a non-string one, is a 400, same as
  a missing or non-string `expr`. Syntax errors and any other unexpected
  failure inside the handler stay a 400, never a 500. Added
  `graphcalc/names.py`: `check_not_constant(name)` raises the same
  client-error exception (`CalcError` -> 400) for a reserved constant or
  function name (`pi`, `e`, `E`, `I`, `i`, `oo`, `nan`, and the whitelisted
  trig/log/exp/sqrt/abs names); P7's `name:=expr` variable/function
  definitions will call it too.

- Evaluation history (P6): every successful `POST /api/calc/evaluate` (no
  parse error, no `domain_error`) is appended to an in-memory history as
  `{"expr","exact","decimal"}`, oldest first. `GET /api/calc/history`
  answers 200 `{"history": [...]}`. `ans` in an expression (e.g. `"ans*2"`)
  substitutes the exact value of the last entry; with no history yet, or
  right after `DELETE /api/calc/history`, evaluating `"ans"` answers 400
  `{"error": "ans is undefined"}` instead of treating it as a free
  variable. `DELETE /api/calc/history` clears the history and answers 200
  `{"history": []}`. History lives behind a `HistoryStore` interface
  (`graphcalc/history.py`); the only implementation today is in-memory and
  does not survive a restart.

- Variable definitions (P7/S1): `"name:=expr"` (e.g. `"a:=5"`) evaluates
  `expr`, stores its exact value under `name`, and answers 200 with the
  usual evaluate shape, `"expr"` set to the original `"name:=expr"` text.
  A later expression (e.g. `"2a+1"`) substitutes the stored value the same
  way `pi` or `ans` already do (`graphcalc/calc.py`'s `evaluate` gained a
  `variables` parameter). Redefining a reserved constant (e.g. `"pi:=3"`)
  answers 400 `{"error": "cannot redefine constant pi"}` via
  `graphcalc/names.py`'s existing `check_not_constant`, and stores nothing.
  A right-hand side with a `domain_error` (e.g. `"a:=1/0"`) answers 200
  with the domain error and also stores nothing. New `graphcalc/state.py`:
  `CalcState` holds `{"variables", "functions"}` (`functions` defaults to
  `{}` so an older state file without it still loads); with no path it is
  in-memory only (what the default server and `--in-memory` use, so no
  file is ever created), and with a path it loads that file's JSON and
  writes through atomically after every change, so a new `CalcState` on
  the same path picks up where the last one left off. `"f(x):=expr"`
  function definitions, `GET /api/calc/vars`, and the `--state` CLI flag
  (P9) are separate, later steps.

### Security
- Hardened the `/static/<name>` route against path traversal: reject a NUL
  byte, a backslash or an absolute segment in the decoded name outright, and
  require the resolved path to stay inside `STATIC_DIR.resolve()`. Unknown
  routes (e.g. `/server.py`) keep answering a JSON 404, never a 500.
