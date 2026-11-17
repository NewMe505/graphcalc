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

By default (no `--in-memory`), variables, functions, lists and history are
held in memory and written through atomically to a JSON file at `--state
PATH` (default `./graphcalc_state.json`, next to the current directory --
pass an absolute path to pin it elsewhere), which is loaded again on
startup -- `python -m graphcalc --port 8000` then `python -m graphcalc
--port 8000` again (same `--state` path, the default) picks up right where
the previous run left off: a variable defined with `"a:=5"` evaluates to
`"5"` after the restart. The file is rewritten (temp file in the same
directory, then an atomic rename) after every change, so it is always valid
JSON, even if the process is killed mid-write. `--in-memory` disables all
of this: nothing is read or written on disk, and nothing in `--state` has
any effect. A state file that is missing, corrupt, or holds the wrong JSON
shape is never fatal -- the server starts with empty defaults for whichever
fields are unreadable instead of failing to start.

`POST /api/state/reset` -- empties variables, functions, lists and history
(and forgets `ans`) in one call, answering 200 `{"status": "reset"}`; with
`--state` this is a single atomic write, and with `--in-memory` it touches
no file at all.

```
curl -s -X POST http://127.0.0.1:8000/api/state/reset
# {"status": "reset"}
```

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
  sympy's simplified result as a string -- clean for a decimal literal, with
  no precision padding (`"1.5"` gives exact `"1.5"`, `"1e5"` gives exact
  `"100000"`, not sympy's own padded `"1.50000000000000"`/
  `"100000.000000000"`), while a rational result still prints as a fraction
  (`"1/3"` gives exact `"1/3"`, never a decimal). `decimal` is a
  12-significant-digit string with no trailing zeros (e.g. `"1/3"` gives
  `"0.333333333333"`), and `complex`/`domain_error` are `null` unless set.
  Once a value's magnitude
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
    -d '{"expr": "1.5"}'
  # {"expr": "1.5", "exact": "1.5", "decimal": "1.5", "complex": null, "domain_error": null}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" \
    -d '{"expr": "1e5"}'
  # {"expr": "1e5", "exact": "100000", "decimal": "100000", "complex": null, "domain_error": null}

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
  400 or a `domain_error` result adds nothing. A successful `"name:=expr"`
  or `"f(params):=expr"` definition appends to the history too, with the
  same `"expr"`/`"exact"`/`"decimal"` its own evaluate response gave (the
  function case's `"exact"` is the caret-form body, e.g. `"x^2 + 1"`); a
  definition rejected with a 400 (a reserved name, e.g. `"pi:=3"`) adds
  nothing, same as any other 400.
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
  `GET /api/calc/vars` lists none of those names afterward. A successful
  definition -- one that stores a value -- is also appended to
  `GET /api/calc/history`, with the exact `"expr"`/`"exact"`/`"decimal"`
  its own 200 response gave; a rejected (400) definition is not.
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

  curl -s http://127.0.0.1:8000/api/calc/history
  # last two entries: {"expr": "a:=5", "exact": "5", "decimal": "5"},
  # {"expr": "f(x):=x^2+1", "exact": "x^2 + 1", "decimal": null}

  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" -d '{"expr": "pi:=3"}'
  # {"error": "cannot redefine constant pi"} -- not added to the history
  ```

The graphing API is a single endpoint, stateless and also never a 500:
`POST /api/graph/plot`'s body is `{"functions": {"f1".."f4": expr}, "window":
{"xmin","xmax","ymin","ymax"}, "samples": int}`. Each `expr` goes through the
same grammar, no-sympy-constructors whitelist and freeze guard as
`/api/calc/evaluate` (always in radians), with `"x"` bound as the sole free
variable -- it never sees stored variables, functions, or `ans` (an
expression that resolves to a free variable other than `"x"`, e.g. `"a*x"` or
`"ans"`, is a 400, not silently treated as a free symbol or zero). Answers
200 with `{"x": [float, ...], "series": {name: {"color": "#rrggbb", "y":
[float | null, ...]}}}`: `x` is `samples` evenly spaced floats from `xmin` to
`xmax`, both ends included (the last one is pinned to the exact float `xmax`,
not accumulated by repeated addition). Each `y` sample is `null` -- a gap in
the curve, never a 400 or a dropped sample -- whenever that one sample is
non-real (`"sqrt(x)"` at `x=-1`), infinite (`"1/x"` at `x=0`, sympy's own
`zoo`), or `nan`; a function that is unconditionally undefined everywhere
(e.g. `"1/0"`, which never mentions `x` at all) comes back as every sample
`null`, and the request as a whole still answers 200 either way. `ymin`/
`ymax` only bound what a client should draw -- they are validated but never
clip or rescale a `y` value the server returns. `f1` through `f4` each get
one fixed, distinct color from `graphcalc.graph.SERIES_COLORS`: `"#1f77b4"`,
`"#d62728"`, `"#2ca02c"`, `"#9467bd"`. A 400 (`{"error": <message>}`) covers:
a function slot outside `f1`-`f4` (a literal `"f5"`, or a fifth function,
e.g. `"unknown function slot: 'f5'"`), a missing/empty/non-dict `functions`,
a function expression that is not a string, a missing/non-dict `window` or a
missing/non-numeric/non-finite `xmin`/`xmax`/`ymin`/`ymax` (the bare
`Infinity`/`-Infinity`/`NaN` tokens Python's own `json` module otherwise
decodes without error are rejected too), `xmin >= xmax` or `ymin >= ymax`
(e.g. `"window xmin must be less than xmax"`), and a missing/non-int (a bool
does not count) `samples` outside `[2, 10000]`. A parse error or an unknown
function call in an `expr` (the same checks `/api/calc/evaluate` already
makes) is a 400 too, never a 500.

```
curl -s -X POST http://127.0.0.1:8000/api/graph/plot \
  -H "Content-Type: application/json" \
  -d '{"functions": {"f1": "x^2"}, "window": {"xmin": -2, "xmax": 2, "ymin": -1, "ymax": 5}, "samples": 5}'
# {"x": [-2.0, -1.0, 0.0, 1.0, 2.0], "series": {"f1": {"color": "#1f77b4", "y": [4.0, 1.0, 0.0, 1.0, 4.0]}}}

curl -s -X POST http://127.0.0.1:8000/api/graph/plot \
  -H "Content-Type: application/json" \
  -d '{"functions": {"f1": "1/x"}, "window": {"xmin": -1, "xmax": 1, "ymin": -5, "ymax": 5}, "samples": 3}'
# {"x": [-1.0, 0.0, 1.0], "series": {"f1": {"color": "#1f77b4", "y": [-1.0, null, 1.0]}}}

curl -s -X POST http://127.0.0.1:8000/api/graph/plot \
  -H "Content-Type: application/json" \
  -d '{"functions": {"f1": "x", "f2": "x", "f3": "x", "f4": "x", "f5": "x"}, "window": {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}, "samples": 2}'
# {"error": "unknown function slot: 'f5'"}
```

`POST /api/graph/window` turns one window into the next one, stateless --
the server never remembers a "current" window across requests, so the
client sends the window it already has (or none at all) and gets the next
one back. Body `{"action": "zoom_in" | "zoom_out" | "pan" | "standard",
"factor", "dx", "dy", "window"}`. `"standard"` ignores every other key and
always answers the fixed `-10..10` window on both axes. Every other action
defaults `"window"` (when absent or `null`) to that same standard `-10..10`
window, otherwise `"window"` must be an object with finite, non-bool
`xmin`/`xmax`/`ymin`/`ymax` (same rules as `/api/graph/plot`'s own window,
including rejecting `xmin >= xmax` or `ymin >= ymax`). `"zoom_in"`/
`"zoom_out"` need a finite, non-bool, strictly positive `"factor"`, and zoom
about the window's own center: factor 2 halves (`zoom_in`) or doubles
(`zoom_out`) each axis's half-span. `"pan"` needs finite, non-bool `"dx"`
and `"dy"`, added straight onto `xmin`/`xmax` (`dx`) and `ymin`/`ymax`
(`dy`) -- a pure translation, so the window's width and height are
unchanged. Answers 200 with `{"xmin","xmax","ymin","ymax"}` as plain
numbers -- an int when the result is a whole number, a float otherwise
(e.g. zooming `-10..10` in by factor 2 answers `-5`, not `-5.0`). A 400
(`{"error": <message>}`) covers any other `"action"` value, including a
missing one, and the same bad-number rules as above. Never a 500.

```
curl -s -X POST http://127.0.0.1:8000/api/graph/window \
  -H "Content-Type: application/json" \
  -d '{"action": "zoom_in", "factor": 2, "window": {"xmin": -10, "xmax": 10, "ymin": -10, "ymax": 10}}'
# {"xmin": -5, "xmax": 5, "ymin": -5, "ymax": 5}

curl -s -X POST http://127.0.0.1:8000/api/graph/window \
  -H "Content-Type: application/json" \
  -d '{"action": "pan", "dx": 1, "dy": -2}'
# {"xmin": -9, "xmax": 11, "ymin": -12, "ymax": 8} -- window defaults to standard -10..10

curl -s -X POST http://127.0.0.1:8000/api/graph/window \
  -H "Content-Type: application/json" -d '{"action": "sideways"}'
# {"error": "unknown action: 'sideways'"}
```

`POST /api/graph/table` builds a value table for up to four functions, also
stateless. Body `{"functions": {"f1".."f4": expr}, "start", "step", "rows"}`
-- each `expr` goes through the same grammar, whitelist and freeze guard as
`/api/graph/plot`, with `"x"` the sole free variable. Answers 200 with
`{"x": [str, ...], "columns": {name: [str | null, ...]}}`: `"x"` is `rows`
values of `start + index * step` for `index` 0..`rows - 1` -- a plain
arithmetic sequence starting at `start`, unlike `/api/graph/plot`'s evenly-
spaced-between-two-ends `"x"` -- and both `"x"` and every column entry are
12-significant-digit decimal strings, e.g. `{"start": 0, "step": 0.5,
"rows": 3}` gives `x ["0", "0.5", "1"]`. A non-real or undefined sample
(`"sqrt(x)"` at `x=-1`, `"1/x"` at `x=0`) is `null` in that column -- the
same gap rule `/api/graph/plot` already applies -- never a 400 for one bad
sample; the request as a whole still answers 200. A 400
(`{"error": <message>}`) covers the same `functions` validation
`/api/graph/plot` uses (a slot outside `f1`-`f4`, a missing/empty/non-dict
`functions`, a non-string expression), a missing/non-numeric/non-finite
`start` or `step`, `step` equal to `0`, and a missing/non-int (a bool does
not count) `rows` outside `[1, 1000]`. A parse error or an unknown function
call in an `expr` is a 400 too, never a 500.

```
curl -s -X POST http://127.0.0.1:8000/api/graph/table \
  -H "Content-Type: application/json" \
  -d '{"functions": {"f1": "x^2"}, "start": 0, "step": 0.5, "rows": 3}'
# {"x": ["0", "0.5", "1"], "columns": {"f1": ["0", "0.25", "1"]}}

curl -s -X POST http://127.0.0.1:8000/api/graph/table \
  -H "Content-Type: application/json" \
  -d '{"functions": {"f1": "sqrt(x)"}, "start": -1, "step": 1, "rows": 3}'
# {"x": ["-1", "0", "1"], "columns": {"f1": [null, "0", "1"]}}

curl -s -X POST http://127.0.0.1:8000/api/graph/table \
  -H "Content-Type: application/json" \
  -d '{"functions": {"f1": "x"}, "start": 0, "step": 0, "rows": 3}'
# {"error": "step must not be zero"}
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

The Graphs tab (`tab-graphs`) is wired to all four graph endpoints, not just
the static `#graph-canvas` shell. Changing any of `#graph-f1`..`#graph-f4`
or the window inputs `#graph-xmin`/`#graph-xmax`/`#graph-ymin`/`#graph-ymax`
(or pressing Enter in one) POSTs `/api/graph/plot` with only the non-empty
function slots and `samples` set to the canvas's own pixel width (`600`);
the response's series are drawn onto `#graph-canvas` by mapping the window
to pixel coordinates, breaking each series' path wherever its `y` sample is
`null` so a domain gap (e.g. `"1/x"` at `x=0`) is never bridged by a
straight line. The path is also broken between two consecutive *finite*
samples that jump across a vertical asymptote falling between them (bug
#40): a pole such as `1/x`'s `x=0`, `tan(x)`'s `x=pi/2`, or `1/(x-1)`'s
`x=1` is essentially never sampled exactly, so its two neighbouring samples
both come back as large-but-finite numbers of opposite sign, one on each
side -- `app.js`'s `graphIsAsymptoteJump(y0, y1, ymin, ymax)` treats that
jump as a break (never joined with `lineTo`) only when both samples are
finite, they swing from positive to negative (or back), and the swing
exceeds twice the window's own height, so a steep but still continuous
curve such as `"10*x"` stays one unbroken line. An axis is only drawn when
`0` falls inside the window on that axis. With every function slot empty, no plot request is sent -- the
canvas just clears and redraws the axes. `#graph-zoom-in`/`#graph-zoom-out`
POST `/api/graph/window` with `"factor": 2`, and the four pan buttons
(`#graph-pan-left`/`#graph-pan-right`/`#graph-pan-up`/`#graph-pan-down`)
POST it with `"dx"`/`"dy"` set to a quarter of the current window's
width/height; either way the response is written straight back into the
four window inputs before replotting. On load, those same four inputs are
seeded from a real `{"action": "standard"}` call to `/api/graph/window`,
not a hard-coded `-10..10` literal in `app.js`. `#graph-trace-x` plus
`#graph-analyze` POST `{"operation": "value", "f": <first non-empty
function slot>, "x": <trace-x value>}` to `/api/graph/analyze` and show the
result (`"x = ..., y = ..."`) or its `domain_error` in a plain status line
`app.js` creates under the Analyze button at runtime (it has no id of its
own); the same status line also shows a 400 error from any of the four
graph endpoints. After every successful plot, `#graph-table` is rebuilt
automatically (there is no separate button for it) from `/api/graph/table`:
21 rows starting at the window's `xmin`, stepped by `(xmax - xmin) / 20`,
one column per non-empty function slot, with a `null` cell rendered blank. All of it
lives in `graphcalc/static/app.js` too, same plain `fetch()` on relative
paths; every plotted point, window, analysis result and table cell the
Graphs tab shows comes from one of these four endpoints, never computed in
the browser.

A long result, value or error never widens the page: `graphcalc/static/
style.css` sets `overflow-wrap: anywhere` (plus `word-break: break-word` for
older browsers) on `body`, inherited by every tab panel, so an unbroken run
of digits -- `"10^1000"`'s 1,001-digit exact value in `#calc-history`, the
same value stored by `"a:=10^1000"` in `#calc-vars`, a function body such as
`"f(x):=x+10^1000"`, a bad expression long enough to echo into
`#calc-error`, or a long value/error in the Graphs tab's `#graph-table`
cells or its analyze/error status line -- wraps inside its own block instead
of scrolling the whole page sideways. The rule lives on `body`, not on any
one tab's elements, so the Lists & Statistics and CAS tabs get the same
protection for any long text they render later.

## Develop

```
pip install -e . ruff pytest
ruff check --no-cache --select E9,F63,F7,F82,F821 --output-format concise .
python -m pytest -q --tb=short -p no:cacheprovider -rfE --no-header
```

Product specification: [PRODUCT.md](PRODUCT.md). Progress: `.scio/product/progress.json`.
