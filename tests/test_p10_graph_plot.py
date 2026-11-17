"""Tests for plan step P10/S1: graphcalc/graph.py and POST /api/graph/plot.

F1 (PRODUCT.md, [failing] before this step): '{"functions":{"f1":"x^2"},
"window":{"xmin":-2,"xmax":2,"ymin":-1,"ymax":5},"samples":5} returns x
[-2,-1,0,1,2] and series.f1.y [4,1,0,1,4]'. test_p10_plot_parabola proves
this directly over HTTP, against an in-process server built the same way
tests/test_p32_definitions_in_history.py's own `server`/`base` fixtures
build one for /api/calc/evaluate.

F2 (PRODUCT.md, [failing] before this step): 'f1 "sqrt(x)" sampled at x
[-1,0,1] returns y [null,0,1]; f1 "1/x" at x=0 returns y null with status
200'. test_p10_null_gaps_sqrt and test_p10_null_gaps_reciprocal prove this
directly over HTTP: a non-real sample (sqrt of a negative number) and an
infinite one (division by zero, sympy's own zoo) both become a JSON null
gap, never a 400 or a 500, and the request as a whole still returns 200.

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


# ---- F2: null gaps for a non-real sample and an infinite sample ----


def test_p10_null_gaps_sqrt(base):
    """'sqrt(x)' sampled at x [-1,0,1] returns y [null,0,1]' (PRODUCT.md F2).

    sqrt(-1) is the non-real 1.0*I under sympy's own evalf -- see
    graphcalc.graph._evaluate_at's is_real check -- so it must become a JSON
    null (a gap in the curve) rather than a 400 or a dropped sample; the
    request as a whole still succeeds with status 200.
    """
    status, body = _post(
        base,
        "/api/graph/plot",
        {
            "functions": {"f1": "sqrt(x)"},
            "window": {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1},
            "samples": 3,
        },
    )
    assert status == 200, body
    assert body["x"] == [-1, 0, 1], body
    assert body["series"]["f1"]["y"] == [None, 0, 1], body


def test_p10_null_gaps_reciprocal(base):
    """'1/x' at x=0 returns y null with status 200' (PRODUCT.md F2).

    Substituting the sympy Float(0) sample point into "1/x" resolves to
    sympy's own symbolic zoo (not a Python ZeroDivisionError) -- see
    graphcalc.graph._evaluate_at's own docstring -- which this module turns
    into a JSON null gap instead of a 400 or 500.
    """
    status, body = _post(
        base,
        "/api/graph/plot",
        {
            "functions": {"f1": "1/x"},
            "window": {"xmin": -1, "xmax": 1, "ymin": -5, "ymax": 5},
            "samples": 3,
        },
    )
    assert status == 200, body
    assert body["x"] == [-1, 0, 1], body
    assert body["series"]["f1"]["y"][1] is None, body
