"""Tests for plan steps P18/S1 and P18/S3: the Lists & Statistics tab's
markup, and app.js's own wiring to all three endpoints it uses.

PRODUCT.md's first P18 acceptance criterion ("GET / contains elements with
ids list-grid, stats-list, stats-output, regression-model, regression-output
and a canvas with id stats-canvas") is a static-content check, the same
style tests/test_p14_graphs_ui.py's own test_p14_index_graph_ids already
uses for the Graphs tab: start the real server, GET /, and check every
required id is present exactly once and that stats-canvas is a <canvas>
element. Plan step S1 also calls for regression-x, regression-y and
regression-run (the dropdowns/button a regression needs beyond what the
acceptance text names explicitly), so those are checked too.

PRODUCT.md's second P18 acceptance criterion ("GET /static/app.js contains
the paths /api/lists, /api/stats/onevar and /api/stats/regression") is
proven by test_p18_app_js_has_lists_stats_paths below, added by plan step
S3 once app.js's own wiring to /api/stats/regression (the last of the
three paths) exists -- the same style test_p14_graphs_ui.py's own
test_p14_appjs_graph_paths already uses for the Graphs tab. The real
browser-driven behaviour both wirings produce is proven separately by
tests/test_p18_lists_browser.py.
"""

import threading
import urllib.request
from html.parser import HTMLParser
from http.server import HTTPServer

from graphcalc.cli import Handler

# The ids plan step P18/S1 adds to the Lists & Statistics tab.
LISTS_STATS_IDS = (
    "list-grid",
    "stats-list",
    "stats-output",
    "regression-model",
    "regression-x",
    "regression-y",
    "regression-run",
    "regression-output",
    "stats-canvas",
)

# The Graphs and Calculator tabs' ids (added by earlier plan steps) must
# survive this step's edits untouched.
GRAPH_IDS = (
    "graph-f1",
    "graph-canvas",
)

CALC_IDS = (
    "calc-input",
    "calc-submit",
)


class _IdCollector(HTMLParser):
    """Collects every element id seen (keeping duplicates) plus its tag.

    Keeping duplicates -- rather than only the last write into a dict --
    lets callers check an id is unique, not merely present.
    """

    def __init__(self):
        super().__init__()
        self.ids = []
        self.tags_by_id = {}

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "id" and value:
                self.ids.append(value)
                self.tags_by_id[value] = tag


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    return server


def test_p18_index_has_lists_stats_ids():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/") as res:
            assert res.status == 200
            assert res.headers.get("Content-Type", "").startswith("text/html")
            html = res.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    parser = _IdCollector()
    parser.feed(html)

    for element_id in LISTS_STATS_IDS:
        assert parser.ids.count(element_id) == 1, f"{element_id} missing or duplicated"

    # stats-canvas must be an actual <canvas> element, the same way the
    # Graphs tab's graph-canvas is -- a plain <div id="stats-canvas"> would
    # pass a bare id-presence check but could never be drawn on.
    assert parser.tags_by_id.get("stats-canvas") == "canvas"

    # The Graphs and Calculator tabs' ids and behaviour must stay unchanged.
    for element_id in GRAPH_IDS:
        assert element_id in parser.tags_by_id
    for element_id in CALC_IDS:
        assert element_id in parser.tags_by_id


def test_p18_app_js_has_lists_stats_paths():
    """Plan step P18/S3: app.js wires the tab to all three endpoints.

    Same style as tests/test_p14_graphs_ui.py's own
    test_p14_appjs_graph_paths: GET /static/app.js and check every path
    the Lists & Statistics tab's own wiring (plan steps P18/S2 and P18/S3)
    POSTs/GETs to is present as a literal string.
    """
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/static/app.js") as res:
            assert res.status == 200
            script = res.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    for path in (
        "/api/lists",
        "/api/stats/onevar",
        "/api/stats/regression",
    ):
        assert path in script, path

    # The Graphs and Calculator tabs' own wiring must stay unchanged.
    assert "/api/graph/plot" in script
    assert "/api/calc/evaluate" in script
