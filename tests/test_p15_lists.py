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
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from graphcalc.cli import build_server


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
