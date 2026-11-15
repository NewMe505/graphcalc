# GraphCalc: a local CAS graphing calculator in the browser

A local graphing calculator inspired by the TI-Nspire CX CAS. A Python HTTP server bound to 127.0.0.1 does all the math through a JSON API with one endpoint per operation, using sympy. It also serves one plain HTML/CSS/JS page with four tabs: Calculator, Graphs, Lists & Statistics, and CAS. The page only draws what the API returns. Every result can be checked over HTTP. A client mistake gets a 400 with a JSON error and never a 500. State is kept on disk, so it survives a restart.

## Run

<!-- scio:run -->
```
python -m graphcalc --version
```
<!-- scio:run-end -->

## Use

Start the server, e.g. `python -m graphcalc --port 8000 --in-memory`, then open
`http://127.0.0.1:8000/` in a browser. `GET /` serves one plain HTML/CSS/JS
page (no build step, no CDN or other external resources) with four tabs:
Calculator, Graphs, Lists & Statistics, and CAS. The page only draws what the
JSON API returns.

The UI shell is served from two routes:
- `GET /` -- `text/html`, the tab page (`tab-calculator`, `tab-graphs`,
  `tab-lists`, `tab-cas`, and a `graph-canvas` canvas on the Graphs tab).
- `GET /static/<name>` -- the page's own `.js`/`.css`/`.html` files with an
  explicit content type (e.g. `application/javascript`, `text/css`). Any
  other path, including a traversal attempt, answers a JSON 404, never a 500.

