import threading
import urllib.request
from html.parser import HTMLParser
from http.server import HTTPServer

from graphcalc.cli import Handler


class _IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags_by_id = {}

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "id" and value:
                self.tags_by_id[value] = tag


def test_index_page():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
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
    assert parser.tags_by_id["graph-canvas"] == "canvas"
    for element_id in ("tab-calculator", "tab-graphs", "tab-lists", "tab-cas"):
        assert element_id in parser.tags_by_id
