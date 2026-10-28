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


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _media_type(content_type_header):
    """The Content-Type value with any ';charset=...' parameter stripped."""
    return content_type_header.split(";", 1)[0].strip()


def test_index_page():
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
    assert parser.tags_by_id["graph-canvas"] == "canvas"
    for element_id in ("tab-calculator", "tab-graphs", "tab-lists", "tab-cas"):
        assert element_id in parser.tags_by_id


def test_static_content_types_js():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/static/app.js") as res:
            assert res.status == 200
            assert _media_type(res.headers.get("Content-Type", "")) == "application/javascript"
    finally:
        server.shutdown()
        server.server_close()


def test_static_content_types_css():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/static/style.css") as res:
            assert res.status == 200
            assert _media_type(res.headers.get("Content-Type", "")) == "text/css"
    finally:
        server.shutdown()
        server.server_close()
