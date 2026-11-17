"""Tests for plan step P22/S1: the CAS tab's markup.

PRODUCT.md's first P22 acceptance criterion ("GET / contains elements with
ids cas-input, cas-var, cas-op, cas-submit and cas-output") is a
static-content check, the same style tests/test_p18_lists_ui.py's own
test_p18_index_has_lists_stats_ids and tests/test_p14_graphs_ui.py's own
test_p14_index_graph_ids already use for their own tabs: start the real
server, GET /, and check every required id is present exactly once.

This step only adds the markup (plan step S1); app.js's own wiring to the
seven /api/cas/* endpoints is a later step and is not tested here. The page
must still load no external resources, the same way tests/test_static.py's
own test_static_security_no_external_urls already checks for the whole
page -- this module re-checks it narrowly against the CAS panel's own
markup so a regression there is caught right where it was introduced.
"""

import re
import threading
import urllib.request
from html.parser import HTMLParser
from http.server import HTTPServer
from urllib.parse import urlsplit

from graphcalc.cli import Handler

# The ids plan step P22/S1 adds to the CAS tab (PRODUCT.md acceptance
# criteria for P22).
CAS_IDS = (
    "cas-input",
    "cas-var",
    "cas-op",
    "cas-submit",
    "cas-output",
)

# The other tabs' ids (added by earlier plan steps) must survive this
# step's edits untouched.
GRAPH_IDS = (
    "graph-f1",
    "graph-canvas",
)

CALC_IDS = (
    "calc-input",
    "calc-submit",
)

LISTS_IDS = (
    "list-grid",
    "stats-output",
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


def _get_index_html():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/") as res:
            assert res.status == 200
            assert res.headers.get("Content-Type", "").startswith("text/html")
            return res.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()


def test_index_has_cas_elements():
    html = _get_index_html()

    parser = _IdCollector()
    parser.feed(html)

    for element_id in CAS_IDS:
        assert parser.ids.count(element_id) == 1, f"{element_id} missing or duplicated"

    # cas-op must offer all seven ops, as plain <option> values.
    op_select_start = html.index('id="cas-op"')
    op_select_end = html.index("</select>", op_select_start)
    op_select_html = html[op_select_start:op_select_end]
    for op in ("simplify", "expand", "factor", "derivative", "integral", "limit", "solve"):
        assert f'value="{op}"' in op_select_html, op

    # The other tabs' ids and behaviour must stay unchanged.
    for element_id in GRAPH_IDS:
        assert element_id in parser.tags_by_id
    for element_id in CALC_IDS:
        assert element_id in parser.tags_by_id
    for element_id in LISTS_IDS:
        assert element_id in parser.tags_by_id

    # No external http(s) resource (script/link/img/etc.) anywhere on the
    # page -- the CAS panel must not have introduced one.
    url_pattern = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)
    for url in url_pattern.findall(html):
        assert urlsplit(url).hostname == "127.0.0.1", url


def test_cas_output_wraps_long_text():
    """P33: long CAS output must wrap rather than widen the page.

    cas-output carries its own inline white-space/overflow-wrap styling
    (plan step P22/S1) rather than relying solely on the page-wide rule
    (graphcalc/static/style.css), because CAS results can contain
    newlines (e.g. several solutions) that plain wrapping would collapse;
    white-space: pre-wrap keeps those line breaks while still letting a
    long unbroken run break via overflow-wrap: anywhere.
    """
    html = _get_index_html()

    output_start = html.index('id="cas-output"')
    tag_end = html.index(">", output_start)
    tag_html = html[max(0, output_start - 50) : tag_end]

    assert "white-space" in tag_html and "pre-wrap" in tag_html, tag_html
    assert "overflow-wrap" in tag_html and "anywhere" in tag_html, tag_html
