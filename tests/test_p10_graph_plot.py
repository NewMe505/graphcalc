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
import re
import threading
import urllib.error
import urllib.request

import pytest

from graphcalc.cli import build_server
from graphcalc.graph import MAX_SAMPLES, MIN_SAMPLES, SERIES_COLORS


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
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
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


# ---- F3: distinct per-slot colors, and the request validation that
# backs "a fifth function or xmin >= xmax returns 400" ----

_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")


def test_p10_colors_distinct(base):
    """'f1 to f4 each return a different series color' (PRODUCT.md F3).

    Checked two ways: graphcalc.graph.SERIES_COLORS -- the fixed palette
    plot() assigns colors from -- has one entry per slot, each matching
    "#rrggbb" and pairwise distinct; and a live request naming all four
    slots gets those same colors back in its response, proving plot()
    actually threads SERIES_COLORS[name] into series[name]["color"] rather
    than, say, always answering with one slot's color.
    """
    assert set(SERIES_COLORS) == {"f1", "f2", "f3", "f4"}
    colors = [SERIES_COLORS[name] for name in ("f1", "f2", "f3", "f4")]
    for color in colors:
        assert _COLOR_RE.match(color), color
    assert len(set(colors)) == len(colors), colors

    status, body = _post(
        base,
        "/api/graph/plot",
        {
            "functions": {"f1": "x", "f2": "x", "f3": "x", "f4": "x"},
            "window": {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1},
            "samples": 2,
        },
    )
    assert status == 200, body
    response_colors = [body["series"][name]["color"] for name in ("f1", "f2", "f3", "f4")]
    assert response_colors == colors, body
    assert len(set(response_colors)) == 4, body


def test_p10_validation_fifth_function(base):
    """'a fifth function ... returns 400' (PRODUCT.md F3).

    "f5" is outside the f1..f4 slots graphcalc.graph.SERIES_COLORS defines,
    so plot() rejects it as GraphError before parsing anything -- 400 with
    a JSON body carrying an "error" key, never a 500.
    """
    status, body = _post(
        base,
        "/api/graph/plot",
        {
            "functions": {"f1": "x", "f2": "x", "f3": "x", "f4": "x", "f5": "x"},
            "window": {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1},
            "samples": 2,
        },
    )
    assert status == 400, body
    assert isinstance(body.get("error"), str) and body["error"], body


def test_p10_validation_xmin_ge_xmax(base):
    """'xmin >= xmax ... returns 400' (PRODUCT.md F3) -- both exactly at
    the boundary (xmin == xmax) and strictly past it (xmin > xmax), which
    plot()'s own ">=" check -- not a strict ">" -- must reject either way.
    ymin >= ymax (plan step P10/S3's own extension of the same rule to the
    other axis) is checked too, at the boundary.
    """
    windows = [
        {"xmin": 1, "xmax": 1, "ymin": -1, "ymax": 1},  # xmin == xmax
        {"xmin": 2, "xmax": -2, "ymin": -1, "ymax": 1},  # xmin > xmax
        {"xmin": -1, "xmax": 1, "ymin": 1, "ymax": 1},  # ymin == ymax
    ]
    for window in windows:
        status, body = _post(
            base,
            "/api/graph/plot",
            {"functions": {"f1": "x"}, "window": window, "samples": 2},
        )
        assert status == 400, (window, body)
        assert isinstance(body.get("error"), str) and body["error"], (window, body)


def test_p10_validation_non_finite_window_bound(base):
    """A window bound that is not finite -- Infinity, -Infinity or NaN --
    must 400 even though Python's json module happily decodes those bare
    tokens into real float('inf')/float('nan') values (graphcalc.graph.
    _window_bound's own math.isfinite check, plan step P10/S3). json.dumps
    emits the same bare tokens back out, so round-tripping through _post's
    json.dumps/urlopen reaches the server exactly as a browser's fetch()
    sending literal JSON text would.
    """
    base_window = {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}
    for key, bad_value in (
        ("xmin", float("-inf")),
        ("xmax", float("inf")),
        ("ymax", float("nan")),
    ):
        window = dict(base_window, **{key: bad_value})
        status, body = _post(
            base,
            "/api/graph/plot",
            {"functions": {"f1": "x"}, "window": window, "samples": 2},
        )
        assert status == 400, (key, bad_value, body)
        assert isinstance(body.get("error"), str) and body["error"], (key, bad_value, body)


def test_p10_validation_non_string_expr(base):
    """A function body that is not a string -- e.g. a bare number, None,
    or a list -- must 400 as a GraphError ("function f1 must be a
    string"), not as graphcalc.calc.CalcError's own, differently worded,
    "missing parameter: expr" (which would otherwise also still be a 400,
    but names a parameter this API never exposes) -- see graphcalc.graph.
    plot's own docstring, plan step P10/S3.
    """
    window = {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}
    for bad_expr in (5, None, ["x"], {"a": 1}):
        status, body = _post(
            base,
            "/api/graph/plot",
            {"functions": {"f1": bad_expr}, "window": window, "samples": 2},
        )
        assert status == 400, (bad_expr, body)
        assert isinstance(body.get("error"), str) and body["error"], (bad_expr, body)
        assert "string" in body["error"], (bad_expr, body)


def test_p10_validation_bad_samples(base):
    """"samples" must be a non-bool int inside [MIN_SAMPLES, MAX_SAMPLES]
    (graphcalc.graph.plot's own validation, plan step P10/S3) -- a bool
    (even though Python's bool is an int subclass), a float, a string, and
    an in-range-looking-but-too-small/too-large int must all 400.
    """
    window = {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}
    bad_values = (
        True,
        False,
        2.0,
        "5",
        MIN_SAMPLES - 1,
        0,
        -5,
        MAX_SAMPLES + 1,
    )
    for bad_samples in bad_values:
        status, body = _post(
            base,
            "/api/graph/plot",
            {"functions": {"f1": "x"}, "window": window, "samples": bad_samples},
        )
        assert status == 400, (bad_samples, body)
        assert isinstance(body.get("error"), str) and body["error"], (bad_samples, body)
