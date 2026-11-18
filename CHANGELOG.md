# Changelog

## [Unreleased]

## [0.1.0] - 2026-11-18
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

- Function definitions (P7/S2): `"f(x):=expr"` (or `"f(x,y):=expr"`, one or
  more comma-separated params) evaluates `expr` with the params bound as
  plain symbols, stores `{"params", "body"}` under `f`, and answers 200
  with `"exact"` set to the body in caret form (e.g. `"x^2 + 1"`). A later
  call (e.g. `"f(3)"`) evaluates it as a sympy `Lambda`; the wrong number of
  arguments answers 400, never a 500. Redefining a reserved name as a
  function (e.g. `"pi(x):=x"`) is rejected the same way a variable
  redefinition is.

- Listing variables and functions (P7/S3): `GET /api/calc/vars` answers 200
  `{"variables": {name: exact}, "functions": {name: {"params", "body"}}}`
  for everything stored so far, e.g. after `"a:=5"` and `"f(x):=x^2+1"`:
  `{"variables": {"a": "5"}, "functions": {"f": {"params": ["x"], "body":
  "x^2 + 1"}}}`. Both values and bodies are rendered in caret form, same as
  a function definition's own response. Redefining `pi`, `e` or `I` (or any
  other reserved name) is rejected with 400
  `{"error": "cannot redefine constant <name>"}` before anything is
  evaluated or stored, so the constant still evaluates normally afterwards
  and state is left unchanged.

- Calculator tab UI (P8): `GET /` now ships a working Calculator tab, not
  just the static shell. `#calc-input` / `#calc-mode` / `#calc-submit` POST
  `{"expr", "mode"}` to `/api/calc/evaluate` on click or on Enter in the
  input; `#calc-history` and `#calc-vars` are rebuilt from a fresh
  `GET /api/calc/history` and `GET /api/calc/vars` after every successful
  submit (never patched incrementally, so they can't drift from server
  state); `#calc-error` shows the JSON error's message on a 400 or a
  `domain_error`, and is cleared on the next submit. All in
  `graphcalc/static/app.js`, plain `fetch()` on relative paths, no external
  resources; the page still draws only what those three endpoints return.
  Added `tests/test_calc_ui.py`, pinning both acceptance criteria: `GET /`
  contains the six `calc-*` ids, and `GET /static/app.js` mentions the three
  API paths.
