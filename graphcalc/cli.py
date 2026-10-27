"""Command line entry point: the walking skeleton with a health endpoint."""

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from graphcalc import __version__

HEALTH_PATH = "/health"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == HEALTH_PATH:
            body = json.dumps({"status": "ok", "version": __version__}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


# Process lifecycle: the black-box acceptance tests run it against the started app;
# the coverage floor counts in-process code only (M11).
def serve(port):  # pragma: no cover
    host = os.environ.get("HOST", "127.0.0.1")  # the Dockerfile sets 0.0.0.0
    server = HTTPServer((host, port), Handler)
    print(f"serving on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="graphcalc")
    parser.add_argument("--version", action="store_true", help="print the version")
    sub = parser.add_subparsers(dest="cmd")
    run = sub.add_parser("serve", help="start the HTTP server")
    run.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.cmd == "serve":  # pragma: no cover
        return serve(args.port)
    parser.print_usage()
    return 2
