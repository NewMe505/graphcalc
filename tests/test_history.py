"""Tests for the history store, GET /api/calc/history (S1), and "ans" (S2).

Only a successful evaluation (no CalcError, no domain_error) is appended to
history, as {"expr": <input>, "exact": ..., "decimal": ...}; a 400 (parse
error) adds nothing. Every test gets a fresh, empty history via the
`server` fixture, which attaches a brand-new InMemoryHistoryStore to its own
HTTPServer instance -- never shared across tests.

"ans" recalls the last entry's exact result (calc.evaluate's `last_entry`
parameter, fed by cli.py from the same history store); with no history yet,
evaluating "ans" is a 400 {"error": "ans is undefined"}.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from graphcalc.cli import build_server
from graphcalc.history import InMemoryHistoryStore


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
    """A fresh server, built with build_server's own injection hook so each
    test gets a brand-new, empty InMemoryHistoryStore -- never shared."""
    srv = build_server(0, history_store=InMemoryHistoryStore())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def base(server):
    return f"http://127.0.0.1:{server.server_port}"


# ---- GET /api/calc/history starts empty ----


def test_history_starts_empty(base):
    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}


# ---- a successful evaluation is recorded ----


def test_history_records_eval(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "2+3"})
    assert status == 200
    assert body["exact"] == "5"

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body["history"][-1] == {"expr": "2+3", "exact": "5", "decimal": "5"}


def test_history_records_multiple_evals_in_order(base):
    _post(base, "/api/calc/evaluate", {"expr": "2+3"})
    _post(base, "/api/calc/evaluate", {"expr": "1/3+1/6"})

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert [entry["expr"] for entry in body["history"]] == ["2+3", "1/3+1/6"]
    assert body["history"][-1] == {"expr": "1/3+1/6", "exact": "1/2", "decimal": "0.5"}


# ---- failures never add an entry ----


def test_history_records_nothing_on_parse_error(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "2+*3"})
    assert status == 400

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}


def test_history_records_nothing_on_missing_expr(base):
    status, body = _post(base, "/api/calc/evaluate", {})
    assert status == 400

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}


def test_history_records_nothing_on_domain_error(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "1/0"})
    assert status == 200
    assert body["domain_error"] is not None

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}


# ---- per-test isolation: a fresh server starts with no history, even after
#      a previous test (using a different server) recorded an entry ----


def test_history_fixture_gives_a_fresh_store_each_test(base):
    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}


# ---- "ans" recalls the last successful result (plan step S2) ----


def test_ans_recalls_last(base):
    status, body = _post(base, "/api/calc/evaluate", {"expr": "2+3"})
    assert status == 200
    assert body["exact"] == "5"

    status, body = _post(base, "/api/calc/evaluate", {"expr": "ans*2"})
    assert status == 200
    assert body["exact"] == "10"

    # The original expression text is stored in history, not "10" or "5*2".
    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body["history"][-1] == {"expr": "ans*2", "exact": "10", "decimal": "10"}

    # A second check: "ans" now refers to the just-recorded 10.
    status, body = _post(base, "/api/calc/evaluate", {"expr": "ans+1"})
    assert status == 200
    assert body["exact"] == "11"


def test_ans_undefined_on_empty_history(base):
    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}

    status, body = _post(base, "/api/calc/evaluate", {"expr": "ans"})
    assert status == 400
    assert body == {"error": "ans is undefined"}

    status, body = _get(base, "/api/calc/history")
    assert status == 200
    assert body == {"history": []}


# ---- unit tests: InMemoryHistoryStore directly, no HTTP ----


def test_in_memory_history_store_append_and_entries():
    store = InMemoryHistoryStore()
    assert store.entries() == []
    assert store.last() is None
    store.append({"expr": "2+3", "exact": "5", "decimal": "5"})
    assert store.entries() == [{"expr": "2+3", "exact": "5", "decimal": "5"}]
    assert store.last() == {"expr": "2+3", "exact": "5", "decimal": "5"}


def test_in_memory_history_store_clear():
    store = InMemoryHistoryStore()
    store.append({"expr": "2+3", "exact": "5", "decimal": "5"})
    store.clear()
    assert store.entries() == []
    assert store.last() is None


def test_in_memory_history_store_entries_is_a_copy():
    store = InMemoryHistoryStore()
    store.append({"expr": "2+3", "exact": "5", "decimal": "5"})
    entries = store.entries()
    entries.append({"expr": "injected", "exact": "x", "decimal": None})
    assert store.entries() == [{"expr": "2+3", "exact": "5", "decimal": "5"}]
