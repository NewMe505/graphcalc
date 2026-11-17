"""Tests for plan step P18/S1: the Lists & Statistics tab's markup.

PRODUCT.md's first P18 acceptance criterion ("GET / contains elements with
ids list-grid, stats-list, stats-output, regression-model, regression-output
and a canvas with id stats-canvas") is a static-content check, the same
style tests/test_p14_graphs_ui.py's own test_p14_index_graph_ids already
uses for the Graphs tab: start the real server, GET /, and check every
required id is present exactly once and that stats-canvas is a <canvas>
element. Plan step S1 also calls for regression-x, regression-y and
regression-run (the dropdowns/button a regression needs beyond what the
acceptance text names explicitly), so those are checked too. Wiring this
markup to /api/lists, /api/stats/onevar and
/api/stats/regression (the rest of P18) is a later step -- this file only
proves the markup itself exists, same as test_p14_graphs_ui.py's own id
test proves the Graphs tab's markup before that step's app.js wiring.
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
