import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from graphcalc import __version__
from graphcalc.cli import HEALTH_PATH, Handler, main


def test_version_flag_prints_the_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_no_arguments_prints_usage():
    assert main([]) == 2


def test_the_app_answers_its_health_path_and_404s_elsewhere():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + HEALTH_PATH) as res:
            assert json.load(res) == {"status": "ok", "version": __version__}
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(base + "/missing")
        assert missing.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
