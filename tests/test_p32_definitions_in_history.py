"""Tests for definitions in history (plan step P32, owner revision
2026-11-14: "definitions in history").

Before this fix, graphcalc.cli._handle_calc_evaluate stored a successful
"name:=expr" or "f(x):=expr" definition only in the HTTPServer's
graphcalc.state.CalcState (via set_variable/set_function), never in the
graphcalc.history.HistoryStore a plain evaluate() success is appended to.
GET /api/calc/history therefore never showed a definition at all, even
right after one succeeded.

The fix: a successful definition (result["exact"] is not None -- i.e. no
domain_error on the right-hand side) is now also appended to the history
store, as {"expr": <original "name:=expr"/"f(x):=expr" text>,
"exact": ..., "decimal": ...} -- `exact` and `decimal` read directly off
the dict actually sent back as the HTTP response, so the history entry's
"exact" is always the exact string the client saw (for a function, that is
the caret-converted form, e.g. "x^2 + 1", not the stored "**" body). A
rejected definition -- names.check_not_constant's 400 ("pi:=3"), or a
domain_error on the right-hand side ("a:=1/0") -- returns before this
append ever runs, so it adds nothing, same as a plain evaluate() 400 or
domain_error already added nothing.

"ans" is unaffected: CalcState.set_ans is still only ever called from the
plain-evaluate branch (P26/S1, P30), never from a definition's own
right-hand-side evaluation, so defining a variable or function never
changes what "ans" recalls.
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


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


@pytest.fixture
def server():
    """A fresh server with a default (in-memory) history store and state."""
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


# ---- F1: a:=5 then f(x):=x^2+1 -- both land in history, each with the
#      exact its own evaluate response gave ----


def test_variable_definition_exact_matches_response_in_history(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
    assert status == 200, body
    assert body["exact"] == "5"

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body["history"][-1] == {"expr": "a:=5", "exact": "5", "decimal": "5"}


def test_function_definition_exact_matches_response_in_history(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "f(x):=x^2+1"})
    assert status == 200, body
    assert body["exact"] == "x^2 + 1"

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body["history"][-1] == {"expr": "f(x):=x^2+1", "exact": "x^2 + 1", "decimal": None}


def test_both_definitions_are_the_last_two_history_entries_in_order(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
    assert status == 200, body
    a_response = dict(body)

    status, body = _post(base, "/api/calc/evaluate", {"expr": "f(x):=x^2+1"})
    assert status == 200, body
    f_response = dict(body)

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    last_two = body["history"][-2:]
    assert [entry["expr"] for entry in last_two] == ["a:=5", "f(x):=x^2+1"]
    assert last_two[0]["exact"] == a_response["exact"]
    assert last_two[1]["exact"] == f_response["exact"]


def test_multiple_params_function_definition_added_to_history(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "g(x,y):=x+y"})
    assert status == 200, body
    assert body["exact"] == "x + y"

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body["history"][-1] == {"expr": "g(x,y):=x+y", "exact": "x + y", "decimal": None}


def test_defined_variable_still_usable_after_being_recorded(base):
    _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
    status, body = _post(base, "/api/calc/evaluate", {"expr": "2a+1"})
    assert status == 200
    assert body["exact"] == "11"


# ---- F2: a definition that returns 400 is not added to the history ----


def test_redefining_constant_returns_400_and_history_stays_empty(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "pi:=3"})
    assert status == 400
    assert body == {"error": "cannot redefine constant pi"}

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}


def test_redefining_constant_as_function_returns_400_and_history_stays_empty(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "pi(x):=x"})
    assert status == 400
    assert body == {"error": "cannot redefine constant pi"}

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}


def test_rejected_definition_does_not_disturb_an_earlier_history_entry(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
    assert status == 200, body

    status, body = _post(base, "/api/calc/evaluate", {"expr": "pi:=3"})
    assert status == 400

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert [entry["expr"] for entry in body["history"]] == ["a:=5"]


# ---- a domain_error on the right-hand side also adds nothing (the same
#      rule a plain evaluate()'s own domain_error already follows) ----


def test_variable_definition_with_domain_error_not_added_to_history(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=1/0"})
    assert status == 200, body
    assert body["exact"] is None
    assert body["domain_error"] is not None

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}


# ---- defining a variable or function never changes what "ans" recalls ----


def test_definition_does_not_change_ans(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "2+2"})
    assert status == 200, body
    assert body["exact"] == "4"

    status, body = _post(base, "/api/calc/evaluate", {"expr": "a:=5"})
    assert status == 200, body
    assert body["exact"] == "5"

    status, body = _post(base, "/api/calc/evaluate", {"expr": "ans"})
    assert status == 200, body
    assert body["exact"] == "4"
