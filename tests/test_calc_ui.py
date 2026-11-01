"""Tests for the Calculator tab's wiring to the calculator endpoints (P8).

PRODUCT.md's two acceptance criteria are both static-content checks, not
behavioral ones (there is no in-process JS engine in this test suite):
GET / must contain elements with the six calc-* ids, and GET /static/app.js
must mention the three API paths it calls them against. The actual fetch()
wiring in graphcalc/static/app.js (POST /api/calc/evaluate, GET/DELETE-free
GET /api/calc/history, GET /api/calc/vars) is exercised end to end by the
acceptance suite / a real browser, not by this file.
"""

import threading
from html.parser import HTMLParser
from http.server import HTTPServer
from urllib.request import urlopen

from graphcalc.cli import Handler

CALC_UI_IDS = (
    "calc-input",
    "calc-mode",
    "calc-submit",
    "calc-history",
    "calc-vars",
    "calc-error",
)

CALC_API_PATHS = (
    "/api/calc/evaluate",
    "/api/calc/history",
    "/api/calc/vars",
)


class _IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "id" and value:
                self.ids.add(value)


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_index_page_has_calculator_tab_elements():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/") as res:
            assert res.status == 200
            html = res.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    parser = _IdCollector()
    parser.feed(html)
    for element_id in CALC_UI_IDS:
        assert element_id in parser.ids, element_id


def test_app_js_references_calculator_endpoints():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/static/app.js") as res:
            assert res.status == 200
            script = res.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    for path in CALC_API_PATHS:
        assert path in script, path
