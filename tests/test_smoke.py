import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from graphcalc import __version__
from graphcalc.cli import HEALTH_PATH, Handler, build_server, main


def test_version_flag_prints_the_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"graphcalc {__version__}"


def test_no_arguments_prints_usage():
    assert main([]) == 2


def test_the_app_answers_its_health_path_and_404s_elsewhere():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + HEALTH_PATH) as res:
            assert res.status == 200
            assert json.load(res) == {"status": "ok"}
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(base + "/missing")
        assert missing.value.code == 404
        error_body = json.loads(missing.value.read())
        assert "error" in error_body
    finally:
        server.shutdown()
        server.server_close()


def test_server_binds_only_to_loopback_by_default(monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    server = build_server(0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_version_flag_as_a_real_subprocess_prints_graphcalc_and_the_version():
    result = subprocess.run(
        [sys.executable, "-m", "graphcalc", "--version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"graphcalc {__version__}"


def test_port_and_in_memory_flags_as_a_real_subprocess_serve_health():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "graphcalc", "--port", str(port), "--in-memory"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 10
        last_error = None
        body = None
        status = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{HEALTH_PATH}", timeout=1) as res:
                    status = res.status
                    body = json.load(res)
                break
            except (urllib.error.URLError, ConnectionError) as exc:
                last_error = exc
                time.sleep(0.1)
        else:
            raise AssertionError(f"server never answered /health: {last_error}")
        assert status == 200
        assert body == {"status": "ok"}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
