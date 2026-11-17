"""Tests for plan step P34/S1 (bug #40): graph-canvas must never join a
curve across a vertical asymptote, while a steep but continuous curve must
still be drawn whole.

The fix lives entirely in graphcalc/static/app.js's canvas draw loop (see
that file's own P34-BEGIN/P34-END comments) -- graphcalc/graph.py and the
POST /api/graph/plot contract it implements (plan step P10) are
deliberately unchanged, so this file never touches graphcalc.graph.plot's
inputs/outputs beyond reading the same "y" arrays it has always returned.

Two tests are pure source checks (always run): the pure helper
`graphIsAsymptoteJump` is defined between the P34-BEGIN/P34-END markers,
and graphDrawSeries calls it. The other four actually execute that helper
under Node (skipped individually when `node` isn't on PATH, per plan step
P34/S1) against the exact "y" arrays graph.plot() returns for a window of
-5..5 on both axes with 600 samples -- the same window/sample count the
acceptance criteria and app.js's own `samples: graphCanvas.width` (600,
see graphcalc/static/index.html) use -- and find the indices where the
path breaks, i.e. where graphIsAsymptoteJump(ys[i-1], ys[i], ymin, ymax)
is true for two non-null neighbours.
"""

import json
import math
import pathlib
import re
import shutil
import subprocess

import pytest

from graphcalc.graph import plot

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS_PATH = ROOT / "graphcalc" / "static" / "app.js"

WINDOW = {"xmin": -5.0, "xmax": 5.0, "ymin": -5.0, "ymax": 5.0}
SAMPLES = 600

_NODE = shutil.which("node")
_node_required = pytest.mark.skipif(_NODE is None, reason="node is not on PATH")


def _app_js_text():
    return APP_JS_PATH.read_text(encoding="utf-8")


def _extract_p34_block(text):
    match = re.search(r"// P34-BEGIN(.*?)// P34-END", text, re.S)
    assert match, "app.js is missing the // P34-BEGIN .. // P34-END markers"
    return match.group(1)


def _plot_y(expr):
    """The "x"/series.f1.y arrays graph.plot() returns for `expr` over
    WINDOW with SAMPLES samples -- exactly what graphDrawSeries receives.
    """
    result = plot({"functions": {"f1": expr}, "window": WINDOW, "samples": SAMPLES})
    return result["x"], result["series"]["f1"]["y"]


def _break_indices(ys, ymin, ymax, helper_src):
    """Runs the extracted graphIsAsymptoteJump under node and returns every
    index i (1 <= i < len(ys)) where it says the path from ys[i-1] to
    ys[i] is an asymptote jump -- a null-adjacent pair is skipped, the same
    way graphDrawSeries's own prevY tracking resets on a null gap instead
    of calling the helper.
    """
    driver_lines = [
        helper_src,
        "const ys = " + json.dumps(ys) + ";",
        "const ymin = " + repr(float(ymin)) + ";",
        "const ymax = " + repr(float(ymax)) + ";",
        "const breaks = [];",
        "for (let i = 1; i < ys.length; i++) {",
        "  var y0 = ys[i - 1];",
        "  var y1 = ys[i];",
        "  if (y0 === null || y1 === null) { continue; }",
        "  if (graphIsAsymptoteJump(y0, y1, ymin, ymax)) {",
        "    breaks.push(i);",
        "  }",
        "}",
        "console.log(JSON.stringify(breaks));",
    ]
    driver = "\n".join(driver_lines)
    result = subprocess.run(
        [_NODE, "-"],
        input=driver,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ---- Source checks: always run, no node required ----


def test_p34_helper_defined_in_markers():
    block = _extract_p34_block(_app_js_text())
    assert "function graphIsAsymptoteJump(" in block


def test_p34_draw_series_calls_helper():
    text = _app_js_text()
    start = text.index("function graphDrawSeries(")
    end = text.index("function graphRenderPlot(", start)
    body = text[start:end]
    assert "graphIsAsymptoteJump(" in body


# ---- Behavioral checks: run the extracted helper under node ----


@_node_required
def test_p34_one_over_x_breaks_at_zero():
    helper_src = _extract_p34_block(_app_js_text())
    xs, ys = _plot_y("1/x")
    breaks = _break_indices(ys, WINDOW["ymin"], WINDOW["ymax"], helper_src)
    assert len(breaks) == 1, breaks
    index = breaks[0]
    assert xs[index - 1] < 0 < xs[index], (xs[index - 1], xs[index])


@_node_required
def test_p34_tan_breaks_at_half_pi():
    helper_src = _extract_p34_block(_app_js_text())
    xs, ys = _plot_y("tan(x)")
    breaks = _break_indices(ys, WINDOW["ymin"], WINDOW["ymax"], helper_src)
    # tan(x) also has poles at -pi/2 and +-3pi/2 inside -5..5; every one of
    # them is a sign-flip of huge magnitude and must break too.
    assert len(breaks) == 4, breaks
    straddling_half_pi = [
        index for index in breaks if xs[index - 1] < math.pi / 2 < xs[index]
    ]
    assert len(straddling_half_pi) == 1, (breaks, xs[:5])


@_node_required
def test_p34_shifted_pole_breaks_at_one():
    helper_src = _extract_p34_block(_app_js_text())
    xs, ys = _plot_y("1/(x-1)")
    breaks = _break_indices(ys, WINDOW["ymin"], WINDOW["ymax"], helper_src)
    assert len(breaks) == 1, breaks
    index = breaks[0]
    assert xs[index - 1] < 1 < xs[index], (xs[index - 1], xs[index])


@_node_required
def test_p34_steep_line_unbroken():
    helper_src = _extract_p34_block(_app_js_text())
    xs, ys = _plot_y("10*x")
    breaks = _break_indices(ys, WINDOW["ymin"], WINDOW["ymax"], helper_src)
    assert breaks == [], (breaks, xs[:3])
