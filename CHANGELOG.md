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

### Security
- Hardened the `/static/<name>` route against path traversal: reject a NUL
  byte, a backslash or an absolute segment in the decoded name outright, and
  require the resolved path to stay inside `STATIC_DIR.resolve()`. Unknown
  routes (e.g. `/server.py`) keep answering a JSON 404, never a 500.
