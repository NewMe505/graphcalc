"""Command line entry point: health endpoint plus the static UI shell.

Serves JSON at /health and the plain HTML/CSS/JS page (and its /static/<name>
assets) that the browser-facing tabs are built on; see Handler.do_GET.
"""

import argparse
import json
import os
import pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

from graphcalc import __version__

HEALTH_PATH = "/health"

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


class Handler(BaseHTTPRequestHandler):
    """The product's only HTTP handler: health check, UI shell, static assets.

    Routes matched on the exact request path (no query-string handling):
    - /health          -> 200 JSON {"status": "ok"}
    - /                -> 200 text/html, the four-tab index page
    - /static/<name>   -> see _serve_static for the allowlist and the
                           traversal/NUL/backslash checks
    - anything else    -> 404 JSON {"error": ...}, never a 500
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
        _send_json(self, 404, {"error": f"not found: {self.path}"})

    def log_message(self, format, *args):
        return


def build_server(port):
    host = os.environ.get("HOST", "127.0.0.1")  # the Dockerfile sets 0.0.0.0
    return HTTPServer((host, port), Handler)


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
