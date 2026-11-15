"""Tests for plan step P9/S1: CalcState as the single persisted store for
variables, functions, lists and history, and graphcalc.history.
StateBackedHistoryStore, which writes history through that same file.

F2 (PRODUCT.md, [failing] before this step): "The state file S parses as
valid JSON after every change." This file proves that directly -- after a
variable definition, a function definition, a plain evaluation (which
appends to history), a history clear, and a full reset, the file on disk
still parses with json.loads() and still has the "variables", "functions",
"lists" and "history" keys every one of those operations is documented to
touch or leave alone.

The tests above only exercise graphcalc.state.CalcState and
graphcalc.history.StateBackedHistoryStore directly, the same way
tests/test_calc_definitions.py's own disk-persistence tests inject a
path-backed CalcState into build_server(). graphcalc/cli.py's --state PATH
and --in-memory wiring (plan step P9/S2) is exercised below instead, by
test_p9_restart_persists_variable, through a real `python -m graphcalc`
subprocess -- the actual F1 acceptance check (PRODUCT.md): "After 'a:=5'
with --state S, restarting the server with the same --state S and
evaluating 'a' returns exact '5'". POST /api/state/reset and the
.gitignore entry are still a later step of the same plan (P9).
"""

import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from graphcalc.cli import HEALTH_PATH, build_server
from graphcalc.history import StateBackedHistoryStore
from graphcalc.state import CalcState

REQUIRED_KEYS = {"variables", "functions", "lists", "history"}


def _post(base, path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def _delete(base, path):
    req = urllib.request.Request(base + path, method="DELETE")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def _start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


def _stop(server):
    server.shutdown()
    server.server_close()


def _read_state_file(path):
    """json.loads() the file at `path` and assert its basic shape.

    This is the F2 assertion itself ("the state file parses as valid
    JSON"): json.load() raising here is this test's failure, not something
    it catches.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, dict), data
    assert REQUIRED_KEYS <= set(data.keys()), data
    assert isinstance(data["variables"], dict), data
    assert isinstance(data["functions"], dict), data
    assert isinstance(data["lists"], dict), data
    assert isinstance(data["history"], list), data
    return data


# ---- F2: the state file stays valid JSON, with the right keys, after
# every kind of change CalcState and StateBackedHistoryStore make ----


def test_p9_state_file_valid_json_after_each_change(tmp_path):
    path = str(tmp_path / "state.json")
    state = CalcState(path)
    srv = build_server(0, history_store=StateBackedHistoryStore(state), state=state)
    base = _start(srv)
    try:
        # Define a variable: "variables" gains "a", and the definition is
        # also appended to history (plan step P32).
        status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
        assert status == 200, body
        data = _read_state_file(path)
        assert data["variables"]["a"] == "5", data
        assert len(data["history"]) == 1, data

        # Define a function: "functions" gains "f".
        status, body = _post(base, "/api/calc/evaluate", {"expr": "f(x):=x+1"})
        assert status == 200, body
        data = _read_state_file(path)
        assert "f" in data["functions"], data
        assert len(data["history"]) == 2, data

        # A plain evaluation appends to history without touching
        # variables/functions.
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body
        data = _read_state_file(path)
        assert len(data["history"]) == 3, data
        assert data["variables"]["a"] == "5", data
        assert "f" in data["functions"], data

        # Clear history: DELETE /api/calc/history empties history (and
        # "ans") through the same StateBackedHistoryStore -> CalcState path,
        # leaving variables/functions alone.
        status, body = _delete(base, "/api/calc/history")
        assert status == 200, body
        assert body == {"history": []}, body
        data = _read_state_file(path)
        assert data["history"] == [], data
        assert data["variables"]["a"] == "5", data
        assert "f" in data["functions"], data

        # Re-populate, then reset(): everything empties in one save.
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        state.reset()
        data = _read_state_file(path)
        assert data["variables"] == {}, data
        assert data["functions"] == {}, data
        assert data["lists"] == {}, data
        assert data["history"] == [], data
    finally:
        _stop(srv)


# ---- A missing, corrupt or wrong-shape state file must never raise, and
# must never block evaluation (bug #14) ----


def test_p9_state_file_valid_json_after_corrupt_file_allows_evaluation(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not valid json at all", encoding="utf-8")

    state = CalcState(str(path))  # must not raise despite the garbage above
    srv = build_server(0, history_store=StateBackedHistoryStore(state), state=state)
    base = _start(srv)
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body

        status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
        assert status == 200, body
        assert body["exact"] == "5", body
    finally:
        _stop(srv)

    # The very next change overwrites the garbage with a valid file.
    data = _read_state_file(str(path))
    assert data["variables"]["a"] == "5", data


def test_p9_state_file_valid_json_after_wrong_shape_file_allows_evaluation(tmp_path):
    path = tmp_path / "state.json"
    # Valid JSON, but the top level is a list, not an object -- and
    # "variables" inside it (further down) would not even apply, since
    # there is no object to key into at all.
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    state = CalcState(str(path))  # must not raise
    srv = build_server(0, history_store=StateBackedHistoryStore(state), state=state)
    base = _start(srv)
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body
    finally:
        _stop(srv)

    data = _read_state_file(str(path))
    assert len(data["history"]) == 1, data


# ---- F1: a variable defined before a restart is still there after one,
# through the real `python -m graphcalc` CLI subprocess (--state), not an
# in-process CalcState/build_server() injection like the tests above ----


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_for_health(port, timeout=10):
    """Poll /health until it answers, or raise after `timeout` seconds."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{HEALTH_PATH}", timeout=1) as res:
                return res.status, json.loads(res.read().decode("utf-8"))
        except (urllib.error.URLError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"server never answered /health: {last_error}")


