"""Tests for plan step P11/S1: graphcalc/graph.py's window() and
POST /api/graph/window.

F1 (PRODUCT.md, [failing] before this step): '{"action":"zoom_in",
"factor":2,"window":{"xmin":-10,"xmax":10,"ymin":-10,"ymax":10}} returns
{"xmin":-5,"xmax":5,"ymin":-5,"ymax":5}'. test_p11_zoom_in proves this
directly over HTTP, against an in-process server built the same way
tests/test_p10_graph_plot.py's own `server`/`base` fixtures build one for
/api/graph/plot.

F2 (PRODUCT.md, [failing] before this step): 'zoom_out with factor 2 on
the same window returns -20..20 on both axes'. test_p11_zoom_out proves
this directly over HTTP.

F3 (PRODUCT.md, [failing] before this step): '{"action":"pan","dx":1,
"dy":-2} on the standard window returns xmin -9, xmax 11, ymin -12,
ymax 8; an unknown action returns 400'. test_p11_pan_standard_window and
test_p11_unknown_action prove the two halves of this directly over HTTP.
test_p11_pan_standard_window sends no "window" key at all -- exactly the
acceptance criterion's own request body -- to prove graphcalc.graph.
window() defaults a missing window to the standard -10..10 window before
panning it (see that module's own docstring for window()).

Every acceptance-criteria response is checked for plain-number formatting
too (planner notes: "Return plain numbers (ints when whole)"): each bound
compares equal to a Python int, and json.loads never decoded it as a
string.
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


@pytest.fixture
def server():
    """A fresh server with a default (in-memory) history store and state.

    POST /api/graph/window never reads either one (see graphcalc.cli's own
    module docstring), but build_server() always wires up both regardless,
    the same way every other test in this repository builds a server.
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


# ---- F1: zoom_in about the window center ----


def test_p11_zoom_in(base):
    status, body = _post(
        base,
        "/api/graph/window",
        {
            "action": "zoom_in",
            "factor": 2,
            "window": {"xmin": -10, "xmax": 10, "ymin": -10, "ymax": 10},
        },
    )
    assert status == 200, body
    assert body == {"xmin": -5, "xmax": 5, "ymin": -5, "ymax": 5}, body
    for key in ("xmin", "xmax", "ymin", "ymax"):
        assert isinstance(body[key], int), body


# ---- F2: zoom_out about the window center ----


def test_p11_zoom_out(base):
    status, body = _post(
        base,
        "/api/graph/window",
        {
            "action": "zoom_out",
            "factor": 2,
            "window": {"xmin": -10, "xmax": 10, "ymin": -10, "ymax": 10},
        },
    )
    assert status == 200, body
    assert body == {"xmin": -20, "xmax": 20, "ymin": -20, "ymax": 20}, body
    for key in ("xmin", "xmax", "ymin", "ymax"):
        assert isinstance(body[key], int), body


# ---- F3: pan on the (default) standard window, and an unknown action ----


def test_p11_pan_standard_window(base):
    """No "window" key at all -- exactly the acceptance criterion's own
    request body -- so window() must default it to the standard -10..10
    window before panning.
    """
    status, body = _post(base, "/api/graph/window", {"action": "pan", "dx": 1, "dy": -2})
    assert status == 200, body
    assert body == {"xmin": -9, "xmax": 11, "ymin": -12, "ymax": 8}, body
    for key in ("xmin", "xmax", "ymin", "ymax"):
        assert isinstance(body[key], int), body


def test_p11_pan_explicit_window(base):
    """A pan also works relative to an explicit window, as a pure
    translation: width and height stay the same, only the bounds shift.
    """
    status, body = _post(
        base,
        "/api/graph/window",
        {
            "action": "pan",
            "dx": 2,
            "dy": 3,
            "window": {"xmin": -4, "xmax": 4, "ymin": -1, "ymax": 1},
        },
    )
    assert status == 200, body
    assert body == {"xmin": -2, "xmax": 6, "ymin": 2, "ymax": 4}, body


