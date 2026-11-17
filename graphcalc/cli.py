"""Command line entry point: health endpoint, static UI shell, calc API.

Serves JSON at /health and the plain HTML/CSS/JS page (and its /static/<name>
assets) that the browser-facing tabs are built on; see Handler.do_GET. The
math API lives under /api/calc/... -- see Handler.do_POST and
_handle_calc_evaluate for POST /api/calc/evaluate, which defers the actual
parsing and evaluation to graphcalc.calc. Every successful evaluation --
including a successful "name:=expr" or "f(x):=expr" definition (plan step
P32, owner revision 2026-11-14) -- is appended to a graphcalc.history.
HistoryStore held on the HTTPServer instance (see build_server and
_history_store); GET /api/calc/history reads it back, and DELETE
/api/calc/history clears it (see Handler.do_DELETE and
_handle_calc_history_delete).

A "name:=expr" input (graphcalc.calc.parse_definition) is detected before
the normal evaluate path and stores the result in a graphcalc.state.CalcState
held on the HTTPServer instance (see build_server and _state), but a
successful definition is added to both. GET /api/calc/vars reads that same
CalcState back as JSON (see _handle_calc_vars_get).

Disk persistence (plan step P9): main()'s `--state PATH` (default
"./graphcalc_state.json") builds a CalcState on that path plus a
graphcalc.history.StateBackedHistoryStore on top of it, so history now lives
in the same JSON file as variables/functions/lists -- the "separate objects"
split described above is only about the in-process API (CalcState vs.
HistoryStore), not the on-disk shape, which P9 unified. `--in-memory` passes
no path to CalcState and plugs in a plain InMemoryHistoryStore instead, so
nothing ever touches disk (see serve()). POST /api/state/reset
(_handle_state_reset) empties both in one call.

The graphing API (plan step P10) lives at POST /api/graph/plot -- see
_handle_graph_plot, which defers the actual parsing, sampling and
evaluation to graphcalc.graph.plot(). Stateless: unlike /api/calc/evaluate,
it never reads from or writes to the HTTPServer's CalcState or history
store.

POST /api/graph/window (plan step P11) lives next to it -- see
_handle_graph_window, which defers to graphcalc.graph.window(). Also
stateless: the client sends the window it already has (or none at all,
for the default "standard" window) and gets the next one back; this
server never remembers a "current" window across requests.

POST /api/graph/analyze (plan step P12) lives next to both -- see
_handle_graph_analyze, which defers to graphcalc.graph.analyze(). The
request is {"operation": "value"|"zero"|"minimum"|"maximum"|
"intersection", "f", "g" (intersection only), "x" (value only), "lower",
"upper" (every other operation)}; the response is always {"operation",
"x", "y", "domain_error"}, with "x"/"y" each a 12-significant-digit
decimal string (graphcalc.numfmt.format_decimal) or None. "No zero or
intersection" is not an error -- it is a 200 with "x"/"y" None and
"domain_error" set (e.g. "no zero in interval"); a bad operation, a
missing parameter, or lower >= upper is a 400, the same as a bad
expression graphcalc.calc.evaluate itself rejects. Also stateless, like
/api/graph/plot and /api/graph/window.

POST /api/graph/table (plan step P13) lives next to all three -- see
_handle_graph_table, which defers to graphcalc.graph.table(). The
request is {"functions": {"f1".."f4": expr}, "start", "step", "rows"};
the response is {"x": [str, ...], "columns": {name: [str | None, ...]}},
with "x" and every column entry a 12-significant-digit decimal string or
None for a non-real/undefined sample. A bad function slot, a missing/
non-finite "start"/"step", a zero "step", or "rows" outside [1, 1000] is
a 400. Also stateless, like the other three graph routes.

Named-list CRUD (plan step P15/S1) lives at GET /api/lists, GET /api/lists/
<name>, PUT /api/lists/<name> and DELETE /api/lists/<name> -- see
_handle_lists_get_all, _handle_lists_get_one, _handle_lists_put and
_handle_lists_delete, which defer name/value validation to graphcalc.lists
and storage to the same CalcState every variable/function definition already
uses (so a list survives a restart with --state, and POST /api/state/reset
empties it, the same as variables and functions). Unlike the four graph
routes above, this one is stateful. The trailing <name> path segment is
decoded and validated by _list_name_from_segment, following the same
decode-then-reject pattern _serve_static already uses for a /static/<name>
segment (percent-decode, then reject a NUL byte or backslash) before
checking it against graphcalc.lists.LIST_NAME_RE; a malformed name, a
malformed body, or an invalid "values" entry is a 400, never a 500 or a
404 -- 404 is reserved for a well-formed name that is simply not a stored
list.

POST /api/stats/onevar (plan steps P16/S1, P16/S2) lives next to the list CRUD
routes above -- see _handle_stats_onevar, which reads body["list"] (a
stored list name) through the same CalcState.get_list the GET /api/lists/
<name> route already uses, then defers the actual statistics to
graphcalc.stats.onevar(). The response is {"n": int, "mean", "median",
"sum", "sx", "sigma_x", "min", "q1", "q3", "max"}, each of the latter nine
an {"exact", "decimal"} pair (graphcalc.numfmt.format_decimal at 12
significant digits for "decimal"); "sx"/"sigma_x" are the sample/
population standard deviations, and "q1"/"q3" are the TI quartile
method's lower/upper-half medians (see graphcalc.stats's own module
docstring for the exact rule). Unlike GET /api/lists/<name>, an undefined
list name here is a 400, not a 404 -- so is a missing "list" key or a
stored list that is empty (never actually possible through PUT /api/lists/
<name>'s own validation, but checked anyway rather than trusting a
hand-edited state file): this route's only successful response is a full
statistics summary, so there is no well-formed "empty" result to 200 with.

POST /api/stats/regression (plan step P17/S1) lives next to POST /api/
stats/onevar above -- see _handle_stats_regression, which is stateless:
unlike onevar's stored-list lookup, this route's body carries "model",
"x" and "y" directly, handed to graphcalc.stats.regression() exactly as
received. The response is {"model", "coefficients": {"a","b"[,"c"]},
"r2", "points": [[x,y], ...], "curve": [[x,y], ...]}, every coefficient/
r2/points/curve number a 12-significant-digit decimal string (graphcalc.
numfmt.format_decimal) with a clean "0" rather than "-0" or "1e-16" for an
exact fit. "points" echoes the request's own ("x","y") pairs; "curve"
holds 50 points evenly spaced across the data's x-range. "model" is
"linear" or "quadratic" (see graphcalc.stats's own module docstring for
each exact fit); an unrecognized "model", a malformed/mismatched-length
"x"/"y", a non-numeric entry, or a degenerate fit (e.g. too few distinct x
values) is a 400, never a 500.
"""

