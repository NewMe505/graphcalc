import threading
import urllib.request
from html.parser import HTMLParser
from http.server import HTTPServer

from graphcalc.cli import Handler

# The 17 ids plan step P14 adds to the Graphs tab (PRODUCT.md acceptance
# criteria for P14).
GRAPH_IDS = (
    "graph-f1",
    "graph-f2",
    "graph-f3",
    "graph-f4",
    "graph-xmin",
    "graph-xmax",
    "graph-ymin",
    "graph-ymax",
    "graph-zoom-in",
    "graph-zoom-out",
    "graph-pan-left",
    "graph-pan-right",
    "graph-pan-up",
    "graph-pan-down",
    "graph-trace-x",
    "graph-analyze",
    "graph-table",
)

CALC_IDS = (
    "calc-input",
    "calc-mode",
    "calc-submit",
    "calc-error",
    "calc-history",
    "calc-vars",
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


def test_p14_index_graph_ids():
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

    for element_id in GRAPH_IDS:
        assert parser.ids.count(element_id) == 1, f"{element_id} missing or duplicated"

    # The Graphs tab's canvas (added in an earlier plan step) must survive
    # this step's edits untouched.
    assert parser.tags_by_id.get("graph-canvas") == "canvas"

    # The Calculator tab's ids and behaviour must stay unchanged.
    for element_id in CALC_IDS:
        assert element_id in parser.tags_by_id


def test_p14_appjs_graph_paths():
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
        "/api/graph/plot",
        "/api/graph/window",
        "/api/graph/analyze",
        "/api/graph/table",
    ):
        assert path in script, path

    assert "graph-canvas" in script

    # The Calculator tab's own wiring must stay unchanged by this step.
    assert "/api/calc/evaluate" in script