- `decimal` (and `complex`'s `real`/`imag`) now switch to scientific
  notation once a value's magnitude needs more than 12 digits before the
  decimal point (P25): `{"expr": "2^100"}` answers decimal
  `"1.26765060023e30"` instead of the literal 31-digit integer rounded to
  12 significant figures and padded out with 19 zeros. The threshold is
  exact: a 12-digit integer (`10**11`) still prints fixed-point
  (`"100000000000"`); a 13-digit one (`10**12`) already switches
  (`"1e12"`). The scientific form keeps the same 12-significant-digit
  precision and trailing-zero stripping as the fixed-point form, now
  applied to the mantissa, with a lowercase `e`, no `+`, and no leading
  zeros in the exponent; a negative value keeps its sign on the mantissa
  (`-2^100` -> `"-1.26765060023e30"`). All in the one shared
  `graphcalc/numfmt.py::format_decimal`, so every current and future
  caller (today, `decimal` and `complex` in `graphcalc/calc.py`) gets the
  same behavior for free. Smaller magnitudes are unaffected. Added
  `tests/test_p25_scientific_notation.py`.
- `"ans"` is now a reserved name (P30, owner revision 2026-11-14):
  `{"expr": "ans:=5"}` answers 400 `{"error": "cannot redefine constant
  ans"}`, same as `"pi:=3"`, and stores nothing -- the history and the real
  `ans` slot (the last plain evaluation's result) are left exactly as they
  were. `{"expr": "ans(x):=1"}` (function-definition syntax) is rejected the
  same way. Concretely: after `{"expr": "2+2"}`, `{"expr": "ans:=5"}` is a
  400 and a following `{"expr": "ans"}` still answers exact `"4"`, never
  `"5"`. `graphcalc/names.py`'s `RESERVED_NAMES` now includes `"ans"`
  alongside `graphcalc.calc._rad_names()` and `{"i", "oo", "nan"}`, so the
  existing `check_not_constant("ans")` call every other
  `"name:=expr"`/`"f(params):=expr"` definition already goes through
  rejects it before any evaluation or storage happens. Added
  `tests/test_p30_ans_reserved.py`.
- A decimal literal's `exact` is now clean (P31, owner revision
  2026-11-14): `{"expr": "1.5"}` answers exact `"1.5"` and decimal `"1.5"`;
  `{"expr": "1e5"}` answers exact `"100000"` instead of sympy's own
  precision-padded `str(Float)` (`"1.50000000000000"`,
  `"100000.000000000"`). New `graphcalc/numfmt.py::clean_float_exact(value)`
  strips the trailing fractional zeros (and the trailing `"."` for an
  integral value) from a sympy `Float`'s `str()`; `graphcalc/calc.py`'s
  `evaluate` calls it for `exact` only when the result is actually a
  `Float` -- a `Rational` (`{"expr": "1/3"}` still answers exact `"1/3"`,
  never a decimal), an `Integer` (`10**1000` still answers exact as the
  full 1001-digit integer and decimal `"1e1000"`, P25 unaffected), or a
  symbolic result all keep plain `str(result)` exactly as before. Added
  `tests/test_p31_clean_decimal_exact.py`; updated
  `tests/test_evaluate_grammar.py`'s `.5x`/`2*.5` cases, which now assert
  the clean `"2"`/`"1"` instead of the previously-padded
  `"2.00000000000000"`/`"1.00000000000000"`.
- A successful variable or function definition is now added to the history
  (P32, owner revision 2026-11-14): after `{"expr": "a:=5"}` and then
  `{"expr": "f(x):=x^2+1"}`, the last two entries of
  `GET /api/calc/history` are `{"expr": "a:=5", "exact": "5", "decimal":
  "5"}` and `{"expr": "f(x):=x^2+1", "exact": "x^2 + 1", "decimal": null}`
  -- each the same `"exact"`/`"decimal"` its own evaluate response gave (a
  function's `"exact"` is the caret-form body, matching the response, never
  the stored `"**"` form). A definition rejected with a 400, such as
  `{"expr": "pi:=3"}` (a reserved name) or a right-hand side with a
  `domain_error` (e.g. `{"expr": "a:=1/0"}`), adds nothing to the history,
  same rule a plain `evaluate()` failure already followed; `"ans"` is
  unaffected, since it is only ever set from a plain evaluation (P26/S1,
  P30), never a definition's right-hand side. Added
  `tests/test_p32_definitions_in_history.py`.
- Disk-persisted state (P9): variables, functions, lists (an empty `{}` for
  now -- P15 adds CRUD for named lists) and history are held in memory and
  written through atomically to a JSON file at `--state PATH` (default
  `./graphcalc_state.json`), which is loaded again on startup -- after
  `{"expr": "a:=5"}` with `--state S`, restarting the server with the same
  `--state S` and evaluating `{"expr": "a"}` answers exact `"5"`. Each write
  is a temp file in the state file's own directory followed by an atomic
  `os.replace`, so the file parses as valid JSON after every change, even if
  the process is killed mid-write. `--in-memory` disables all of this: no
  file is ever read or written, and `--state` has no effect. New `POST
  /api/state/reset` empties variables, functions, lists and history (and
  forgets `ans`) in one call, answering 200 `{"status": "reset"}` -- one
  atomic write with `--state`, no file at all with `--in-memory`. History
  moved behind a new `graphcalc.history.StateBackedHistoryStore`, so one
  JSON file now backs both variables/functions and history; `--in-memory`
  still uses the existing plain `InMemoryHistoryStore`. Bug #14 (load-time):
  a state file that is missing, unreadable, not valid JSON, or has the
  wrong JSON shape at the top level or for any individual field (e.g.
  `"variables"` hand-edited into a string) never raises on load -- the
  affected field(s) simply fall back to their empty default, so a corrupt
  state file can never break evaluation; a load failure also never writes,
  so the corrupt file is left alone until the next real change overwrites
  it with a valid one. `.gitignore` now lists `graphcalc_state.json`. Added
  `graphcalc/state.py`'s file I/O (`CalcState`), `graphcalc.history.
  StateBackedHistoryStore`, and `tests/test_p9_state_persistence.py`
  (restarts a real server subprocess on the same `--state` path).
- `POST /api/graph/plot` (P10): samples up to four functions (`"f1"`..`"f4"`)
  over a window. Body `{"functions": {"f1".."f4": expr}, "window":
  {"xmin","xmax","ymin","ymax"}, "samples": int}` answers 200 `{"x": [float,
  ...], "series": {name: {"color": "#rrggbb", "y": [float | null, ...]}}}`:
  `x` is `samples` evenly spaced floats from `xmin` to `xmax` inclusive (the
  last one pinned to the exact float `xmax`, never accumulated by repeated
  addition). Each `y` sample is `null` -- a gap in the curve, status still
  200 -- whenever that sample is non-real (`"sqrt(x)"` at `x=-1`), infinite
  (`"1/x"` at `x=0`, sympy's own `zoo`), or `nan`; a function that is
  unconditionally undefined everywhere (e.g. `"1/0"`) comes back as every
  sample `null`. `f1`-`f4` each get one fixed, distinct color from new
  `graphcalc.graph.SERIES_COLORS` (`"#1f77b4"`, `"#d62728"`, `"#2ca02c"`,
  `"#9467bd"`). Reuses `graphcalc.calc.evaluate()` for parsing each
  expression, with `"x"` bound as the sole free variable -- the same
  grammar, no-sympy-constructors whitelist and `is_power_too_large` freeze
  guard `/api/calc/evaluate` already enforces apply here too, and
  `graphcalc.calc.CalcError` (bad syntax, an unknown function call, an
  oversized power) escapes `graph.plot()` unchanged and is a 400 here as
  well, not just the new `graphcalc.graph.GraphError`. 400 also covers: a
  function slot outside `f1`-`f4` (a literal `"f5"`, or a fifth function), a
  missing/empty/non-dict `functions`, a non-string function expression, a
  missing/non-dict `window` or a missing/non-numeric/non-finite `xmin`/
  `xmax`/`ymin`/`ymax` (`Infinity`/`-Infinity`/`NaN`, which Python's own
  `json` module otherwise decodes without error, are rejected too),
  `xmin >= xmax` or `ymin >= ymax`, a missing/non-int (bool excluded)
  `samples` outside `[2, 10000]`, and a function expression mentioning a
  free variable other than `"x"` (e.g. `"a*x"`, `"ans"`). Never a 500.
  Stateless -- unlike `/api/calc/evaluate`, it never reads or writes the
  server's stored variables, functions, `ans`, or history. Added
  `graphcalc/graph.py` (`plot`, `GraphError`, `SERIES_COLORS`,
  `MIN_SAMPLES`/`MAX_SAMPLES`) and `tests/test_p10_graph_plot.py`.
- `POST /api/graph/window` (P11): turns one window into the next, also
  stateless -- the server never remembers a "current" window across
  requests. Body `{"action": "zoom_in" | "zoom_out" | "pan" | "standard",
  "factor", "dx", "dy", "window"}` answers 200 `{"xmin","xmax","ymin",
  "ymax"}` as plain numbers (an int when the result is a whole number, a
  float otherwise, e.g. zooming `-10..10` in by factor 2 answers `-5`, not
  `-5.0`). `"standard"` ignores every other key and always answers the
  fixed `-10..10` window on both axes. Every other action defaults
  `"window"` (absent or `null`) to that same standard `-10..10` window,
  otherwise `"window"` must be an object with finite, non-bool `xmin`/
  `xmax`/`ymin`/`ymax` and `xmin < xmax`/`ymin < ymax`, the same rules
  `/api/graph/plot` enforces on its own window. `"zoom_in"`/`"zoom_out"`
  need a finite, non-bool, strictly positive `"factor"`, and zoom about the
  window's own center: factor 2 halves (`zoom_in`, `-10..10` -> `-5..5`) or
  doubles (`zoom_out`, `-10..10` -> `-20..20`) each axis's half-span,
  recentered on the unchanged midpoint. `"pan"` needs finite, non-bool
  `"dx"`/`"dy"`, added straight onto `xmin`/`xmax` (`dx`) and `ymin`/`ymax`
  (`dy`) -- a pure translation, so the window's width and height are
  unchanged (`{"action":"pan","dx":1,"dy":-2}` on the standard window ->
  `{"xmin":-9,"xmax":11,"ymin":-12,"ymax":8}`). Any other `"action"`,
  including a missing one, is a 400 (`{"error": "unknown action: ..."}`),
  same as a bad factor/dx/dy/window. Never a 500. Added
  `graphcalc.graph.window` and `tests/test_p11_graph_window.py`.
- `POST /api/graph/analyze` (P12/S1): `"value"` and `"zero"`, plus the
  request validation shared by every operation (`"minimum"`, `"maximum"`
  and `"intersection"` are validated here but not computed until a later
  step). Body `{"operation": "value"|"zero"|"minimum"|"maximum"|
  "intersection", "f", "g" (`"intersection"` only), "x" (`"value"` only),
  "lower", "upper" (every other operation)}` answers 200 `{"operation",
  "x", "y", "domain_error"}`, with `x`/`y` each a 12-significant-digit
  decimal string (`graphcalc.numfmt.format_decimal`) or `null`. `"value"`
  substitutes `x` into `f` (`"x^2+1"` at `x=3` -> `x "3"`, `y "10"`); a
  gap (e.g. `"1/x"` at `x=0`) answers 200 with `y` `null` and a
  `domain_error` instead, `x` still formatted. `"zero"` scans
  `[lower, upper]` for a sign change or a near-zero sample, refines it by
  bisection, and snaps the result to an exact value with sympy
  `nsimplify` when one still solves the equation within tolerance
  (`"x^2-4"` on `[0,5]` -> `x "2"`, `y "0"`); no root in the interval
  answers 200 with `x`/`y` both `null` and `domain_error`
  `"no zero in interval"` -- not a 400. `f` (and `g`) are parsed with
  `graphcalc.calc.evaluate()`, same as `/api/graph/plot`, so
  `graphcalc.calc.CalcError` escapes unchanged and is a 400 here too, not
  just the new `graphcalc.graph.GraphError`. 400 also covers: an unknown
  `operation`, a missing/non-string `f` (or `g`, for `"intersection"`), a
  missing/non-numeric/non-finite `x` (`"value"`) or `lower`/`upper`
  (every other operation), and `lower >= upper`. Never a 500. Added
  `graphcalc.graph.analyze` (plus `GraphError`, `DOMAIN_ERROR_NO_ZERO`,
  `DOMAIN_ERROR_NO_VALUE`, `ANALYZE_OPERATIONS`), `graphcalc.cli.
  _handle_graph_analyze`, and `tests/test_p12_graph_analyze.py`.
- `POST /api/graph/table` (P13/S1): a value table for up to four functions,
  stateless like `/api/graph/plot`, `/api/graph/window` and
  `/api/graph/analyze`. Body `{"functions": {"f1".."f4": expr}, "start",
  "step", "rows"}` answers 200 `{"x": [str, ...], "columns": {name: [str |
  null, ...]}}`: `"x"` is `rows` values of `start + index * step` -- a plain
  arithmetic sequence, not `/api/graph/plot`'s evenly-spaced-between-two-ends
  `"x"` -- and both `"x"` and every column entry are
  `graphcalc.numfmt.format_decimal` strings (12 significant digits), e.g.
  `{"functions": {"f1": "x^2"}, "start": 0, "step": 0.5, "rows": 3}` ->
  `x ["0", "0.5", "1"]`, `columns.f1 ["0", "0.25", "1"]`. A non-real or
  undefined sample (`"sqrt(x)"` at `x=-1`, `"1/x"` at `x=0`) is `null` in
  that column -- the same gap rule `/api/graph/plot`/`/api/graph/analyze`
  already apply -- never a 400 for one bad sample; the request as a whole
  still answers 200. Each function is parsed with the same
  `_parse_function`/`_evaluate_at` pair `/api/graph/plot` samples with, so
  `graphcalc.calc.CalcError` (bad syntax, an unknown function call, an
  oversized power) is a 400 here too, not just the new
  `graphcalc.graph.GraphError`. 400 also covers: `/api/graph/plot`'s own
  `functions` validation (a slot outside `f1`-`f4`, a missing/empty/non-dict
  `functions`, a non-string expression), a missing/non-numeric/non-finite
  `start` or `step`, `step` equal to `0` (would otherwise repeat `start`
  forever without advancing the table), and a missing/non-int (a bool does
  not count) `rows` outside `[1, 1000]` (`MIN_ROWS`/`MAX_ROWS`). Never a 500.
  Added `graphcalc.graph.table` (plus `MIN_ROWS`/`MAX_ROWS`),
  `graphcalc.cli._handle_graph_table`, and `tests/test_p13_graph_table.py`.
- Graphs tab UI (P14): `GET /` now ships a working Graphs tab, not just the
  static `graph-canvas` shell. `graphcalc/static/index.html` gains 17 new
  ids inside `tab-graphs`: `graph-f1`..`graph-f4`, the window inputs
  `graph-xmin`/`graph-xmax`/`graph-ymin`/`graph-ymax`, `graph-zoom-in`/
  `graph-zoom-out`, the four pan buttons `graph-pan-left`/`graph-pan-right`/
  `graph-pan-up`/`graph-pan-down`, `graph-trace-x`, `graph-analyze`, and a
  new `graph-table` `<table>`. `graphcalc/static/app.js` wires all four
  graph endpoints: a `change` on any function/window input (or Enter in
  one) POSTs `/api/graph/plot` with only the non-empty `f1`-`f4` slots and
  `samples` set to the canvas's own pixel width, then draws each returned
  series onto `graph-canvas` by mapping the window to pixel coordinates and
  breaking the path wherever that series' `y` sample is `null`, so a domain
  gap is never bridged by a straight line; the zoom/pan buttons POST
  `/api/graph/window` (`zoom_in`/`zoom_out` at factor 2, `pan` by a quarter
  of the current window's width/height) and write the response straight
  back into the window inputs before replotting; those same inputs are
  seeded on load from a real `{"action": "standard"}` call rather than a
  hard-coded `-10..10` literal; `graph-trace-x` plus `graph-analyze` POST
  `{"operation": "value", "f": <first non-empty function slot>, "x":
  <trace-x value>}` to `/api/graph/analyze` and show the result or its
  `domain_error` in a plain status line `app.js` creates under the Analyze
  button (no id of its own); and after every successful plot, `graph-table`
  is rebuilt automatically, with no separate button, from
  `/api/graph/table` (21 rows from `xmin`, step `(xmax - xmin) / 20`, one
  column per non-empty function slot, a `null` cell rendered blank). A 400
  from any of the four endpoints shows its `error` message in that same
  status line. The Calculator tab's own ids and wiring are unchanged. Added
  `tests/test_p14_graphs_ui.py`, pinning both acceptance criteria: `GET /`
  contains each of those 17 ids exactly once (and `graph-canvas`, added in
  an earlier step, is still a `<canvas>`) and `GET /static/app.js` mentions
  the four `/api/graph/*` paths.
- Named lists (P15/S1): `GET /api/lists` -> `{"lists": [sorted names]}`;
  `GET /api/lists/<name>` -> `{"name","values"}` or a 404 JSON error;
  `PUT /api/lists/<name> {"values": [...]}` -> 200, upserting the list
  (overwrites any existing list under the same name); `DELETE
  /api/lists/<name>` -> 200 `{"deleted": name}` or a 404. A list name must
  fully match `[A-Za-z][A-Za-z0-9_]{0,15}`; `"values"` must be a non-empty,
  non-oversized JSON array of strings, each checked with the same
  `graphcalc.calc.evaluate` every `/api/calc/evaluate` request already goes
  through (so a value such as `"abc+"` is a 400, same message as a bare
  expression would get) -- stored as the original strings, never the
  evaluated result, so a stored list can never break a later evaluation
  (P26). A malformed name, body, or values entry is always a 400, never a
  500; 404 is reserved for a well-formed name that is simply not a stored
  list. Lists live in the same on-disk state file as variables/functions
  (the `"lists"` key P9 already reserved for this): they survive a restart
  with the same `--state`, and `POST /api/state/reset` empties them along
  with everything else. Added `graphcalc/lists.py`
  (`LIST_NAME_RE`/`validate_list_name`/`validate_list_values`),
  `CalcState.get_list`/`set_list`/`delete_list` in `graphcalc/state.py`,
  `do_PUT` plus the four `_handle_lists_*` handlers in `graphcalc/cli.py`,
  and `tests/test_p15_lists.py`.
- Named lists survive a restart and `POST /api/state/reset` (P15/S2):
  `CalcState`'s on-disk loader now validates the `"lists"` field entry by
  entry, not just as a whole -- any name not matching `LIST_NAME_RE`, any
  value that is not a list, or any list containing a non-string item is
  dropped on load instead of being resurfaced through `GET /api/lists` or
  crashing a later evaluation (extending P26's "stored data never breaks
  later evaluations" rule to a hand-edited or pre-P15 state file). CRUD
  through `/api/lists` already wrote through atomically and `reset()`
  already emptied `"lists"` since P9, so no further change was needed for
  a list to survive `python -m graphcalc --state S` being stopped and
  started again, or to be emptied by `POST /api/state/reset`.
- Lists in expressions (P15/S3): `POST /api/calc/evaluate` now resolves a
  stored list by name -- with `L1` set to `["1","2","3"]` via `PUT
  /api/lists/L1`, `{"expr": "2*L1+1"}` answers 200 `exact` `"[3, 5, 7]"`.
  Any expression that references, as a whole token, at least one stored
  list name is evaluated elementwise instead of as a single scalar; a
  plain number or a stored variable/function that is not itself one of
  the referenced lists broadcasts across every index, and two lists used
  together must share the same length or the request is a 400 (`"lists
  have mismatched lengths: ..."`). The first element whose own evaluation
  hits a `domain_error` short-circuits the whole result into that one
  `domain_error`, the same shape a plain scalar domain error already has;
  `decimal` and `complex` are always `null` for a list result, since
  neither has a single rendering for a list, and referencing `ans` right
  after leaves it undefined, the same as with no history at all. An
  expression that references no stored list name behaves exactly as
  before. `graphcalc/calc.py`'s `evaluate()` gained a `lists` parameter
  (new `_evaluate_list_expression`/`_list_lengths_or_raise` helpers), and
  `graphcalc/cli.py`'s calc-evaluate handler now passes
  `lists=_state(handler).lists()` into every call.
- `POST /api/stats/regression` (P17): least-squares curve fit for `x`/`y`
  data sent directly in the request body. Body `{"model":
  "linear"|"quadratic", "x": [str], "y": [str]}` answers 200 with
  `{"model", "coefficients": {"a","b"[,"c"]}, "r2", "points": [[x,y], ...],
  "curve": [[x,y], ...]}`: `"linear"` solves `y = a*x + b` and `"quadratic"`
  solves `y = a*x**2 + b*x + c`, each from the exact least-squares normal
  equations (`graphcalc/stats.py`'s new `_fit_linear`/`_fit_quadratic`, via
  `sympy.Matrix.solve()` for the quadratic 3x3 system) over exact
  Rational/Integer arithmetic, never a float. Every coefficient, `r2`, and
  every `"points"`/`"curve"` number is a 12-significant-digit decimal
  string with a clean `"0"` rather than `"-0"` or `"1e-16"` for an exact
  fit (e.g. `x [1,2,3]`, `y [2,4,6]` answers `a "2"`, `b "0"`, `r2 "1"`).
  `"points"` echoes the request's own `(x, y)` pairs in their original
  order (not sorted); `"curve"` holds 50 points evenly spaced across the
  data's own `min(x)..max(x)` (both endpoints exact), each paired with the
  fit's predicted `y`. An unrecognized `"model"`, a malformed/empty/
  oversized `"x"`/`"y"` (reusing `graphcalc.lists.validate_list_values`), a
  non-string or non-numeric entry, mismatched `"x"`/`"y"` lengths, too few
  distinct x values for the model (fewer than 2 for `"linear"`, fewer than
  3 for `"quadratic"`), or every `y` value equal (`r2` undefined) each
  answer 400, never a 500. Added `tests/test_p17_regression.py`.
- Lists & Statistics tab UI (P18): `GET /` now ships a working Lists &
  Statistics tab, not just the static shell. `graphcalc/static/index.html`
  gains nine new ids inside `tab-lists`: `list-grid`, `stats-list`,
  `stats-output`, `regression-model` (a `<select>` defaulting to
  `"linear"`, with `"quadratic"` as the other option), `regression-x`,
  `regression-y`, `regression-run`, `regression-output`, and a new
  600x400 `stats-canvas` `<canvas>`. `graphcalc/static/app.js` wires all
  three endpoints: `loadLists()` runs on page load and on every click of
  the Lists & Statistics tab button, fetching `GET /api/lists` then one
  `GET /api/lists/<name>` per name in parallel to fill `list-grid` (each
  list's own heading plus its values) and the `stats-list`/`regression-x`/
  `regression-y` selects, keeping a still-valid prior selection; a
  `change` on `stats-list` POSTs `{"list": name}` to `/api/stats/onevar`
  and renders every returned key as a `<dt>`/`<dd>` pair in `stats-output`
  (an `{"exact","decimal"}` pair collapses to just `exact` when the two
  match, e.g. `mean` shows `3`, not `3 = 3`); `regression-run` POSTs
  `regression-model`'s value plus the chosen `regression-x`/`regression-y`
  lists' own *values* (not their names) to `/api/stats/regression` and
  renders `model`/each coefficient/`r2` as `"key = value"` lines in
  `regression-output` (e.g. `a = 2`, `b = 0`), then draws the response's
  `points` (dots) and `curve` (one connected line) on `stats-canvas`, with
  the drawing window fit client-side to their combined min/max plus a 10%
  margin. A 400 from either `/api/stats/onevar` or `/api/stats/regression`
  shows its `error` message in the matching output element instead. The
  Calculator and Graphs tabs' own ids and wiring are unchanged. Added
  `tests/test_p18_lists_ui.py` (both static-content acceptance criteria:
  the nine required ids, with `stats-canvas` confirmed as an actual
  `<canvas>`, and `GET /static/app.js` mentioning all three
  `/api/lists`/`/api/stats/*` paths) and `tests/test_p18_lists_browser.py`
  (real-Chromium, Playwright-driven: F3 -- `L1 [1,2,3,4,5]` appears in
  `list-grid` and choosing it in `stats-list` shows `n 5`/`mean 3` in
  `stats-output` -- and F4 -- a linear regression of `L2 [2,4,6]` on
  `L1 [1,2,3]` shows `a = 2`/`b = 0` in `regression-output` and leaves at
  least one non-blank pixel on `stats-canvas`; skips, never fails, without
  Playwright/Chromium).
- `POST /api/cas/simplify`, `/api/cas/expand` and `/api/cas/factor` (P19):
  stateless CAS algebra over sympy. Each takes body `{"expr": str}` and
  answers 200 with `{"result": str}`: `/simplify` runs `sympy.simplify()`
  (`"(x^2-1)/(x-1)"` -> `"x + 1"`), `/expand` runs `sympy.expand()`
  (`"(x+1)^2"` -> `"x^2 + 2*x + 1"`), and `/factor` runs `sympy.factor()`
  (`"x^2-5x+6"` -> `"(x - 3)*(x - 2)"`). `expr` is parsed with the same
  restricted grammar `POST /api/calc/evaluate` uses (`graphcalc.grammar.
  check_grammar`/`normalize_numbers`, the same `rad`-mode name whitelist
  for calls, implicit multiplication), so an undefined name such as `x`
  becomes a free symbol and every result renders with `^` for a power,
  never sympy's own `**`. Unlike `/api/calc/evaluate`, these routes read
  no stored ans/variables/functions/lists and have no `rad`/`deg` mode --
  a CAS request carries no state at all. A missing/empty/non-string
  `"expr"`, a non-object body, invalid JSON, or anything the parser itself
  rejects (bad grammar, an unknown function call, a dangling operator such
  as `"x+"`) answers 400 with a JSON `{"error": ...}`, never a 500. Added
  `graphcalc/cas.py` and `tests/test_p19_cas.py`.
- `POST /api/cas/derivative`, `/api/cas/integral` and `/api/cas/limit`
  (P20): the rest of the CAS calculus set, next to P19's algebra routes in
  `graphcalc/cas.py`. `/derivative` takes `{"expr", "var"}` and runs
  `sympy.diff()` (`"x*sin(x)"` by `"x"` -> `"x*cos(x) + sin(x)"`).
  `/integral` takes `{"expr", "var"}` plus optional `"lower"`/`"upper"`:
  with neither, the indefinite integral (`"x^2"` by `"x"` ->  `"x^3/3"`);
  with both, the definite one (`0`/`1` -> `"1/3"`); supplying only one of
  the two is a 400, and an integral sympy cannot find a closed form for
  answers 400 `"no closed form"` rather than echoing the input back.
  `/limit` takes `{"expr", "var", "point"}` plus optional `"dir"`: with no
  `"dir"`, sympy's own two-sided `dir="+-"` (`"sin(x)/x"` at `0` -> `"1"`);
  `"+"`/`"-"` for a one-sided limit (`"1/x"` at `0` with `"+"` -> `"oo"`);
  any other `"dir"` (including a non-string) is a 400 before `"expr"` is
  even parsed. A limit sympy cannot resolve -- it raises (the two one-sided
  limits disagree) or hands back its own `zoo`/`nan` instead of a value
  (the two-sided limit of `"1/x"` at `0`) -- is also a 400, never a 200
  echoing an undefined result. `"var"` must be a plain ASCII identifier
  string for all three routes. `"lower"`/`"upper"`/`"point"` each accept
  either a JSON number (bool and non-finite float rejected) or an
  expression string such as `"pi"` or `"oo"`/`"-oo"` (`"infinity"`/
  `"-infinity"` also work) -- `"oo"`/`"-oo"` map straight to sympy's own
  infinity, any other string is parsed with the same grammar/whitelist
  `"expr"` itself uses and must come back with no free symbols (so `"pi"`
  and `"2*pi"` work, `"y"` and a malformed string such as `"x+"` are both
  400s), letting `integral("sin(x)", "x", 0, "pi")` -> `"2"` and
  `limit("1/x", "x", "oo")` -> `"0"` both work. The P20/S1 power-size guard
  (`graphcalc.limits.is_power_too_large`, the same "guard against hangs, as
  in P28" fix) runs inside the shared `_parse`, so it also covers every
  bound string, not just `"expr"`. Added
  `tests/test_p20_cas_calculus.py`.
- `POST /api/cas/solve` (P21): takes `{"equation", "var"}` and answers
  `{"solutions": [str, ...]}`, a sorted list of exact "^"-notation
  solution strings, next to P19/P20's other CAS routes in
  `graphcalc/cas.py`. `"equation"` is split on a single `"="` (zero `"="`
  means the whole string is taken to equal `0`; more than one, e.g.
  `"x=y=2"`, is a 400) and `sympy.solve()` runs against `lhs - rhs`:
  `"x^2=4"` for `"x"` -> `["-2", "2"]`; `"x^2+1"` for `"x"` ->
  `["-I", "I"]` (sympy already finds complex roots with no extra domain
  hint); `"2y+3=7"` for `"y"` -> `["2"]`. `"var"` must be a plain ASCII
  identifier string, the same rule `/derivative`, `/integral` and
  `/limit` already apply; a missing or non-string `"var"` (or
  `"equation"`) is a 400, never a 500. Added
  `tests/test_p21_cas_solve.py`.

### Security
- Hardened the `/static/<name>` route against path traversal: reject a NUL
  byte, a backslash or an absolute segment in the decoded name outright, and
  require the resolved path to stay inside `STATIC_DIR.resolve()`. Unknown
  routes (e.g. `/server.py`) keep answering a JSON 404, never a 500.

### Changed
- State file format (P26): the on-disk state JSON gains two top-level maps,
  `"variable_sreprs"` (name -> sympy `srepr()` string, or `null`) and
  `"function_sreprs"` (name -> body's `srepr()` string, or `null`),
  alongside the existing `"variables"` and `"functions"`; a stored "ans" is
  now `{"exact": str, "srepr": str}` instead of a plain string. A state file
  written before this change (or hand-edited) simply has `null`/absent
  srepr(s) for every name and still loads cleanly -- see "Fixed" below for
  why srepr exists at all. `CalcState.variables()`/`.functions()` (what
  `GET /api/calc/vars` reads) are unchanged; the new srepr maps are only
  ever read back through the new `variable_entries()`/`function_entries()`.

### Fixed
- Bug #14 (P26): a stored "ans", variable, or function can no longer break
  a later, unrelated evaluation. Before this fix, a stored value was always
  rebuilt by plain `sympify()` of its exact-value string -- sympy's own full
  namespace, not this calculator's restricted whitelist -- so a value built
  from a name this calculator deliberately never whitelists (`"beta"`,
  `"gamma"`, `"zeta"`, `"S"`, `"N"`, `"Q"`: each a real sympy
  function/singleton, not just a free symbol, in sympy's own namespace)
  could fail to rebuild; for "ans" specifically, that rebuild ran on *every*
  evaluation regardless of whether the expression mentioned "ans" at all, so
  `{"expr":"beta+1"}` followed by the unrelated `{"expr":"1+1"}` could
  answer 400 instead of 200. Now: `{"expr":"a:=beta+1"}` or
  `{"expr":"f(x):=beta(x)"}` followed by `{"expr":"1+1"}` always answers 200
  `"2"`, and `{"expr":"ans"}` after `{"expr":"gamma"}`, `{"expr":"S"}`,
  `{"expr":"N"}` or `{"expr":"Q"}` always answers 200 with that same exact
  string back. Every stored variable's value and function's body is now
  also persisted as its sympy `srepr()` (see "Changed" below), rebuilt from
  that instead of a plain, ambiguous `sympify()` of the exact string
  whenever one is available; and a stored name's value or body is only ever
  rebuilt at all when an expression actually references that name, so an
  unrebuildable definition (one with no srepr -- stored before this fix, or
  loaded from a hand-edited file) can still only ever break a request that
  uses it, never an unrelated one like `"1+1"`.
- Bug #5 (P23): `POST /api/calc/evaluate` (and the `name:=expr`/
  `f(x):=expr` definition paths) now accept only this calculator's own
  grammar, via a new pre-parse gate, `graphcalc/grammar.py`. Before this
  fix, sympy's `parse_expr` -- built on Python's own tokenizer -- silently
  accepted Python syntax outside the calculator's grammar. Every one of the
  following now answers 400 with a JSON error instead of a Python-semantics
  result: the comparison operators `< > <= >= == !=`, `%`, `//`, the
  bitwise/shift operators `& | ~ << >>`; the Python-only numeric literals
  `0x10`, `0b11`, `0o7`, `1_000`, `2j`, `3J`; and an extra argument to a
  built-in one-argument function, e.g. `ln(e,2)` or `sqrt(4,2)` (sympy's own
  two-argument `log(x, base)` previously let that through even though this
  calculator's `ln`/`sqrt`/etc. are always one-argument). Postfix `!`
  (`5!` -> `120`), top-level `name:=expr` definitions, implied
  multiplication (`2x`, `2(x+1)`), and a multi-argument call to a
  user-defined function all keep working exactly as before.
- Bug #7 (P24): a multi-letter identifier is now always one name, as on the
  TI-Nspire CAS, never split into letters. Before this fix,
  `graphcalc/calc.py` built its parser on sympy's bundled
  `implicit_multiplication_application`, whose `split_symbols` step broke
  any name not already known into one symbol per letter and re-resolved
  each letter against the whitelist on its own -- so `{"expr": "rate"}`
  evaluated to exact `"E*a*r*t"` (its `"e"` silently became the constant
  `E`), `{"expr": "sec"}` to `"E*c*s"`, `{"expr": "deg"}` to `"E*d*g"`, and
  `{"expr": "SIN(pi/2)"}` to `"I*pi*N*S/2"`. `_TRANSFORMATIONS` now uses
  `implicit_multiplication` + `implicit_application` +
  `function_exponentiation` instead, with `split_symbols` dropped entirely:
  a run of letters/digits/underscores -- the same token
  `graphcalc/grammar.py`'s tokenizer already reads as one `IDENT` -- parses
  as exactly one `Symbol` unless it is a whitelisted constant/function or a
  stored variable/function. `{"expr": "rate"}` now answers exact `"rate"`
  (decimal `null`), and `{"expr": "xy"}`, `{"expr": "sec"}`, `{"expr":
  "deg"}` and `{"expr": "rate*2"}` each answer an exact with no stray `E`
  or `I` anywhere in it. Calling a name this calculator doesn't whitelist
  with `(...)`, including a wrongly-cased built-in (`{"expr":
  "SIN(pi/2)"}`, versus the whitelisted lowercase `sin`) or a real sympy
  name this calculator never whitelisted (`zeta(2)`), now answers 400
  `{"error": "unknown function '<name>'"}` instead of silently falling
  back to an implicit product between an unresolved symbol and the
  argument list. Implied multiplication by a number (`"2x"` -> `"2*x"`,
  `"2pi"` -> `"2*pi"`, `"2sin(pi/6)"` -> `"1"`) and `e`/`E`/`I` as
  standalone names still resolve exactly as before. New
  `graphcalc/grammar.py::called_names()`, sharing P23's tokenizer, finds
  every name immediately followed by `"("` so `calc.evaluate` can check it
  against its whitelist before `parse_expr` ever runs.
- Bug #21 (P27): `POST /api/calc/evaluate` no longer lets a user call one of
  sympy's internal constructors by name. Before this fix, `calc.evaluate`'s
  "unknown function" check (Bug #7's `called_names(expr)` scan) let a call
  through whenever the name was a key of `_GLOBAL_DICT` -- the small set of
  constructors (`Integer`, `Float`, `Rational`, `Symbol`, `Function`,
  `factorial`) `parse_expr`'s own transformations need to emit internally
  from a generated AST node, never meant to be reachable by name from
  user-typed text -- so `{"expr":"Integer(2)"}`, `{"expr":"Float(2)"}`,
  `{"expr":"Rational(1,2)"}` and `{"expr":"factorial(5)"}` each evaluated
  successfully instead of being rejected. Each now answers 400 with a JSON
  `"error"`. The check now only accepts a called name already in
  `local_dict` (the rad/deg whitelist, a stored variable or function, a
  function definition's own param, or "ans"), regardless of whether it is
  also a `_GLOBAL_DICT` key; `_GLOBAL_DICT` itself is unchanged, still
  reachable only via a transformation-generated node, never via literal
  user text -- `{"expr":"5!"}` still answers exact `"120"` and
  `{"expr":"1/3+1/6"}` still answers exact `"1/2"`.
- Bug #21 (P27, continued): a non-ASCII digit, letter, or
  superscript/subscript numeral now answers 400 instead of being silently
  accepted by Python's own Unicode-aware `\w`/`\d` -- `{"expr":"２+２"}`
  (fullwidth digits), `{"expr":"٣+1"}` (an Arabic-indic digit) and
  `{"expr":"x²"}` (an ASCII letter immediately followed by a superscript
  two) each now answer 400 with a JSON `"error"` instead of evaluating.
  The same rejection applies to a `"name:=expr"`/`"f(params):=expr"`
  definition's own name and parameter list, not just its body --
  `{"expr":"x²:=4"}`, `{"expr":"a２:=1"}` and `{"expr":"f(x²):=1"}` each
  answer 400 too, and a rejected definition never reaches `CalcState`:
  `GET /api/calc/vars` lists none of those names afterward, and the stored
  variables/functions are byte-for-byte unchanged from before the attempt.
- Bug #20 (P28): `POST /api/calc/evaluate` no longer freezes the server on a
  power whose exact result would need an unreasonable number of decimal
  digits -- `{"expr":"9^9^9"}` (~369,671,667 digits), `{"expr":
  "10^10^10"}` (10,000,000,000 digits) and `{"expr":"2^10000000"}`
  (~3,010,300 digits) previously made sympy try to materialize that exact
  integer before answering at all, which could block every other request,
  including an unrelated `{"expr":"1+1"}`, for minutes or longer. New
  `graphcalc/limits.py::is_power_too_large()` parses the expression a
  second time with `evaluate=False` and estimates each power's result size
  from float `log10` arithmetic alone -- base's magnitude times exponent's
  magnitude, recursing bottom-up through a right-associative tower such as
  `9^9^9` without ever computing the inner exponent exactly -- before
  `calc.evaluate`'s own, real (evaluating) `parse_expr` call runs at all.
  A power estimated past the limit answers 200 with `domain_error:
  "result too large to compute"` instead (`exact`/`decimal`/`complex` all
  `null`), each within the same request/response cycle, so the next
  request is always answered. A symbolic or non-numeric base/exponent
  (`{"expr":"x^10000000"}`, a stored variable used as a base or exponent)
  is always treated as "unknown" and let through unflagged.
  `{"expr":"10^1000"}` (1001 digits) still answers exact `"1000000...0"`
  and decimal `"1e1000"`.
- Bug #27 (P33): a long result, value or error no longer widens the whole
  page -- before this fix, `{"expr":"10^1000"}`'s 1,001-digit exact value
  printed on one unbroken line in `#calc-history`, and the page scrolled
  sideways instead of staying put (reported in issue #27 as 8,963px wide
  in a 1280px window).
  `graphcalc/static/style.css` now sets `overflow-wrap: anywhere` (and
  `word-break: break-word` as a fallback) on `body`; inherited by every
  `.tab-panel`, it breaks any unbroken run of characters the server
  echoes back -- the same digit string in the history entry
  (`{"expr":"10^1000"}`), the variable list (`{"expr":"a:=10^1000"}`), the
  function list (`{"expr":"f(x):=x+10^1000"}`), and the error line (a 400
  whose message echoes a long bad input) -- inside its own block instead
  of widening `document.documentElement.scrollWidth` past
  `window.innerWidth`. The rule is global (on `body`, not a per-tab
  selector), so the Graphs, Lists & Statistics and CAS tabs inherit the
  same protection for any long text added later. Added
  `tests/test_p33_wrapping.py` (Playwright-driven: evaluates each case in
  a real 1280x900 page and asserts `scrollWidth <= innerWidth`, plus a
  plain static-content check that `style.css` sets `overflow-wrap` or
  `word-break` on `body`/`.tab-panel`).
- Bug #40 (P34): the Graphs tab no longer joins a curve across a vertical
  asymptote -- `f1 "1/x"` in the `-5..5` window used to draw a near-vertical
  line in f1's colour straight through `x = 0`, visually welding its two
  branches together, even though `POST /api/graph/plot` (P10) already
  answered `y: null` for the one sample exactly on the pole: with 600
  evenly spaced samples across `-5..5`, the pole itself falls *between*
  two samples, so both of its neighbours come back as large-but-finite
  floats and the canvas drew straight through the gap. `tan(x)` at its
  poles and `1/(x-1)` at `x = 1` had the same problem. Fixed entirely in
  `graphcalc/static/app.js`'s canvas draw loop (`graphDrawSeries`), between
  new `// P34-BEGIN`/`// P34-END` markers: a new pure helper,
  `graphIsAsymptoteJump(y0, y1, ymin, ymax)`, now also breaks the path
  between two consecutive samples when both are finite, they swing from
  positive to negative (or back), and the swing is more than twice the
  window's own height -- never on a mere `null` gap, which already broke
  the path before this fix. A steep but still continuous curve such as
  `f1 "10*x"` stays one unbroken line: its jump between adjacent samples is
  nowhere near the window's height. `graphcalc/graph.py`'s `plot()` and the
  `POST /api/graph/plot` contract (P10) are unchanged. Added
  `tests/test_p34_asymptote_break.py` (checks the helper is defined inside
  the markers and that `graphDrawSeries` calls it, then -- when `node` is on
  `PATH` -- runs the extracted helper against the exact `y` arrays
  `graph.plot()` returns, confirming it breaks `1/x`, `tan(x)` and
  `1/(x-1)` at their poles but leaves `10*x` whole) and
  `tests/acceptance/test_p34_asymptote.py` (a real headless-browser check
  that reads `graph-canvas`'s own pixels for each case; skips if the
  acceptance harness has no browser).