import argparse
import json
import os
import pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

from graphcalc import __version__
from graphcalc.history import InMemoryHistoryStore, StateBackedHistoryStore
from graphcalc.state import CalcState

HEALTH_PATH = "/health"
CALC_EVALUATE_PATH = "/api/calc/evaluate"
CALC_HISTORY_PATH = "/api/calc/history"
CALC_VARS_PATH = "/api/calc/vars"
STATE_RESET_PATH = "/api/state/reset"
GRAPH_PLOT_PATH = "/api/graph/plot"
GRAPH_WINDOW_PATH = "/api/graph/window"
GRAPH_ANALYZE_PATH = "/api/graph/analyze"
GRAPH_TABLE_PATH = "/api/graph/table"
LISTS_PATH = "/api/lists"
LISTS_PREFIX = "/api/lists/"
STATS_ONEVAR_PATH = "/api/stats/onevar"
STATS_REGRESSION_PATH = "/api/stats/regression"
CAS_SIMPLIFY_PATH = "/api/cas/simplify"
CAS_EXPAND_PATH = "/api/cas/expand"
CAS_FACTOR_PATH = "/api/cas/factor"
CAS_DERIVATIVE_PATH = "/api/cas/derivative"
CAS_INTEGRAL_PATH = "/api/cas/integral"

# The static UI shell: index.html plus plain CSS/JS, shipped next to this module.
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"
STATIC_PREFIX = "/static/"

# Only extensions we explicitly know how to label get served; anything else 404s.
STATIC_CONTENT_TYPES = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".html": "text/html",
}


def _send_json(handler, status, payload):
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_bytes(handler, status, content_type, body):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _serve_static(handler, path):
    """Serve a file under STATIC_DIR for a /static/<name> request.

    The raw request path is percent-decoded by hand (never trust the client's
    normalization). A NUL byte, a backslash or an absolute segment is refused
    outright; the resolved path must then stay inside STATIC_DIR.resolve().
    Any of those failures, an unknown extension, or a missing file, is a
    JSON 404 -- never a 500.
    """
    try:
        name = unquote(path[len(STATIC_PREFIX) :])
    except (UnicodeDecodeError, ValueError):
        _send_json(handler, 404, {"error": f"not found: {path}"})
        return
    if "\x00" in name or "\\" in name or pathlib.PurePosixPath(name).is_absolute():
        _send_json(handler, 404, {"error": f"not found: {path}"})
        return
    content_type = STATIC_CONTENT_TYPES.get(pathlib.PurePosixPath(name).suffix)
    if content_type is None:
        _send_json(handler, 404, {"error": f"not found: {path}"})
        return
    try:
        candidate = (STATIC_DIR / name).resolve()
    except (ValueError, OSError):
        _send_json(handler, 404, {"error": f"not found: {path}"})
        return
    if not candidate.is_relative_to(STATIC_DIR.resolve()):
        _send_json(handler, 404, {"error": f"not found: {path}"})
        return
    try:
        body = candidate.read_bytes()
    except OSError:
        _send_json(handler, 404, {"error": f"not found: {path}"})
        return
    _send_bytes(handler, 200, content_type, body)


def _read_json_body(handler):
    """Read and JSON-decode the request body, or {} when there is none.

    Raises ValueError (the base of UnicodeDecodeError and
    json.JSONDecodeError, and what int() raises on a bad Content-Length)
    for any malformed body; the caller turns that into a JSON 400.
    """
    length = int(handler.headers.get("Content-Length", 0) or 0)
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _history_store(handler):
    """Return the HTTPServer's history store, creating a default if missing.

    build_server() always sets one up front; this fallback only matters for
    a server built by calling HTTPServer(..., Handler) directly (as tests
    that don't care about history do), so every request path still has a
    store to read from or append to.
    """
    store = getattr(handler.server, "history_store", None)
    if store is None:
        store = InMemoryHistoryStore()
        handler.server.history_store = store
    return store


def _state(handler):
    """Return the HTTPServer's CalcState, creating a default if missing.

    build_server() always sets one up front; this fallback only matters for
    a server built by calling HTTPServer(..., Handler) directly (as tests
    that don't care about variables do), so every evaluate request still has
    a state object to read stored variables from or store a new one into.
    The default CalcState() is in-memory only (no path), same as the
    _history_store fallback.
    """
    state = getattr(handler.server, "state", None)
    if state is None:
        state = CalcState()
        handler.server.state = state
    return state


def _handle_calc_history_get(handler):
    """GET /api/calc/history -> 200 {"history": [...]}, oldest entry first."""
    _send_json(handler, 200, {"history": _history_store(handler).entries()})


