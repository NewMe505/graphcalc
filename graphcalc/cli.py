"""Command line entry point: the walking skeleton with a health endpoint."""

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

    The extension must be in STATIC_CONTENT_TYPES and the resolved path must
    stay inside STATIC_DIR; either failure, or a missing file, is a JSON 404.
    """
    name = unquote(path[len(STATIC_PREFIX) :])
    content_type = STATIC_CONTENT_TYPES.get(pathlib.PurePosixPath(name).suffix)
    if content_type is None:
        _send_json(handler, 404, {"error": f"not found: {path}"})
        return
    try:
        candidate = (STATIC_DIR / name).resolve()
        candidate.relative_to(STATIC_DIR)
        body = candidate.read_bytes()
    except (ValueError, OSError):
        _send_json(handler, 404, {"error": f"not found: {path}"})
        return
    _send_bytes(handler, 200, content_type, body)


class Handler(BaseHTTPRequestHandler):
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