def _start_cli_subprocess(port, state_path):
    return subprocess.Popen(
        [sys.executable, "-m", "graphcalc", "--port", str(port), "--state", state_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_cli_subprocess(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def test_p9_restart_persists_variable(tmp_path):
    """F1 (PRODUCT.md): after "a:=5" with --state S, restarting the server
    with the same --state S and evaluating "a" returns exact "5".

    Unlike every other test in this file, this one does not inject a
    path-backed CalcState into build_server() directly -- it starts the
    real CLI (`python -m graphcalc --port P --state S`) as a subprocess,
    twice, on the same state file, which is the only way to actually prove
    graphcalc/cli.py's --state wiring (plan step P9/S2) works end to end.
    The first process is always terminated (in a finally block) before the
    second one starts, so the file's own atomic write -- not two processes
    racing on it -- is what carries "a" across the restart.
    """
    state_path = str(tmp_path / "s.json")

    port1 = _free_port()
    proc1 = _start_cli_subprocess(port1, state_path)
    try:
        _wait_for_health(port1)
        status, body = _post(f"http://127.0.0.1:{port1}", "/api/calc/evaluate", {"expr": "a:=5"})
        assert status == 200, body
        assert body["exact"] == "5", body
    finally:
        _stop_cli_subprocess(proc1)

    port2 = _free_port()
    proc2 = _start_cli_subprocess(port2, state_path)
    try:
        _wait_for_health(port2)
        status, body = _post(f"http://127.0.0.1:{port2}", "/api/calc/evaluate", {"expr": "a"})
        assert status == 200, body
        assert body["exact"] == "5", body
    finally:
        _stop_cli_subprocess(proc2)


def test_p9_state_file_valid_json_after_wrong_shape_field_allows_evaluation(tmp_path):
    path = tmp_path / "state.json"
    # Valid JSON object, but "variables" itself is the wrong shape (a plain
    # string instead of an object) -- a hand-edit mistake distinct from the
    # whole-file cases above.
    path.write_text(json.dumps({"variables": "oops", "history": "also oops"}), encoding="utf-8")

    state = CalcState(str(path))  # must not raise
    srv = build_server(0, history_store=StateBackedHistoryStore(state), state=state)
    base = _start(srv)
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body
    finally:
        _stop(srv)

    data = _read_state_file(str(path))
    assert len(data["history"]) == 1, data