def _handle_calc_history_delete(handler):
    """DELETE /api/calc/history -> clears the store, then 200 {"history": []}.

    Also clears the CalcState's stored "ans" (graphcalc.state.CalcState.
    clear_ans) at the same time, since P26/S1 moved "ans" off the history
    store and onto CalcState -- without this, a later /api/calc/evaluate
    using "ans" would keep recalling the pre-delete answer forever. After
    this, "ans" in a later /api/calc/evaluate has no last entry to recall:
    calc.evaluate raises CalcError("ans is undefined"), which
    _handle_calc_evaluate turns into the usual 400, never a 500.
    """
    _history_store(handler).clear()
    _state(handler).clear_ans()
    _send_json(handler, 200, {"history": []})


def _handle_calc_vars_get(handler):
    """GET /api/calc/vars -> 200 {"variables": {...}, "functions": {...}}.

    `_state(handler).variables()` and `.functions()` hold plain sympy str()
    values/bodies ("**" notation, directly re-sympify()-able -- see
    graphcalc.state.CalcState). Both are rendered through calc.to_caret the
    same way a function definition's own evaluate response already is
    (plan step P7/S2), so a value or body with a power reads with "^" here
    too (e.g. a stored body "x**2 + 1" -> "x^2 + 1"); a plain value like
    "5" is unchanged. This is read-only: it never evaluates or stores
    anything, so it cannot itself trigger names.check_not_constant.
    """
    from graphcalc import calc

    state = _state(handler)
    variables = {name: calc.to_caret(value) for name, value in state.variables().items()}
    functions = {
        name: {"params": spec["params"], "body": calc.to_caret(spec["body"])}
        for name, spec in state.functions().items()
    }
    _send_json(handler, 200, {"variables": variables, "functions": functions})


def _handle_state_reset(handler):
    """POST /api/state/reset -> 200 {"status": "reset"} (plan step P9/S3).

    Empties variables, functions, lists, history and "ans" in one go:
    `_state(handler).reset()` (graphcalc.state.CalcState.reset) clears the
    first four and "ans" and, when a --state path is set, saves the now-
    empty state to disk once (one atomic write, not a sequence of partial
    ones). The history store is cleared too -- `_history_store(handler).
    clear()` -- which matters for a --in-memory run's plain
    InMemoryHistoryStore (not reachable through CalcState.reset() at all,
    since that store holds its own list) and is a harmless no-op for a
    --state run's StateBackedHistoryStore, whose clear() just calls back
    into the same CalcState.reset() already emptied "history" (clearing an
    already-empty list). Either way, GET /api/calc/history and GET
    /api/calc/vars both read back empty right after this.
    """
    _state(handler).reset()
    _history_store(handler).clear()
    _send_json(handler, 200, {"status": "reset"})


