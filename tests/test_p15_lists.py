"""Tests for plan step P15/S1: named-list CRUD over /api/lists.

F1 (PRODUCT.md, [failing] before this step): 'PUT /api/lists/L1
{"values":["1","2","3"]} returns 200, GET /api/lists/L1 returns
{"name":"L1","values":["1","2","3"]}, and GET /api/lists returns
{"lists":[names]}.' test_lists_crud_put, test_lists_crud_get_one and
test_lists_crud_get_all prove each half, through graphcalc.cli.Handler's
real routes (do_PUT/do_GET), against an in-process server built the same
way tests/test_p13_graph_table.py's own `server`/`base` fixtures build one.

F2 (PRODUCT.md, [failing] before this step): 'DELETE /api/lists/L1 returns
200 {"deleted":"L1"} then GET returns 404; PUT with a value of "abc+" or a
list name not matching [A-Za-z][A-Za-z0-9_]{0,15} returns 400.'
test_lists_delete_validation_delete_then_404 proves the first half;
test_lists_delete_validation_bad_value, test_lists_delete_validation_bad_name
(parametrized over every shape graphcalc.lists.LIST_NAME_RE rejects: a
leading digit, a leading underscore, one character too long, a disallowed
character, and an empty name) and
test_lists_delete_validation_bad_values_field (a missing "values" key and a
non-list "values" value) prove the second half -- each case a JSON 400,
never a 500.

F3 (PRODUCT.md, plan step P15/S2): "Lists survive a restart with the same
--state S, and POST /api/state/reset empties them."
test_lists_persist_restart_across_server_restart proves the first half,
through a real `python -m graphcalc --state S` subprocess started twice on
the same state file -- the same pattern tests/test_p9_state_persistence.py's
own test_p9_restart_persists_variable uses for a variable, now for a PUT
/api/lists/<name> list instead. test_lists_persist_reset_empties_lists
proves the second half, through an in-process server backed by a
path-backed CalcState -- the same pattern test_p9_state_persistence.py's
own test_p9_state_reset_empties_everything uses -- checking both the API
(GET /api/lists, GET /api/lists/<name>) and the state file on disk.
test_lists_persist_corrupted_entries_skipped_allows_evaluation proves the
P26 "stored data never breaks later evaluations" rule, extended to lists by
P15/S2's graphcalc.state._coerce_lists_dict: a hand-written state file with
several differently-malformed "lists" entries (two bad names, a non-list
value and a dict value, and a list of non-string items), alongside one
well-formed list, still lets the server start, still evaluates a plain
expression, and still serves the one well-formed list -- while every
malformed entry is simply absent, never raised over.
test_lists_persist_non_dict_lists_field_allows_evaluation proves the same
rule for the coarser case where the whole "lists" field is not even a
dict. test_lists_persist_calcstate_coerce is a fast, server-free unit check
of _coerce_lists_dict directly, on the same hand-written bad entries.

F4 (PRODUCT.md, plan step P15/S3): "With L1 = [1,2,3], evaluating
"2*L1+1" returns exact "[3, 5, 7]"." test_lists_evaluate_scalar_broadcast
proves exactly that example through the real POST /api/calc/evaluate
route. test_lists_evaluate_two_lists_elementwise proves "L1+L1" ->
"[2, 4, 6]" (two same-length lists combine elementwise, not just a list
with a literal scalar). test_lists_evaluate_mismatched_lengths_400 proves
two differently-sized lists used together is a 400, never a 500 or a
best-effort partial answer. test_lists_evaluate_regression_plain_expr_
unchanged and test_lists_evaluate_regression_stored_variable_unchanged are
the required regression check: an expression that uses no list at all --
a plain expression, and one that references a previously stored plain
variable -- must evaluate exactly as it did before this step, through the
same server that now also has a stored list sitting unused in its state.
"""

import json
import pathlib
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from graphcalc.cli import HEALTH_PATH, build_server
from graphcalc.history import StateBackedHistoryStore
from graphcalc.state import CalcState

