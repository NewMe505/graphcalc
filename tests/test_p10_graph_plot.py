"""Tests for plan step P10/S1: graphcalc/graph.py and POST /api/graph/plot.

F1 (PRODUCT.md, [failing] before this step): '{"functions":{"f1":"x^2"},
"window":{"xmin":-2,"xmax":2,"ymin":-1,"ymax":5},"samples":5} returns x
[-2,-1,0,1,2] and series.f1.y [4,1,0,1,4]'. test_p10_plot_parabola proves
this directly over HTTP, against an in-process server built the same way
tests/test_p32_definitions_in_history.py's own `server`/`base` fixtures
build one for /api/calc/evaluate.

The x values are sympy Floats under the hood (graphcalc.graph.plot builds
them via plain float arithmetic, then substitutes a sympy Float per sample
-- see that module's own docstring), so they round-trip through JSON as
floats (-2.0, -1.0, ...): == against the plain ints the acceptance
criterion lists still holds, since Python (and the json module's own
decoded floats) compare a float equal to the int it exactly represents.
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

    POST /api/graph/plot never reads either one (see graphcalc.cli's own
    module docstring), but build_server() always wires up both regardless,
    the same way every other test in this repository builds a server.
    """
    srv = build_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def base(server):
    return f"http://127.0.0.1:{server.server_port}"


# ---- F1: the acceptance criterion's own x^2 example ----


def test_p10_plot_parabola(base):
    status, body = _post(
        base,
        "/api/graph/plot",
        {
            "functions": {"f1": "x^2"},
            "window": {"xmin": -2, "xmax": 2, "ymin": -1, "ymax": 5},
            "samples": 5,
        },
    )
    assert status == 200, body
    assert body["x"] == [-2, -1, 0, 1, 2], body
    assert body["series"]["f1"]["y"] == [4, 1, 0, 1, 4], body