def _handle_calc_evaluate(handler):
    """POST /api/calc/evaluate: {"expr","mode"} -> calc.evaluate's dict, 200 JSON.

    A malformed body, a non-object body, a missing "expr", or a CalcError
    from calc.evaluate (bad syntax, an invalid mode) is a JSON 400 -- never
    a 500. The sympy-backed calc module is imported lazily so every other
    route keeps working even if sympy were ever unavailable.

    Only a successful evaluation (no CalcError, and result["domain_error"]
    is None) is appended to the history store as
    {"expr": <original input>, "exact": ..., "decimal": ...}; a 400 or a
    domain_error (division by zero, undefined) adds nothing.

    Before any of that, calc.parse_definition checks whether expr is a bare
    "name:=expr" assignment (plan step P7/S1). When it is: names.check_not_
    constant(name) first rejects a reserved name (-> 400 "cannot redefine
    constant <name>"), then the right-hand side is evaluated the same way
    as any other expr (so it also sees previously stored variables and
    functions), and -- only when that evaluation has no domain_error -- the
    result's exact value is stored under name in the HTTPServer's CalcState.
    The response is calc.evaluate's own dict with "expr" replaced by the
    original "name:=expr" text. "ans" only ever recalls a plain evaluation's
    result (P26/S1, P30), never a definition's right-hand side -- that is
    unchanged by the below. A successful definition (no domain_error on the
    right-hand side) is, however, appended to the history store too (plan
    step P32, owner revision 2026-11-14: "definitions in history"), as
    {"expr": <original "name:=expr" text>, "exact": ..., "decimal": ...} --
    `exact` and `decimal` are read back off the same `response` dict this
    handler is about to send, so the history entry always matches what the
    client actually saw. A rejected definition (check_not_constant's 400, or
    a domain_error on the right-hand side such as "a:=1/0") returns before
    this append ever runs, so it adds nothing -- the same rule a plain
    evaluate() failure already followed.

    calc.parse_function_definition checks for "f(x):=expr" (or "f(x,y):=
    expr") the same way (plan step P7/S2): names.check_not_constant(name)
    rejects a reserved function name, then the body is evaluated with the
    params bound as plain Symbols (so a param always wins over a same-named
    stored variable) and with every previously stored function also in
    scope. On success, {"params": params, "body": <plain "**" str>} is
    stored under name in CalcState, and the response's "exact" is the body
    rendered in caret form via calc.to_caret (e.g. "x^2 + 1") -- the one
    place that conversion happens; the stored body itself stays in plain
    "**" form so it stays directly re-sympify()-able. The history entry
    added for a successful function definition (plan step P32, same rule as
    above) uses this already-caret-converted `response["exact"]`, so it
    reads "x^2 + 1" too, never the stored "**" form. A later plain
    evaluate() call such as "f(3)" sees every stored function through
    `functions=_state(handler).functions()` below, which rebuilds it as a
    sympy Lambda; calling it with the wrong number of arguments is a 400,
    never a 500 (calc.evaluate turns sympy's BadArgumentsError into a
    CalcError).

    `lists=_state(handler).lists()` is passed into every one of the three
    calc.evaluate calls above (plan step P15/S3), the same way `variables`
    and `functions` already are: an expr/rhs that references a stored list
    name (e.g. "2*L1+1") is evaluated elementwise instead, exact
    "[3, 5, 7]" -- see calc.evaluate's own docstring and
    calc._evaluate_list_expression for the full rule. An expr/rhs that
    references no list name at all behaves exactly as it did before this
    feature existed.

    Everything above is wrapped in a catch-all: any exception this function
    did not anticipate (e.g. something calc.evaluate's own try/except does
    not cover) is still turned into a JSON 400, never left to propagate into
    a 500. This handler must never answer with a 500. The catch-all's own
    message is "request failed: <exc>", not "unexpected error: <exc>" (plan
    step P28/S2, Bug #20 fix): before that fix, a result just past calc.
    evaluate's own is_power_too_large guard (e.g. "2^20000") could still
    raise Python's int-to-str ValueError ("Exceeds the limit (4300
    digits)...") on the way out, which this catch-all then wrapped as
    "unexpected error: Exceeds the limit (4300 digits)..." -- exactly the
    wording this product's acceptance criteria ban from ever appearing in a
    response. calc.evaluate now catches that ValueError/OverflowError itself
    and reports the same "result too large to compute" domain_error instead
    (see calc.evaluate's own docstring), so this catch-all should no longer
    ever see that particular exception at all; the wording changed anyway,
    as a second line of defense for any other exception this handler did
    not anticipate.
    """
    from graphcalc import calc, names

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        expr = payload.get("expr")
        if expr is None:
            _send_json(handler, 400, {"error": "missing parameter: expr"})
            return
        mode = payload.get("mode", "rad")

        definition = calc.parse_definition(expr)
        if definition is not None:
            name, rhs = definition
            try:
                names.check_not_constant(name)
                result = calc.evaluate(
                    rhs,
                    mode,
                    last_entry=_state(handler).ans(),
                    variables=_state(handler).variable_entries(),
                    functions=_state(handler).function_entries(),
                    lists=_state(handler).lists(),
                )
            except calc.CalcError as exc:
                _send_json(handler, 400, {"error": str(exc)})
                return
            result_srepr = result.pop("_result_srepr", None)
            if result["exact"] is not None:
                _state(handler).set_variable(name, result["exact"], result_srepr)
            response = dict(result)
            response["expr"] = expr
            if result["exact"] is not None:
                _history_store(handler).append(
                    {"expr": expr, "exact": response["exact"], "decimal": response["decimal"]}
                )
            _send_json(handler, 200, response)
            return

        function_definition = calc.parse_function_definition(expr)
        if function_definition is not None:
            name, params, rhs = function_definition
            try:
                names.check_not_constant(name)
                result = calc.evaluate(
                    rhs,
                    mode,
                    last_entry=_state(handler).ans(),
                    variables=_state(handler).variable_entries(),
                    functions=_state(handler).function_entries(),
                    symbols=params,
                    lists=_state(handler).lists(),
                )
            except calc.CalcError as exc:
                _send_json(handler, 400, {"error": str(exc)})
                return
            result_srepr = result.pop("_result_srepr", None)
            if result["exact"] is not None:
                _state(handler).set_function(name, params, result["exact"], result_srepr)
            response = dict(result)
            response["expr"] = expr
            if result["exact"] is not None:
                response["exact"] = calc.to_caret(result["exact"])
                _history_store(handler).append(
                    {"expr": expr, "exact": response["exact"], "decimal": response["decimal"]}
                )
            _send_json(handler, 200, response)
            return

        try:
            result = calc.evaluate(
                expr,
                mode,
                last_entry=_state(handler).ans(),
                variables=_state(handler).variable_entries(),
                functions=_state(handler).function_entries(),
                lists=_state(handler).lists(),
            )
        except calc.CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        ans_srepr = result.pop("_result_srepr", None)
        if result["domain_error"] is None:
            _history_store(handler).append(
                {"expr": expr, "exact": result["exact"], "decimal": result["decimal"]}
            )
            _state(handler).set_ans(result["exact"], ans_srepr)
        _send_json(handler, 200, result)
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_graph_plot(handler):
    """POST /api/graph/plot: {"functions","window","samples"} -> graph.plot's
    dict, 200 JSON (plan step P10/S1).

    A malformed body, a non-object body, or a graphcalc.graph.GraphError
    (bad function slot, bad window, bad sample count, or a free variable
    other than "x") is a JSON 400. graphcalc.calc.CalcError -- bad syntax,
    an unknown function call, or an expression the freeze guard flags, all
    of which graph.plot() can raise unchanged, via graphcalc.graph.
    _parse_function reusing graphcalc.calc.evaluate -- is also a JSON 400
    here, not just GraphError (see graphcalc.graph's own module docstring
    for why both are expected). The catch-all at the very end is this
    handler's own backstop for anything neither of those two covers: this
    endpoint must never answer with a 500.

    graphcalc.graph is imported lazily, the same reason graphcalc.calc is
    imported lazily in _handle_calc_evaluate: every other route keeps
    working even if sympy were ever unavailable.
    """
    from graphcalc import calc, graph

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        try:
            result = graph.plot(payload)
        except (graph.GraphError, calc.CalcError) as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _send_json(handler, 200, result)
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_graph_window(handler):
    """POST /api/graph/window: {"action","factor","dx","dy","window"} ->
    graph.window's dict, 200 JSON (plan step P11/S1).

    A malformed body, a non-object body, or a graphcalc.graph.GraphError
    (an unknown action, a bad window, or a bad factor/dx/dy) is a JSON
    400. Unlike _handle_graph_plot, graph.window() never calls
    graphcalc.calc.evaluate, so there is no CalcError to catch here -- see
    graphcalc.graph's own module docstring. The catch-all at the very end
    is this handler's own backstop for anything else: this endpoint must
    never answer with a 500.

    graphcalc.graph is imported lazily, the same reason graphcalc.calc is
    imported lazily in _handle_calc_evaluate: every other route keeps
    working even if sympy were ever unavailable.
    """
    from graphcalc import graph

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        try:
            result = graph.window(payload)
        except graph.GraphError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _send_json(handler, 200, result)
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_graph_analyze(handler):
    """POST /api/graph/analyze: {"operation","f","g","x","lower","upper"} ->
    graph.analyze's dict, 200 JSON (plan step P12/S1).

    A malformed body, a non-object body, or a graphcalc.graph.GraphError
    (a bad operation, a missing/wrong-type parameter, or lower >= upper)
    is a JSON 400. graphcalc.calc.CalcError -- bad syntax, an unknown
    function call, or an expression the freeze guard flags, all of which
    graph.analyze() can raise unchanged, via graphcalc.graph._parse_function
    reusing graphcalc.calc.evaluate -- is also a JSON 400 here, not just
    GraphError (same dual-exception contract as _handle_graph_plot; see
    graphcalc.graph's own module docstring). "No zero in interval" is not
    one of these -- graph.analyze() answers that as a normal 200 with
    "domain_error" set, so it is sent the same way as any other success.
    The catch-all at the very end is this handler's own backstop for
    anything else: this endpoint must never answer with a 500.

    graphcalc.graph is imported lazily, the same reason graphcalc.calc is
    imported lazily in _handle_calc_evaluate: every other route keeps
    working even if sympy were ever unavailable.
    """
    from graphcalc import calc, graph

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        try:
            result = graph.analyze(payload)
        except (graph.GraphError, calc.CalcError) as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _send_json(handler, 200, result)
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_graph_table(handler):
    """POST /api/graph/table: {"functions","start","step","rows"} ->
    graph.table's dict, 200 JSON (plan step P13/S1).

    A malformed body, a non-object body, or a graphcalc.graph.GraphError
    (a bad function slot, a missing/non-finite "start"/"step", a zero
    "step", or "rows" outside [1, 1000]) is a JSON 400. graphcalc.calc.
    CalcError -- bad syntax, an unknown function call, or an expression
    the freeze guard flags, all of which graph.table() can raise
    unchanged, via graphcalc.graph._parse_function reusing graphcalc.
    calc.evaluate -- is also a JSON 400 here, not just GraphError (same
    dual-exception contract as _handle_graph_plot and
    _handle_graph_analyze; see graphcalc.graph's own module docstring).
    The catch-all at the very end is this handler's own backstop for
    anything else: this endpoint must never answer with a 500.

    graphcalc.graph is imported lazily, the same reason graphcalc.calc is
    imported lazily in _handle_calc_evaluate: every other route keeps
    working even if sympy were ever unavailable.
    """
    from graphcalc import calc, graph

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        try:
            result = graph.table(payload)
        except (graph.GraphError, calc.CalcError) as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _send_json(handler, 200, result)
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


