"""Tests for plan step P17/S1: POST /api/stats/regression.

Acceptance bullet 1 ('linear on x [1,2,3], y [2,4,6] returns coefficients
a "2", b "0" and r2 "1"'): test_regression_linear_exact_fit proves exactly
that, through the real POST /api/stats/regression route (graphcalc.cli.
Handler.do_POST) against an in-process server, reusing the same `_post`
HTTP helper and server-building pattern tests/test_p16_onevar.py and
tests/test_p15_lists.py already use. It also checks "points" echoes the
request's own (x, y) pairs and "curve" holds 50 points.

Acceptance bullet 3's "lists of different lengths return 400" half is
proven by test_regression_400_mismatched_lengths; the quadratic half of
that bullet, and bullet 2 (quadratic model), are a later plan step's job
(_FITS currently only has "linear" -- see graphcalc/stats.py's own module
docstring) and are not claimed here.

The remaining tests are the same "never a 500" checks
tests/test_p16_onevar.py already runs for its own POST route, adapted to
this route's own request shape: a non-string/unparseable "x"/"y" entry, an
unknown "model", and a non-object body are all 400 with an "error" key.
"""

import threading

from graphcalc.cli import build_server

from tests.test_p15_lists import _post  # reuse the same tiny HTTP helper


import pytest


@pytest.fixture
def server():
    """A fresh server with a default (in-memory) history store and state.

    Same per-test isolation as tests/test_p16_onevar.py's own `server`
    fixture -- this route is stateless, but the server itself is still
    built fresh per test to match every other HTTP test in this suite.
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


# ---- acceptance bullet 1: linear exact fit ----


def test_regression_linear_exact_fit(base):
    status, body = _post(
        base,
        "/api/stats/regression",
        {"model": "linear", "x": ["1", "2", "3"], "y": ["2", "4", "6"]},
    )
    assert status == 200, body
    assert body["model"] == "linear", body
    assert body["coefficients"] == {"a": "2", "b": "0"}, body
    assert body["r2"] == "1", body
    assert body["points"] == [["1", "2"], ["2", "4"], ["3", "6"]], body
    assert len(body["curve"]) == 50, body
    assert body["curve"][0] == ["1", "2"], body
    assert body["curve"][-1] == ["3", "6"], body


# ---- acceptance bullet 3: mismatched lengths return 400 ----


def test_regression_400_mismatched_lengths(base):
    status, body = _post(
        base,
        "/api/stats/regression",
        {"model": "linear", "x": ["1", "2", "3"], "y": ["2", "4"]},
    )
    assert status == 400, body
    assert "error" in body, body


# ---- "never a 500": bad model/entries/body are all 400 ----


def test_regression_400_unknown_model(base):
    status, body = _post(
        base,
        "/api/stats/regression",
        {"model": "cubic", "x": ["1", "2"], "y": ["2", "4"]},
    )
    assert status == 400, body
    assert "error" in body, body


def test_regression_400_bad_entry(base):
    status, body = _post(
        base,
        "/api/stats/regression",
        {"model": "linear", "x": ["1", "2", "3"], "y": ["2", "abc", "6"]},
    )
    assert status == 400, body
    assert "error" in body, body


def test_regression_400_non_object_body(base):
    status, body = _post(base, "/api/stats/regression", {"model": "linear", "x": "nope", "y": ["1"]})
    assert status == 400, body
    assert "error" in body, body


def test_regression_400_missing_keys(base):
    status, body = _post(base, "/api/stats/regression", {})
    assert status == 400, body
    assert "error" in body, body
