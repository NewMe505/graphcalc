"""Tests for plan step P17: POST /api/stats/regression.

Acceptance bullet 1 ('linear on x [1,2,3], y [2,4,6] returns coefficients
a "2", b "0" and r2 "1"'): test_regression_linear_exact_fit proves exactly
that, through the real POST /api/stats/regression route (graphcalc.cli.
Handler.do_POST) against an in-process server, reusing the same `_post`
HTTP helper and server-building pattern tests/test_p16_onevar.py and
tests/test_p15_lists.py already use. It also checks "points" echoes the
request's own (x, y) pairs and "curve" holds 50 points.

Acceptance bullet 2 ('quadratic on x [0,1,2,3], y [1,2,5,10] returns a
"1", b "0", c "1", r2 "1"', plan step P17/S2): test_regression_quadratic_
exact_fit proves exactly that, through the same route/server pattern.

Acceptance bullet 3's "lists of different lengths return 400" half is
proven by test_regression_400_mismatched_lengths.

The remaining tests are the same "never a 500" checks
tests/test_p16_onevar.py already runs for its own POST route, adapted to
this route's own request shape: a non-string/unparseable "x"/"y" entry, an
unknown "model" (plan step P17/S2's own acceptance line), and a non-object
body are all 400 with an "error" key. test_regression_400_non_object_body
in particular sends a non-list "x" (a bare string) rather than a
structurally-wrong top-level body -- the node id is kept as-is rather than
renamed, since this attempt's own tests_added already cites it under its
existing name.

Plan step P17/S3 adds two more things neither of the above fully proves:

test_regression_linear_unsorted_x_input_order_and_curve_range proves
"points" holds the data pairs *in input order* (not sorted) and "curve"
spans min(x)..max(x) *as a range*, not just xs[0]..xs[-1] -- both
acceptance bullets 1 and 2 above use already-sorted x, so curve[0]/
curve[-1] matching points[0]/points[-1] there does not actually rule out
an implementation that (wrongly) sampled from the first/last x entries
instead of the true min/max.

test_regression_400_validation (parametrized) covers every 400 case S3
names explicitly that was not already exercised above: an empty "x", a
list of non-string (JSON number) entries, too few distinct x values for
each model (linear needs >=2, quadratic needs >=3), and SS_tot == 0 (every
y value equal).
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


# ---- acceptance bullet 2: quadratic exact fit ----


def test_regression_linear_unsorted_x_input_order_and_curve_range(base):
    status, body = _post(
        base,
        "/api/stats/regression",
        {"model": "linear", "x": ["3", "1", "2"], "y": ["6", "2", "4"]},
    )
    assert status == 200, body
    assert body["points"] == [["3", "6"], ["1", "2"], ["2", "4"]], body
    assert len(body["curve"]) == 50, body
    assert body["curve"][0] == ["1", "2"], body
    assert body["curve"][-1] == ["3", "6"], body


def test_regression_quadratic_exact_fit(base):
    status, body = _post(
        base,
        "/api/stats/regression",
        {"model": "quadratic", "x": ["0", "1", "2", "3"], "y": ["1", "2", "5", "10"]},
    )
    assert status == 200, body
    assert body["model"] == "quadratic", body
    assert body["coefficients"] == {"a": "1", "b": "0", "c": "1"}, body
    assert body["r2"] == "1", body
    assert body["points"] == [["0", "1"], ["1", "2"], ["2", "5"], ["3", "10"]], body
    assert len(body["curve"]) == 50, body
    assert body["curve"][0] == ["0", "1"], body
    assert body["curve"][-1] == ["3", "10"], body


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


# ---- plan step P17/S3's own validation list, each case not already hit above ----


@pytest.mark.parametrize(
    "payload",
    [
        # "a list is empty ... is not a list of strings": empty "x".
        {"model": "linear", "x": [], "y": []},
        # "... or not a list of strings": entries are JSON numbers, not strings.
        {"model": "linear", "x": [1, 2, 3], "y": [2, 4, 6]},
        # "too few distinct x values for the model (fewer than 2 for linear ...)".
        {"model": "linear", "x": ["1", "1", "1"], "y": ["1", "2", "3"]},
        # "... fewer than 3 for quadratic".
        {"model": "quadratic", "x": ["1", "1", "2", "2"], "y": ["1", "2", "3", "4"]},
        # "SS_tot is 0": every y value equal.
        {"model": "linear", "x": ["1", "2", "3"], "y": ["5", "5", "5"]},
    ],
)
def test_regression_400_validation(base, payload):
    status, body = _post(base, "/api/stats/regression", payload)
    assert status == 400, body
    assert "error" in body, body