# Named-list CRUD (plan step P15/S1).


def _list_name_from_segment(segment):
    """Decode and validate a trailing /api/lists/<name> path segment.

    Follows the same decode-then-reject pattern _serve_static already uses
    for a /static/<name> segment: percent-decode, then reject a NUL byte or
    backslash, before handing the result to graphcalc.lists.
    validate_list_name, which checks it against LIST_NAME_RE. Returns the
    decoded name on success; raises graphcalc.calc.CalcError -- the same
    type validate_list_name itself raises -- for a decode failure, a NUL
    byte, or a backslash, so every caller below can catch just that one
    exception type and turn it into the usual 400, the same way a bad name
    that *does* decode cleanly but fails the regex already would.
    """
    from graphcalc.calc import CalcError
    from graphcalc.lists import validate_list_name

    try:
        name = unquote(segment)
    except (UnicodeDecodeError, ValueError):
        raise CalcError(f"invalid list name: {segment!r}")
    if "\x00" in name or "\\" in name:
        raise CalcError(f"invalid list name: {name!r}")
    validate_list_name(name)
    return name


def _handle_lists_get_all(handler):
    """GET /api/lists -> 200 {"lists": [sorted names]} (plan step P15/S1)."""
    try:
        _send_json(handler, 200, {"lists": sorted(_state(handler).lists().keys())})
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_lists_get_one(handler, segment):
    """GET /api/lists/<name> -> 200 {"name","values"} or 404 (plan step
    P15/S1). A malformed `segment` (not matching graphcalc.lists.
    LIST_NAME_RE, a NUL byte, or a backslash -- see _list_name_from_segment)
    is a 400, never a 404: 404 is reserved for a well-formed name that is
    simply not a stored list.
    """
    from graphcalc.calc import CalcError

    try:
        try:
            name = _list_name_from_segment(segment)
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        values = _state(handler).get_list(name)
        if values is None:
            _send_json(handler, 404, {"error": f"no such list: {name}"})
            return
        _send_json(handler, 200, {"name": name, "values": values})
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_lists_put(handler, segment):
    """PUT /api/lists/<name> {"values": [...]} -> 200 {"name","values"}
    (plan step P15/S1). Overwrites any existing list already stored under
    `name` -- PUT is upsert, same as PUT in general; there is no separate
    "create" vs. "update" response.

    A malformed name (see _list_name_from_segment), a malformed/non-object
    JSON body, or an invalid "values" field -- not a list of strings,
    empty, oversized, or containing a value graphcalc.calc.evaluate rejects
    such as "abc+" (graphcalc.lists.validate_list_values) -- is a 400,
    never a 500.

    The request body is always read first, before the path-derived name is
    even checked, the same order every other body-bearing route (_handle_
    calc_evaluate, _handle_graph_plot/window/analyze/table) already uses.
    A bad name is still a 400, but only after the body is drained: this
    server answers with "HTTP/1.0" (Handler never sets protocol_version),
    so BaseHTTPRequestHandler closes the TCP connection after every single
    response. Closing a socket while the client's PUT body is still sitting
    unread in the kernel receive buffer makes the OS send a TCP RST instead
    of a clean FIN, which the client can observe as a connection-reset/
    aborted error instead of ever seeing the 400 -- nondeterministically,
    since it is a race between the server's close and the client finishing
    its write/starting its read. Validating the name first (the order this
    handler originally used) left that body undrained on every bad-name
    PUT, which is exactly that race.
    """
    from graphcalc.calc import CalcError
    from graphcalc.lists import validate_list_values

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        try:
            name = _list_name_from_segment(segment)
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        values = payload.get("values")
        try:
            validate_list_values(values)
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _state(handler).set_list(name, values)
        _send_json(handler, 200, {"name": name, "values": list(values)})
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_lists_delete(handler, segment):
    """DELETE /api/lists/<name> -> 200 {"deleted": name} or 404 (plan step
    P15/S1). A malformed name (see _list_name_from_segment) is a 400, the
    same as GET/PUT; 404 is reserved for a well-formed name that is simply
    not a stored list.
    """
    from graphcalc.calc import CalcError

    try:
        try:
            name = _list_name_from_segment(segment)
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        if not _state(handler).delete_list(name):
            _send_json(handler, 404, {"error": f"no such list: {name}"})
            return
        _send_json(handler, 200, {"deleted": name})
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_stats_onevar(handler):
    """POST /api/stats/onevar {"list": name} -> stats.onevar's dict, 200
    JSON (plan steps P16/S1, P16/S2).

    "list" must be a non-empty string naming a stored list -- a missing
    "list" key, a non-string value, a name graphcalc.lists.
    validate_list_name rejects (plan step P16/S2: reused here, the same
    check PUT/GET/DELETE /api/lists/<name> already apply to a path-derived
    name), a name graphcalc.state.CalcState.get_list does not recognize, or
    (only reachable through a hand-edited state file, never through PUT
    /api/lists/<name> itself) a stored but empty list -- the latter raised
    as CalcError by graphcalc.stats.onevar itself, not checked here -- are
    all a 400, never the 404 GET /api/lists/<name> itself would give for an
    unknown name -- this route has no "well-formed but not found" response
    to give, only a statistics summary or an error. Everything else is
    handed to graphcalc.stats.onevar() unchanged; any exception it raises
    (including the IndexError a one-element list's undefined TI quartile
    halves raise -- see graphcalc.stats's own module docstring) is caught
    by the blanket catch-all below, same as every other route's "never a
    500" rule.
    """
    from graphcalc import stats
    from graphcalc.calc import CalcError
    from graphcalc.lists import validate_list_name

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        name = payload.get("list")
        if not isinstance(name, str) or not name:
            _send_json(handler, 400, {"error": "missing parameter: list"})
            return
        try:
            validate_list_name(name)
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        values = _state(handler).get_list(name)
        if values is None:
            _send_json(handler, 400, {"error": f"no such list: {name}"})
            return
        try:
            result = stats.onevar(values)
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _send_json(handler, 200, result)
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_stats_regression(handler):
    """POST /api/stats/regression {"model","x","y"} -> stats.regression's
    dict, 200 JSON (plan step P17/S1).

    Unlike _handle_stats_onevar, this route is stateless -- "x"/"y" are
    sent in the request body, not read out of a stored list -- so "model",
    "x", and "y" are handed to graphcalc.stats.regression() exactly as the
    client sent them (including a missing or wrong-typed one, e.g. "x" not
    present at all), and that pure function owns every validation decision:
    an unrecognized "model" ("linear" and "quadratic" are implemented), a
    malformed/empty/oversized "x" or "y" (graphcalc.lists.
    validate_list_values, reused there the same way PUT /api/lists/<name>
    already uses it), a non-string or unparseable entry, a non-real entry,
    mismatched "x"/"y" lengths, or a degenerate fit (e.g. too few distinct
    x values) are all raised as CalcError and turned into the same 400 here.
    The blanket catch-all below still backs up any exception
    graphcalc.stats.regression does not itself anticipate, the same
    "never a 500" rule every other route already follows.
    """
    from graphcalc import stats
    from graphcalc.calc import CalcError

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        try:
            result = stats.regression(payload.get("model"), payload.get("x"), payload.get("y"))
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _send_json(handler, 200, result)
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_cas_op(handler, op):
    """Shared body for every stateless POST /api/cas/<op> route (plan step
    P19/S2 pulls this out of what was _handle_cas_simplify alone in P19/S1,
    so /simplify, /expand and /factor -- added in P19/S3 -- share one
    handler instead of three near-identical copies).

    `op` is one of graphcalc.cas's own functions (simplify, expand, ...):
    "expr" is handed to it exactly as the client sent it, and that function
    owns every parsing/algebra decision -- see graphcalc.cas's own module
    docstring for the full grammar/whitelist rule it shares with graphcalc.
    calc.evaluate. A malformed body, a non-object body, a missing or
    non-string "expr", or a graphcalc.calc.CalcError from `op` (bad
    grammar, an unknown function call, or anything else parse_expr itself
    rejects) is a JSON 400. The blanket catch-all below still backs up any
    exception neither of those anticipates, the same "never a 500" rule
    every other route already follows.
    """
    from graphcalc.calc import CalcError

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        expr = payload.get("expr")
        if not isinstance(expr, str) or not expr.strip():
            _send_json(handler, 400, {"error": "missing parameter: expr"})
            return
        try:
            result = op(expr)
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _send_json(handler, 200, {"result": result})
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_cas_simplify(handler):
    """POST /api/cas/simplify {"expr"} -> 200 JSON {"result": str} (plan
    step P19/S1). See _handle_cas_op for the shared body this delegates to.
    """
    from graphcalc import cas

    _handle_cas_op(handler, cas.simplify)