The calculator's math goes through a JSON API, one endpoint per operation:
- `POST /api/calc/evaluate` -- body `{"expr": str, "mode": "rad"|"deg"}`
  (`mode` is optional, default `"rad"`). Parses `+ - * / ^`, parentheses,
  postfix `!` (e.g. `"5!"` gives exact `"120"`) and implied multiplication
  (e.g. `"2(3+1)^2"`). Answers 200 with
  `{"expr", "exact", "decimal", "complex", "domain_error"}`: `exact` is
  sympy's simplified result as a string, `decimal` is a 12-significant-digit
  string with no trailing zeros (e.g. `"1/3"` gives `"0.333333333333"`), and
  `complex`/`domain_error` are `null` unless set. Once a value's magnitude
  needs more than 12 digits before the decimal point, `decimal` (and
  `complex`'s `real`/`imag`) switch to scientific notation instead --
  `"2^100"` gives `"1.26765060023e30"`, 12 significant digits, no trailing
  zeros in the mantissa, lowercase `e`, no `+` and no leading zeros in the
  exponent. A parse error or an invalid
  `mode` answers 400 with `{"error": <message>}`; a body with no `expr`
  answers 400 with `{"error": "missing parameter: expr"}`. Never a 500.

  A non-real result (e.g. `"sqrt(-4)"`) keeps `exact` as sympy's `str()`
  (`"2*I"`) and also fills `complex` with a rectangular
  `{"real": str, "imag": str}`, each a 12-significant-digit string
  (`"ln(-1)"` gives `complex {"real": "0", "imag": "3.14159265359"}`).
  A result with no value answers 200 with `exact`, `decimal` and `complex`
  all `null` and `domain_error` set instead: `"division by zero"` for a
  division by zero (`"1/0"`), or a non-null message for an indeterminate
  form (`"0/0"`). A power whose exact result would take an unreasonable
  number of decimal digits to compute -- a tower such as `"9^9^9"` or
  `"10^10^10"`, or a huge exponent such as `"2^10000000"` -- is sized up
  from the expression's text alone, before sympy ever tries to compute it,
  and also answers 200 with `domain_error: "result too large to compute"`
  instead of blocking the server: each still answers within a few seconds,
  and a later request (e.g. `"1+1"`) is answered normally, never left
  waiting behind it. A power that is merely large but still exact, such as
  `"10^1000"`, is unaffected -- it still answers `exact` (a 1001-digit
  integer) and `decimal` `"1e1000"`, same as always. An undefined name
  parses as a free symbol, as on the
  TI-Nspire CAS (`"2x"` gives exact `"2*x"`); a multi-letter name such as
  `"rate"` or `"xy"` is always one symbol, never split into letters, so an
  `e`, `E` or `I` that merely appears inside a longer name never becomes a
  constant (`"rate"` gives exact `"rate"`, not `"E*a*r*t"`) -- `e`/`E`/`I`
  only resolve to a constant when typed as a standalone name. Calling a
  name this calculator doesn't whitelist, including a wrongly-cased
  built-in such as `"SIN(pi/2)"` (the whitelist is case-sensitive; only
  lowercase `"sin"` is a function) or one of sympy's own internal
  constructors (e.g. `"Integer(2)"`, `"Float(2)"`, `"Rational(1,2)"`,
  `"factorial(5)"` -- none of these are callable by name, even though the
  calculator's own grammar uses them internally for a bare number or
  postfix `!`), answers 400 `{"error": "unknown function '<name>'"}`.
  Input is ASCII-only: a non-ASCII digit, letter, or superscript/subscript
  numeral (e.g. `"２+２"`, `"٣+1"`, `"x²"`) is also a 400, in both a plain
  expression and a `"name:=expr"`/`"f(params):=expr"` definition's own name
  and parameter list. While the result still has a
  free symbol, `decimal` (and `complex`) stay `null` instead of being
  formatted. `mode` accepts only `"rad"` or `"deg"`; any other value is a
  400, same as a missing or non-string `expr` or a syntax error -- never
  a 500.

  ```
  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" \
    -d '{"expr": "1/3+1/6"}'
  # {"expr": "1/3+1/6", "exact": "1/2", "decimal": "0.5", "complex": null, "domain_error": null}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" \
    -d '{"expr": "sqrt(-4)"}'
  # {"expr": "sqrt(-4)", "exact": "2*I", "decimal": null, "complex": {"real": "0", "imag": "2"}, "domain_error": null}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" \
    -d '{"expr": "1/0"}'
  # {"expr": "1/0", "exact": null, "decimal": null, "complex": null, "domain_error": "division by zero"}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" \
    -d '{"expr": "2^100"}'
  # {"expr": "2^100", "exact": "1267650600228229401496703205376", "decimal": "1.26765060023e30", "complex": null, "domain_error": null}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" \
    -d '{"expr": "9^9^9"}'
  # {"expr": "9^9^9", "exact": null, "decimal": null, "complex": null, "domain_error": "result too large to compute"}
  ```

- `GET /api/calc/history` -- 200 `{"history": [...]}`, oldest entry first.
  Every successful `POST /api/calc/evaluate` (no parse error, no
  `domain_error`) appends `{"expr", "exact", "decimal"}` to the history; a
  400 or a `domain_error` result adds nothing.
- `DELETE /api/calc/history` -- clears the history, answers 200
  `{"history": []}`.
- `ans` in an expression (e.g. `"ans*2"`) substitutes the exact value of
  the last history entry. With an empty history -- at startup, or right
  after `DELETE /api/calc/history` -- evaluating `"ans"` answers 400
  `{"error": "ans is undefined"}` instead of treating it as a free
  variable.

  ```
  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" -d '{"expr": "2+3"}'
  # {"expr": "2+3", "exact": "5", "decimal": "5", "complex": null, "domain_error": null}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" -d '{"expr": "ans*2"}'
  # {"expr": "ans*2", "exact": "10", "decimal": "10", "complex": null, "domain_error": null}

  curl -s http://127.0.0.1:8000/api/calc/history
  # {"history": [{"expr": "2+3", "exact": "5", "decimal": "5"}, {"expr": "ans*2", "exact": "10", "decimal": "10"}]}

  curl -s -X DELETE http://127.0.0.1:8000/api/calc/history
  # {"history": []}
  ```

- `"name:=expr"` (e.g. `"a:=5"`) defines a variable: evaluates `expr`,
  stores its exact value under `name`, and answers 200 with the usual
  evaluate shape, `"expr"` set back to the original `"name:=expr"` text.
  `"f(x):=expr"` (or `"f(x,y):=expr"`, one or more comma-separated params)
  defines a function the same way, with `"exact"` set to the body in caret
  form (e.g. `"x^2 + 1"`). Either kind is usable in a later expression --
  `"2a+1"` substitutes `a`'s stored value, `"f(3)"` calls the stored
  function -- the same way `pi` or `ans` already are; calling a function
  with the wrong number of arguments is a 400, never a 500. Redefining a
  reserved constant or function name (`pi`, `e`, `E`, `I`, `i`, `oo`, `nan`,
  `ans`, or a built-in function name) answers 400
  `{"error": "cannot redefine constant <name>"}` and stores nothing --
  `"ans:=5"` (or `"ans(x):=1"`) is rejected the same way, leaving the real
  `ans` (the last plain evaluation's result) and the history both exactly
  as they were. A
  right-hand side that answers a `domain_error` (e.g. `"a:=1/0"`) answers
  200 with that error and also stores nothing. A non-ASCII character
  anywhere in the name or parameter list (e.g. `"x²:=4"`, `"a２:=1"`,
  `"f(x²):=1"`) is likewise rejected with 400 and stores nothing --
  `GET /api/calc/vars` lists none of those names afterward.
- `GET /api/calc/vars` -- 200 `{"variables": {name: exact}, "functions":
  {name: {"params": [...], "body": exact}}}` for everything defined so far,
  values and bodies both in caret form.

  ```
  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" -d '{"expr": "a:=5"}'
  # {"expr": "a:=5", "exact": "5", "decimal": "5", "complex": null, "domain_error": null}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" -d '{"expr": "2a+1"}'
  # {"expr": "2a+1", "exact": "11", "decimal": "11", "complex": null, "domain_error": null}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" -d '{"expr": "f(x):=x^2+1"}'
  # {"expr": "f(x):=x^2+1", "exact": "x^2 + 1", "decimal": null, "complex": null, "domain_error": null}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" -d '{"expr": "f(3)"}'
  # {"expr": "f(3)", "exact": "10", "decimal": "10", "complex": null, "domain_error": null}

  curl -s http://127.0.0.1:8000/api/calc/vars
  # {"variables": {"a": "5"}, "functions": {"f": {"params": ["x"], "body": "x^2 + 1"}}}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" -d '{"expr": "pi:=3"}'
  # {"error": "cannot redefine constant pi"}
  ```

The Calculator tab (`tab-calculator`) is wired to that API, not just a
static mock: `#calc-input` / `#calc-mode` / `#calc-submit` POST to
`/api/calc/evaluate` on click or on Enter in the input, `#calc-history` and
`#calc-vars` refresh from `GET /api/calc/history` and `GET /api/calc/vars`
after every successful submit, and `#calc-error` shows the JSON error's
message on a 400 or a `domain_error` (e.g. `"1/0"` shows `"division by
zero"`). All of it lives in `graphcalc/static/app.js`, using plain `fetch()`
on relative paths -- no build step, no external resources -- and the page
still only draws what those three endpoints return.

## Develop

```
pip install -e . ruff pytest
ruff check --no-cache --select E9,F63,F7,F82,F821 --output-format concise .
python -m pytest -q --tb=short -p no:cacheprovider -rfE --no-header
```

Product specification: [PRODUCT.md](PRODUCT.md). Progress: `.scio/product/progress.json`.
