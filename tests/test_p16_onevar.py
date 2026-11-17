"""Tests for plan step P16/S1: POST /api/stats/onevar.

F1 (PRODUCT.md, [failing] before this step): 'For L1 [1,2,3,4,5] it returns
n 5 and exact mean "3", median "3", sum "15", min "1", q1 "3/2" (decimal
"1.5"), q3 "9/2" (decimal "4.5"), max "5".' test_onevar_l1_summary proves
exactly that, through the real POST /api/stats/onevar route (graphcalc.
cli.Handler.do_POST) against an in-process server built the same way
tests/test_p15_lists.py's own `server`/`base` fixtures build one, after a
PUT /api/lists/L1 the same way that file's own list tests set up a list.

F2 (PRODUCT.md, [failing] before this step): 'For the same list sx is
exact "sqrt(10)/2" (decimal "1.58113883008") and sigma_x is exact
"sqrt(2)" (decimal "1.41421356237").' test_onevar_l1_spread proves exactly
that, on the same L1 fixture.

test_onevar_quartiles_even is a TI-method check on an even-length list --
[1,2,3,4,5,6] -- where neither half excludes a middle "overall median"
element (unlike the odd-length L1 case above): q1 "2", q3 "5".

The remaining tests prove the acceptance checklist's third bullet: 'An
empty list, a missing list key or an undefined list name returns 400' --
test_onevar_400_undefined_list_name, test_onevar_400_missing_list_key, and
test_onevar_400_empty_list (the last one through a hand-written state file,
since PUT /api/lists/<name> itself never lets a client store an empty
list -- see graphcalc.lists.validate_list_values).
"""

import json
import threading

import pytest

from graphcalc.cli import build_server
from graphcalc.history import StateBackedHistoryStore
from graphcalc.state import CalcState

from tests.test_p15_lists import _post, _put  # reuse the same tiny HTTP helpers


@pytest.fixture
def server():
    """A fresh server with a default (in-memory) history store and state.

    Same per-test isolation as tests/test_p15_lists.py's own `server`
    fixture: each test gets its own server/state, so one test's stored
    lists never leak into another.
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


# ---- F1: n, mean, median, sum, min, q1, q3, max for L1 = [1,2,3,4,5] ----


def test_onevar_l1_summary(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3", "4", "5"]})
    assert status == 200, body

    status, body = _post(base, "/api/stats/onevar", {"list": "L1"})
    assert status == 200, body
    assert body["n"] == 5, body
    assert body["mean"] == {"exact": "3", "decimal": "3"}, body
    assert body["median"] == {"exact": "3", "decimal": "3"}, body
    assert body["sum"] == {"exact": "15", "decimal": "15"}, body
    assert body["min"] == {"exact": "1", "decimal": "1"}, body
    assert body["q1"] == {"exact": "3/2", "decimal": "1.5"}, body
    assert body["q3"] == {"exact": "9/2", "decimal": "4.5"}, body
    assert body["max"] == {"exact": "5", "decimal": "5"}, body


# ---- F2: sx and sigma_x for the same list ----


def test_onevar_l1_spread(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3", "4", "5"]})
    assert status == 200, body

    status, body = _post(base, "/api/stats/onevar", {"list": "L1"})
    assert status == 200, body
    assert body["sx"] == {"exact": "sqrt(10)/2", "decimal": "1.58113883008"}, body
    assert body["sigma_x"] == {"exact": "sqrt(2)", "decimal": "1.41421356237"}, body


# ---- TI quartile method on an even-length list ----


def test_onevar_quartiles_even(base):
    status, body = _put(base, "/api/lists/L1", {"values": ["1", "2", "3", "4", "5", "6"]})
    assert status == 200, body

    status, body = _post(base, "/api/stats/onevar", {"list": "L1"})
    assert status == 200, body
    assert body["n"] == 6, body
    assert body["q1"]["exact"] == "2", body
    assert body["q3"]["exact"] == "5", body


# ---- acceptance: an empty list, a missing list key, or an undefined list
# name all return 400 ----


def test_onevar_400_undefined_list_name(base):
    status, body = _post(base, "/api/stats/onevar", {"list": "NOPE"})
    assert status == 400, body
    assert "error" in body, body


def test_onevar_400_missing_list_key(base):
    status, body = _post(base, "/api/stats/onevar", {})
    assert status == 400, body
    assert "error" in body, body


def test_onevar_400_empty_list(tmp_path):
    """PUT /api/lists/<name> never lets a client store an empty list
    (graphcalc.lists.validate_list_values rejects it before it is ever
    saved), so this reaches the "empty list" case the only other way one
    can exist: a hand-written state file, the same technique
    tests/test_p15_lists.py's own corrupted-entries tests use.
    """
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"lists": {"L1": []}}), encoding="utf-8")

    state = CalcState(str(path))
    assert state.lists() == {"L1": []}, state.lists()  # confirms the fixture is well-formed, not dropped

    srv = build_server(0, history_store=StateBackedHistoryStore(state), state=state)
    base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        status, body = _post(base, "/api/stats/onevar", {"list": "L1"})
        assert status == 400, body
        assert "error" in body, body
    finally:
        srv.shutdown()
        srv.server_close()


def test_onevar_400_non_object_body(base):
    """A malformed/non-object body is also a 400, never a 500 -- the same
    rule every other body-bearing route in this product already follows.
    """
    status, body = _post(base, "/api/stats/onevar", {"list": 5})
    assert status == 400, body
    assert "error" in body, body