def _handle_cas_expand(handler):
    """POST /api/cas/expand {"expr"} -> 200 JSON {"result": str} (plan step
    P19/S2). See _handle_cas_op for the shared body this delegates to.
    """
    from graphcalc import cas

    _handle_cas_op(handler, cas.expand)


def _handle_cas_factor(handler):
    """POST /api/cas/factor {"expr"} -> 200 JSON {"result": str} (plan step
    P19/S3). See _handle_cas_op for the shared body this delegates to.
    """
    from graphcalc import cas

    _handle_cas_op(handler, cas.factor)


def _handle_cas_derivative(handler):
    """POST /api/cas/derivative {"expr", "var"} -> 200 JSON {"result": str}
    (plan step P20/S1).

    Unlike /simplify, /expand and /factor, this route takes a second body
    key, "var", so it does not fit _handle_cas_op's single-"expr" shape --
    hence this sibling handler instead of a fourth _handle_cas_op call. A
    malformed body, a non-object body, or a missing or non-string "expr"
    are rejected exactly as _handle_cas_op rejects them (same message:
    "missing parameter: expr"); a missing or non-string "var" is rejected
    the same way, with "missing parameter: var". Once both are strings,
    graphcalc.cas.derivative owns every remaining parsing/algebra/guard
    decision (including whether `var` is a valid identifier) -- a
    graphcalc.calc.CalcError it raises becomes this route's own JSON 400.
    The blanket catch-all below still backs up any exception neither of
    those anticipates, the same "never a 500" rule every other route
    already follows.
    """
    from graphcalc import cas
    from graphcalc.calc import CalcError

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        expr = payload.get("expr")
        if not isinstance(expr, str) or not expr.strip():
            _send_json(handler, 400, {"error": "missing parameter: expr"})
            return
        var = payload.get("var")
        if not isinstance(var, str) or not var.strip():
            _send_json(handler, 400, {"error": "missing parameter: var"})
            return
        try:
            result = cas.derivative(expr, var)
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _send_json(handler, 200, {"result": result})
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