# graphcalc is not pip-installed in this environment -- `python -m graphcalc`
# only resolves the package because the repo root happens to be on sys.path
# (the implicit cwd entry `-m` adds) when a subprocess inherits this test
# runner's own cwd, the same reasoning tests/test_p9_state_persistence.py's
# own REPO_ROOT/_start_cli_subprocess give for why that file's restart test
# never sets `cwd=`.
REPO_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


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


def _put(base, path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def _get(base, path):
    req = urllib.request.Request(base + path, method="GET")
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


@pytest.fixture
def server():
    """A fresh server with a default (in-memory) history store and state.

    Each test gets its own server/state, so one test's stored lists never
    leak into another -- the same per-test isolation
    tests/test_p13_graph_table.py's own `server` fixture gives its tests.
    """
    srv = build_server(0)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def base(server):
    return f"http://127.0.0.1:{server.server_port}"


# ---- F1: PUT creates/overwrites a list, GET reads one back, GET /api/lists
# lists every name ----


def test_lists_crud_put(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body
    assert body == {"name": "L1", "values": ["1", "2", "3"]}, body


def test_lists_crud_put_overwrites(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body

    status, body = _put(base, "/api/lists/L1", {"values": ["9", "8"]})
    assert status == 200, body
    assert body == {"name": "L1", "values": ["9", "8"]}, body

    status, body = _get(base, "/api/lists/L1")
    assert status == 200, body
    assert body == {"name": "L1", "values": ["9", "8"]}, body


def test_lists_crud_get_one(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body

    status, body = _get(base, "/api/lists/L1")
    assert status == 200, body
    assert body == {"name": "L1", "values": ["1", "2", "3"]}, body


def test_lists_crud_get_one_missing_is_404(base):
    status, body = _get(base, "/api/lists/NOPE")
    assert status == 404, body
    assert "error" in body, body


def test_lists_crud_get_all(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body
    status, body = _put(base, "/api/lists/L2", {"values": ["4", "5"]})
    assert status == 200, body

    status, body = _get(base, "/api/lists")
    assert status == 200, body
    assert body == {"lists": ["L1", "L2"]}, body


def test_lists_crud_get_all_empty(base):
    status, body = _get(base, "/api/lists")
    assert status == 200, body
    assert body == {"lists": []}, body


# ---- F2: DELETE then 404; bad values/names all 400 ----


def test_lists_delete_validation_delete_then_404(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body

    status, body = _delete(base, "/api/lists/L1")
    assert status == 200, body
    assert body == {"deleted": "L1"}, body

    status, body = _get(base, "/api/lists/L1")
    assert status == 404, body
    assert "error" in body, body


def test_lists_delete_validation_delete_missing_is_404(base):
    status, body = _delete(base, "/api/lists/NOPE")
    assert status == 404, body
    assert "error" in body, body


def test_lists_delete_validation_bad_value(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "abc+", "3"]})
    assert status == 400, body
    assert "error" in body, body


def test_lists_delete_validation_bad_value_non_string(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", 2, "3"]})
    assert status == 400, body
    assert "error" in body, body


@pytest.mark.parametrize(
    "name",
    [
        "1L",  # leading digit
        "_L",  # leading underscore
        "a" * 17,  # one character too long (max is 16)
        "L-1",  # disallowed character
        "",  # empty name
    ],
)
def test_lists_delete_validation_bad_name(base, name):
    status, body = _put(base, f"/api/lists/{name}", {"values": ["1", "2", "3"]})
    assert status == 400, body
    assert "error" in body, body


def test_lists_delete_validation_missing_values_field(base):
    status, body = _put(base, "/api/lists/L1", {})
    assert status == 400, body
    assert "error" in body, body


def test_lists_delete_validation_non_list_values_field(base):
    status, body = _put(base, "/api/lists/L1", {"values": "1,2,3"})
    assert status == 400, body
    assert "error" in body, body


# ---- F3: lists survive a restart with the same --state S, and POST
# /api/state/reset empties them ----


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


def test_lists_persist_restart_across_server_restart(tmp_path):
    """F3 (PRODUCT.md): "Lists survive a restart with the same --state S."

    A real `python -m graphcalc --state S` subprocess, started twice on the
    same state file -- the same pattern tests/test_p9_state_persistence.py's
    own test_p9_restart_persists_variable uses for a variable, now proving
    it for a PUT /api/lists/<name> list instead. The first process is always
    terminated (in a finally block) before the second one starts, so the
    file's own atomic write -- not two processes racing on it -- is what
    carries "L1" across the restart.
    """
    state_path = str(tmp_path / "s.json")

    port1 = _free_port()
    proc1 = _start_cli_subprocess(port1, state_path)
    try:
        _wait_for_health(port1)
        base1 = f"http://127.0.0.1:{port1}"
        status, body = _put(base1, "/api/lists/L1", {"values": ["1", "2", "3"]})
        assert status == 200, body
        assert body == {"name": "L1", "values": ["1", "2", "3"]}, body
    finally:
        _stop_cli_subprocess(proc1)

    port2 = _free_port()
    proc2 = _start_cli_subprocess(port2, state_path)
    try:
        _wait_for_health(port2)
        base2 = f"http://127.0.0.1:{port2}"
        status, body = _get(base2, "/api/lists/L1")
        assert status == 200, body
        assert body == {"name": "L1", "values": ["1", "2", "3"]}, body

        status, body = _get(base2, "/api/lists")
        assert status == 200, body
        assert body == {"lists": ["L1"]}, body
    finally:
        _stop_cli_subprocess(proc2)


def test_lists_persist_reset_empties_lists(tmp_path):
    """F3 (PRODUCT.md): "POST /api/state/reset empties them."

    An in-process server backed by a path-backed CalcState -- the same
    pattern tests/test_p9_state_persistence.py's own
    test_p9_state_reset_empties_everything uses -- checking both the API
    (GET /api/lists, GET /api/lists/<name>) and the state file on disk, then
    restarting on the same path to prove the reset was actually saved, not
    just reflected in the now-stopped server's in-memory state.
    """
    path = str(tmp_path / "state.json")
    state = CalcState(path)
    srv = build_server(0, history_store=StateBackedHistoryStore(state), state=state)
    base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
        assert status == 200, body

        status, body = _post(base, "/api/state/reset", {})
        assert status == 200, body
        assert body == {"status": "reset"}, body

        status, body = _get(base, "/api/lists")
        assert status == 200, body
        assert body == {"lists": []}, body

        status, body = _get(base, "/api/lists/L1")
        assert status == 404, body
        assert "error" in body, body

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["lists"] == {}, data
    finally:
        srv.shutdown()
        srv.server_close()

    state2 = CalcState(path)
    srv2 = build_server(0, history_store=StateBackedHistoryStore(state2), state=state2)
    base2 = f"http://127.0.0.1:{srv2.server_port}"
    threading.Thread(target=srv2.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        status, body = _get(base2, "/api/lists")
        assert status == 200, body
        assert body == {"lists": []}, body
    finally:
        srv2.shutdown()
        srv2.server_close()


# ---- F3 / P26 extended to lists: a corrupted "lists" entry (or field)
# must never block the server starting, a plain evaluation, or a
# different, well-formed list stored alongside it ----

_CORRUPTED_LISTS_FIELD = {
    "L1": ["1", "2", "3"],  # well-formed -- must survive
    "1bad": ["1", "2"],  # bad name: leading digit
    "bad name": ["1", "2"],  # bad name: disallowed character (and a space)
    "L2": "notalist",  # value is not a list at all
    "L3": [1, 2],  # list of non-string items
    "L4": {"a": 1},  # value is a dict, not a list
}


def test_lists_persist_corrupted_entries_skipped_allows_evaluation(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"lists": _CORRUPTED_LISTS_FIELD}), encoding="utf-8")

    state = CalcState(str(path))  # must not raise despite the garbage above
    srv = build_server(0, history_store=StateBackedHistoryStore(state), state=state)
    base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body

        status, body = _get(base, "/api/lists")
        assert status == 200, body
        assert body == {"lists": ["L1"]}, body

        status, body = _get(base, "/api/lists/L1")
        assert status == 200, body
        assert body == {"name": "L1", "values": ["1", "2", "3"]}, body
    finally:
        srv.shutdown()
        srv.server_close()


def test_lists_persist_non_dict_lists_field_allows_evaluation(tmp_path):
    """Same P26-for-lists rule as above, but the whole "lists" field itself
    is the wrong JSON type (a bare number, not even a dict) -- the
    whole-field fallback _coerce_lists_dict shares with _coerce_dict, not
    the per-entry checks _CORRUPTED_LISTS_FIELD exercises above.
    """
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"lists": 5}), encoding="utf-8")

    state = CalcState(str(path))  # must not raise
    srv = build_server(0, history_store=StateBackedHistoryStore(state), state=state)
    base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        assert status == 200, body
        assert body["exact"] == "2", body

        status, body = _get(base, "/api/lists")
        assert status == 200, body
        assert body == {"lists": []}, body
    finally:
        srv.shutdown()
        srv.server_close()


def test_lists_persist_calcstate_coerce(tmp_path):
    """Fast unit-level check of graphcalc.state._coerce_lists_dict, with no
    server involved: CalcState built straight from a hand-written dict with
    the same bad entries as above, plus a list containing a non-string
    `None` item, comes back with only the one well-formed list.
    """
    path = tmp_path / "state.json"
    lists_field = dict(_CORRUPTED_LISTS_FIELD)
    lists_field["L5"] = [None]
    path.write_text(json.dumps({"lists": lists_field}), encoding="utf-8")

    state = CalcState(str(path))
    assert state.lists() == {"L1": ["1", "2", "3"]}, state.lists()


# ---- F4: a stored list is usable in /api/calc/evaluate ----


def test_lists_evaluate_scalar_broadcast(base):
    """PRODUCT.md's own example: L1 = [1, 2, 3], "2*L1+1" -> exact
    "[3, 5, 7]" -- the literal scalars "2" and "1" broadcast across every
    element of L1.
    """
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body

    status, body = _post(base, "/api/calc/evaluate", {"expr": "2*L1+1"})
    assert status == 200, body
    assert body["exact"] == "[3, 5, 7]", body
    assert body["domain_error"] is None, body


def test_lists_evaluate_two_lists_elementwise(base):
    """Two lists of the same length (here, the same list used twice)
    combine elementwise, not as some other broadcast or cross-product:
    L1 = [1, 2, 3], "L1+L1" -> "[2, 4, 6]".
    """
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body

    status, body = _post(base, "/api/calc/evaluate", {"expr": "L1+L1"})
    assert status == 200, body
    assert body["exact"] == "[2, 4, 6]", body


def test_lists_evaluate_mismatched_lengths_400(base):
    """Two different-length lists combined in one expression is a 400,
    never a 500 or a truncated/best-effort answer.
    """
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body
    status, body = _put(base, "/api/lists/L2", {"values": ["4", "5"]})
    assert status == 200, body

    status, body = _post(base, "/api/calc/evaluate", {"expr": "L1+L2"})
    assert status == 400, body
    assert "error" in body, body


def test_lists_evaluate_regression_plain_expr_unchanged(base):
    """A plain expression that references no list at all must evaluate
    exactly as it did before this step existed -- even on a server that
    does have an (unreferenced) stored list sitting in its state.
    """
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body

    status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
    assert status == 200, body
    assert body["exact"] == "2", body
    assert body["decimal"] == "2", body


def test_lists_evaluate_regression_stored_variable_unchanged(base):
    """An expression that references a previously stored plain variable
    (never a list) must also evaluate exactly as before, alongside a
    stored list it never mentions.
    """
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body

    status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
    assert status == 200, body
    assert body["exact"] == "5", body

    status, body = _post(base, "/api/calc/evaluate", {"expr": "a+1"})
    assert status == 200, body
    assert body["exact"] == "6", body
