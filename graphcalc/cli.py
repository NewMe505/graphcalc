"""Command line entry point: health endpoint, static UI shell, calc API.

Serves JSON at /health and the plain HTML/CSS/JS page (and its /static/<name>
assets) that the browser-facing tabs are built on; see Handler.do_GET. The
math API lives under /api/calc/... -- see Handler.do_POST and
_handle_calc_evaluate for POST /api/calc/evaluate, which defers the actual
parsing and evaluation to graphcalc.calc. Every successful evaluation is
appended to a graphcalc.history.HistoryStore held on the HTTPServer instance
(see build_server and _history_store); GET /api/calc/history reads it back,
and DELETE /api/calc/history clears it (see Handler.do_DELETE and
_handle_calc_history_delete).

A "name:=expr" input (graphcalc.calc.parse_definition) is detected before
the normal evaluate path and stores the result in a graphcalc.state.CalcState
held on the HTTPServer instance (see build_server and _state), separate from
the history store -- history and state are not yet unified behind one
object; that is a later feature (P9).
"""

import argparse
import json
import os
import pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

from graphcalc import __version__
from graphcalc.history import InMemoryHistoryStore
from graphcalc.state import CalcState

HEALTH_PATH = "/health"
CALC_EVALUATE_PATH = "/api/calc/evaluate"
CALC_HISTORY_PATH = "/api/calc/history"

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

    After this, "ans" in a later /api/calc/evaluate has no last entry to
    recall: calc.evaluate raises CalcError("ans is undefined"), which
    _handle_calc_evaluate turns into the usual 400, never a 500.
    """
    _history_store(handler).clear()
    _send_json(handler, 200, {"history": []})


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
    "name:=expr" assignment (plan step P7/S1; "f(x):=expr" function
    definitions are a separate, later step). When it is: names.check_not_
    constant(name) first rejects a reserved name (-> 400 "cannot redefine
    constant <name>"), then the right-hand side is evaluated the same way
    as any other expr (so it also sees previously stored variables), and --
    only when that evaluation has no domain_error -- the result's exact
    value is stored under name in the HTTPServer's CalcState. The response
    is calc.evaluate's own dict with "expr" replaced by the original
    "name:=expr" text. A definition is not added to the history store; "ans"
    only ever recalls a plain evaluation's result.

    Everything above is wrapped in a catch-all: any exception this function
    did not anticipate (e.g. something calc.evaluate's own try/except does
    not cover) is still turned into a JSON 400, never left to propagate into
    a 500. This handler must never answer with a 500.
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
                    last_entry=_history_store(handler).last(),
                    variables=_state(handler).variables(),
                )
            except calc.CalcError as exc:
                _send_json(handler, 400, {"error": str(exc)})
                return
            if result["exact"] is not None:
                _state(handler).set_variable(name, result["exact"])
            response = dict(result)
            response["expr"] = expr
            _send_json(handler, 200, response)
            return

        try:
            result = calc.evaluate(
                expr,
                mode,
                last_entry=_history_store(handler).last(),
                variables=_state(handler).variables(),
            )
        except calc.CalcError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return
        if result["domain_error"] is None:
            _history_store(handler).append(
                {"expr": expr, "exact": result["exact"], "decimal": result["decimal"]}
            )
        _send_json(handler, 200, result)
    except Exception as exc:  # catch-all: this endpoint must never answer with a 500
        _send_json(handler, 400, {"error": f"unexpected error: {exc}"})


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
        _send_json(self, 404, {"error": f"not found: {self.path}"})

    def do_POST(self):
        if self.path == CALC_EVALUATE_PATH:
            _handle_calc_evaluate(self)
            return
        _send_json(self, 404, {"error": f"not found: {self.path}"})

    def do_DELETE(self):
        if self.path == CALC_HISTORY_PATH:
            _handle_calc_history_delete(self)
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
def serve(port):  # pragma: no cover
    server = build_server(port)
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
        "--in-memory",
        action="store_true",
        help="keep variables, functions, lists and history in memory only",
    )
    args = parser.parse_args(argv)
    if args.version:
        print(f"graphcalc {__version__}")
        return 0
    if args.port is not None:  # pragma: no cover
        return serve(args.port)
    parser.print_usage()
    return 2