def _handle_cas_integral(handler):
    """POST /api/cas/integral {"expr","var","lower","upper" (both optional)}
    -> 200 JSON {"result": str} (plan step P20/S2).

    Like /derivative, this route takes a second body key, "var", so it does
    not fit _handle_cas_op's single-"expr" shape -- hence this sibling
    handler. A malformed body, a non-object body, or a missing or
    non-string "expr"/"var" are rejected exactly as _handle_cas_derivative
    rejects them ("missing parameter: expr"/"missing parameter: var").
    "lower" and "upper" are each optional and forwarded to graphcalc.cas.
    integral exactly as the client sent them (whatever JSON type they
    are) -- that function owns every remaining parsing/algebra/guard
    decision, including rejecting a body that supplies exactly one of the
    two, or a bound that is not a plain JSON number. A graphcalc.calc.
    CalcError it raises becomes this route's own JSON 400. The blanket
    catch-all below still backs up any exception neither of those
    anticipates, the same "never a 500" rule every other route already
    follows.
    """
    from graphcalc import cas
    from graphcalc.calc import CalcError

    try:
        try:
            payload = _read_json_body(handler)
        except ValueError:
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            _send_json(handler, 400, {"error": "invalid JSON body"})
            return
        expr = payload.get("expr")
        if not isinstance(expr, str) or not expr.strip():
            _send_json(handler, 400, {"error": "missing parameter: expr"})
            return
        var = payload.get("var")
        if not isinstance(var, str) or not var.strip():
            _send_json(handler, 400, {"error": "missing parameter: var"})
            return
        lower = payload.get("lower")
        upper = payload.get("upper")
        try:
            result = cas.integral(expr, var, lower, upper)
        except CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        _send_json(handler, 200, {"result": result})
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"request failed: {exc}"})


