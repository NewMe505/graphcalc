import http.client
import json
import re
import threading
import urllib.request
from html.parser import HTMLParser
from http.server import HTTPServer
from urllib.parse import urlsplit

import graphcalc.cli as cli
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


def _raw_get(port, raw_path):
    """GET raw_path over http.client, bypassing any client-side normalization."""
    conn = http.client.HTTPConnection("127.0.0.1", port)
    try:
        conn.putrequest("GET", raw_path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", "127.0.0.1")
        conn.endheaders()
        res = conn.getresponse()
        status = res.status
        body = res.read()
    finally:
        conn.close()
    return status, body


def test_static_security_traversal():
    server = _start_server()
    try:
        port = server.server_port
        for raw_path in (
            "/static/../server.py",
            "/static/%2e%2e/server.py",
            "/static/..%2fserver.py",
            "/static/%2e%2e%5cserver.py",
        ):
            status, body = _raw_get(port, raw_path)
            assert status == 404, raw_path
            payload = json.loads(body.decode("utf-8"))
            assert "error" in payload, raw_path
    finally:
        server.shutdown()
        server.server_close()


def test_static_security_escapes_allowed_extension(tmp_path, monkeypatch):
    """A traversal to a same-extension file outside STATIC_DIR must still 404.

    The four paths in test_static_security_traversal all target "server.py",
    an extension STATIC_CONTENT_TYPES never allows, so they 404 before the
    resolve()/is_relative_to() containment check ever runs. This test points
    the traversal at a sibling ".js" file -- an allowed extension -- so the
    containment check is the thing actually stopping it.
    """
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    # Use write_bytes, not write_text: on Windows, write_text's default text
    # mode would translate "\n" to "\r\n", corrupting the byte-exact
    # assertion below.
    (static_dir / "ok.js").write_bytes(b"// inside\n")
    (tmp_path / "secret.js").write_bytes(b"// outside\n")
    monkeypatch.setattr(cli, "STATIC_DIR", static_dir)

    server = _start_server()
    try:
        port = server.server_port
        status, body = _raw_get(port, "/static/ok.js")
        assert status == 200
        assert body == b"// inside\n"

        for raw_path in (
            "/static/../secret.js",
            "/static/%2e%2e/secret.js",
            "/static/..%2fsecret.js",
            "/static/%2e%2e%5csecret.js",
        ):
            status, body = _raw_get(port, raw_path)
            assert status == 404, raw_path
            payload = json.loads(body.decode("utf-8"))
            assert "error" in payload, raw_path
    finally:
        server.shutdown()
        server.server_close()


def test_unknown_routes_are_json_404_not_500():
    server = _start_server()
    try:
        port = server.server_port
        for raw_path in ("/server.py", "/does-not-exist", "/static/"):
            status, body = _raw_get(port, raw_path)
            assert status == 404, raw_path
            payload = json.loads(body.decode("utf-8"))
            assert "error" in payload, raw_path
    finally:
        server.shutdown()
        server.server_close()


def test_static_security_no_external_urls():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        texts = []
        for route in ("/", "/static/app.js", "/static/style.css"):
            with urllib.request.urlopen(base + route) as res:
                assert res.status == 200
                texts.append(res.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()

    url_pattern = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)
    for text in texts:
        for url in url_pattern.findall(text):
            assert urlsplit(url).hostname == "127.0.0.1", url