def test_p11_unknown_action(base):
    status, body = _post(base, "/api/graph/window", {"action": "sideways"})
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


def test_p11_missing_action(base):
    """A missing "action" is also unknown, never silently defaulted to
    "standard" or any other action.
    """
    status, body = _post(base, "/api/graph/window", {})
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


# ---- "standard" is -10..10 on both axes, ignoring everything else ----


def test_p11_standard(base):
    status, body = _post(base, "/api/graph/window", {"action": "standard"})
    assert status == 200, body
    assert body == {"xmin": -10, "xmax": 10, "ymin": -10, "ymax": 10}, body
    for key in ("xmin", "xmax", "ymin", "ymax"):
        assert isinstance(body[key], int), body


def test_p11_standard_ignores_other_fields(base):
    """"standard" always answers the fixed window, regardless of a
    nonsensical factor/window also present in the same body.
    """
    status, body = _post(
        base,
        "/api/graph/window",
        {
            "action": "standard",
            "factor": -5,
            "window": {"xmin": 1, "xmax": 1, "ymin": 1, "ymax": 1},
        },
    )
    assert status == 200, body
    assert body == {"xmin": -10, "xmax": 10, "ymin": -10, "ymax": 10}, body


# ---- validation: bad factor, bad dx/dy, bad window ----


def test_p11_validation_bad_factor(base):
    window = {"xmin": -10, "xmax": 10, "ymin": -10, "ymax": 10}
    for action in ("zoom_in", "zoom_out"):
        for bad_factor in (0, -2, "2", True, None):
            status, body = _post(
                base,
                "/api/graph/window",
                {"action": action, "factor": bad_factor, "window": window},
            )
            assert status == 400, (action, bad_factor, body)
            assert isinstance(body.get("error"), str) and body["error"], (
                action,
                bad_factor,
                body,
            )


def test_p11_validation_bad_pan_delta(base):
    for bad_delta in ("1", True, None, float("inf"), float("nan")):
        status, body = _post(
            base,
            "/api/graph/window",
            {"action": "pan", "dx": bad_delta, "dy": 0},
        )
        assert status == 400, (bad_delta, body)
        assert isinstance(body.get("error"), str) and body["error"], (bad_delta, body)

        status, body = _post(
            base,
            "/api/graph/window",
            {"action": "pan", "dx": 0, "dy": bad_delta},
        )
        assert status == 400, (bad_delta, body)
        assert isinstance(body.get("error"), str) and body["error"], (bad_delta, body)


def test_p11_validation_bad_window(base):
    bad_windows = [
        {"xmin": 1, "xmax": 1, "ymin": -1, "ymax": 1},  # xmin == xmax
        {"xmin": 2, "xmax": -2, "ymin": -1, "ymax": 1},  # xmin > xmax
        {"xmin": -1, "xmax": 1, "ymin": 1, "ymax": 1},  # ymin == ymax
        {"xmin": -1, "xmax": 1, "ymin": -1},  # missing ymax
        "not a window",  # wrong type entirely
    ]
    for window in bad_windows:
        status, body = _post(
            base,
            "/api/graph/window",
            {"action": "pan", "dx": 1, "dy": 1, "window": window},
        )
        assert status == 400, (window, body)
        assert isinstance(body.get("error"), str) and body["error"], (window, body)


def test_p11_validation_non_finite_window_bound(base):
    base_window = {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}
    for key, bad_value in (
        ("xmin", float("-inf")),
        ("xmax", float("inf")),
        ("ymax", float("nan")),
    ):
        window = dict(base_window, **{key: bad_value})
        status, body = _post(
            base,
            "/api/graph/window",
            {"action": "zoom_in", "factor": 2, "window": window},
        )
        assert status == 400, (key, bad_value, body)
        assert isinstance(body.get("error"), str) and body["error"], (key, bad_value, body)


def test_p11_validation_invalid_body(base):
    status, body = _post(base, "/api/graph/window", "not an object")
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body