class Handler(BaseHTTPRequestHandler):
    """The product's only HTTP handler: health check, UI shell, static assets.

    Routes matched on the exact request path (no query-string handling):
    - /health                -> 200 JSON {"status": "ok"}
    - /                      -> 200 text/html, the four-tab index page
    - /static/<name>         -> see _serve_static for the allowlist and the
                                 traversal/NUL/backslash checks
    - POST /api/calc/evaluate   -> see _handle_calc_evaluate
    - GET /api/calc/history     -> see _handle_calc_history_get
    - DELETE /api/calc/history  -> see _handle_calc_history_delete
    - GET /api/calc/vars        -> see _handle_calc_vars_get
    - POST /api/state/reset     -> see _handle_state_reset
    - POST /api/graph/plot      -> see _handle_graph_plot
    - POST /api/graph/window    -> see _handle_graph_window
    - POST /api/graph/analyze   -> see _handle_graph_analyze
    - POST /api/graph/table     -> see _handle_graph_table
    - GET /api/lists            -> see _handle_lists_get_all
    - GET /api/lists/<name>     -> see _handle_lists_get_one
    - PUT /api/lists/<name>     -> see _handle_lists_put
    - DELETE /api/lists/<name>  -> see _handle_lists_delete
    - POST /api/stats/onevar    -> see _handle_stats_onevar
    - POST /api/stats/regression -> see _handle_stats_regression
    - POST /api/cas/simplify    -> see _handle_cas_simplify
    - POST /api/cas/expand      -> see _handle_cas_expand
    - POST /api/cas/factor      -> see _handle_cas_factor
    - POST /api/cas/derivative  -> see _handle_cas_derivative
    - POST /api/cas/integral    -> see _handle_cas_integral
    - anything else          -> 404 JSON {"error": ...}, never a 500
    """

    def do_GET(self):
        if self.path == HEALTH_PATH:
            _send_json(self, 200, {"status": "ok"})
            return
        if self.path == "/":
            _send_bytes(self, 200, "text/html; charset=utf-8", INDEX_PATH.read_bytes())
            return
        if self.path.startswith(STATIC_PREFIX):
            _serve_static(self, self.path)
            return
        if self.path == CALC_HISTORY_PATH:
            _handle_calc_history_get(self)
            return
        if self.path == CALC_VARS_PATH:
            _handle_calc_vars_get(self)
            return
        if self.path == LISTS_PATH:
            _handle_lists_get_all(self)
            return
        if self.path.startswith(LISTS_PREFIX):
            _handle_lists_get_one(self, self.path[len(LISTS_PREFIX) :])
            return
        _send_json(self, 404, {"error": f"not found: {self.path}"})

    def do_POST(self):
        if self.path == CALC_EVALUATE_PATH:
            _handle_calc_evaluate(self)
            return
        if self.path == STATE_RESET_PATH:
            _handle_state_reset(self)
            return
        if self.path == GRAPH_PLOT_PATH:
            _handle_graph_plot(self)
            return
        if self.path == GRAPH_WINDOW_PATH:
            _handle_graph_window(self)
            return
        if self.path == GRAPH_ANALYZE_PATH:
            _handle_graph_analyze(self)
            return
        if self.path == GRAPH_TABLE_PATH:
            _handle_graph_table(self)
            return
        if self.path == STATS_ONEVAR_PATH:
            _handle_stats_onevar(self)
            return
        if self.path == STATS_REGRESSION_PATH:
            _handle_stats_regression(self)
            return
        if self.path == CAS_SIMPLIFY_PATH:
            _handle_cas_simplify(self)
            return
        if self.path == CAS_EXPAND_PATH:
            _handle_cas_expand(self)
            return
        if self.path == CAS_FACTOR_PATH:
            _handle_cas_factor(self)
            return
        if self.path == CAS_DERIVATIVE_PATH:
            _handle_cas_derivative(self)
            return
        if self.path == CAS_INTEGRAL_PATH:
            _handle_cas_integral(self)
            return
        _send_json(self, 404, {"error": f"not found: {self.path}"})

    def do_PUT(self):
        if self.path.startswith(LISTS_PREFIX):
            _handle_lists_put(self, self.path[len(LISTS_PREFIX) :])
            return
        _send_json(self, 404, {"error": f"not found: {self.path}"})

    def do_DELETE(self):
        if self.path == CALC_HISTORY_PATH:
            _handle_calc_history_delete(self)
            return
        if self.path.startswith(LISTS_PREFIX):
            _handle_lists_delete(self, self.path[len(LISTS_PREFIX) :])
            return
        _send_json(self, 404, {"error": f"not found: {self.path}"})

    def log_message(self, format, *args):
        return


def build_server(port, history_store=None, state=None):
    """Build the HTTPServer, with a history store attached as .history_store
    and a calc state attached as .state.

    `history_store` lets a caller (tests, mainly) inject a fresh
    HistoryStore; the default is a new InMemoryHistoryStore per server so
    unrelated servers never share history. `state` likewise lets a caller
    inject a CalcState (e.g. one backed by a specific file, to prove
    variables survive a restart); the default is a new in-memory-only
    CalcState() -- no path, so no file is ever created, which is what the
    `--in-memory` run (and this function's own default caller, main())
    relies on.
    """
    host = os.environ.get("HOST", "127.0.0.1")  # the Dockerfile sets 0.0.0.0
    server = HTTPServer((host, port), Handler)
    server.history_store = history_store if history_store is not None else InMemoryHistoryStore()
    server.state = state if state is not None else CalcState()
    return server


# Process lifecycle: the black-box acceptance tests run it against the started app;
# the coverage floor counts in-process code only (M11).
def serve(port, state_path=None):  # pragma: no cover
    """Build the server and run it until interrupted.

    `state_path` is the on-disk file to persist variables, functions,
    history and lists to (plan step P9/S2) -- a CalcState(state_path) and a
    StateBackedHistoryStore built on top of it are passed into build_server,
    so a later process started with the same `state_path` picks up right
    where this one left off. `state_path=None` (main()'s `--in-memory` run)
    instead builds an unpathed CalcState() and a plain InMemoryHistoryStore,
    so nothing here ever touches disk.
    """
    state = CalcState(state_path)
    history_store = InMemoryHistoryStore() if state_path is None else StateBackedHistoryStore(state)
    server = build_server(port, history_store=history_store, state=state)
    host, bound_port = server.server_address[0], server.server_address[1]
    print(f"serving on http://{host}:{bound_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="graphcalc")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--port", type=int, default=None, help="start the HTTP server on this port")
    parser.add_argument(
        "--state",
        default="./graphcalc_state.json",
        help="path to the JSON file variables, functions, history and lists are persisted to "
        "(default: ./graphcalc_state.json)",
    )
    parser.add_argument(
        "--in-memory",
        action="store_true",
        help="keep variables, functions, lists and history in memory only",
    )
    args = parser.parse_args(argv)
    if args.version:
        print(f"graphcalc {__version__}")
        return 0
    if args.port is not None:  # pragma: no cover
        state_path = None if args.in_memory else args.state
        return serve(args.port, state_path)
    parser.print_usage()
    return 2
