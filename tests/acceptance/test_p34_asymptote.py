"""Acceptance tests for plan step P34/S1 (bug #40): on the Graphs tab, a
curve must never be drawn across a vertical asymptote, while a steep but
continuous curve must still be drawn whole.

PRODUCT.md's acceptance criteria are pixel-level: no pixel of graph-canvas
within 2px of the asymptote's x column may carry f1's colour (#1f77b4),
while that colour must still appear on both sides of it; conversely a
steep continuous curve ("10*x") must be unbroken, so a pixel near the
canvas point for one of its own data points must carry f1's colour.

These are real-browser checks -- the fix lives in graphcalc/static/app.js's
canvas draw loop, which only a browser executes -- so each test drives a
headless Chromium page through the acceptance harness's `browser` and
`live_server` fixtures (tests/acceptance/conftest.py). Per plan step
P34/S1, the whole module skips outright when the harness has no browser
(Playwright not installed, or no Chromium binary downloaded), rather than
failing.

The canvas is 600x400 (graphcalc/static/index.html); the window used
throughout is -5..5 on both axes, so graphToPixel's own mapping (app.js)
gives, for any data point (x, y):
    px = (x - (-5)) / 10 * 600 = (x + 5) * 60
    py = 400 - (y - (-5)) / 10 * 400 = 400 - (y + 5) * 40
"""

import math

import pytest

F1_RGB = (0x1F, 0x77, 0xB4)  # #1f77b4
CANVAS_WIDTH = 600
CANVAS_HEIGHT = 400
WINDOW = {"xmin": -5, "xmax": 5, "ymin": -5, "ymax": 5}


def _px_x(x):
    return (x - WINDOW["xmin"]) / (WINDOW["xmax"] - WINDOW["xmin"]) * CANVAS_WIDTH


def _px_y(y):
    return CANVAS_HEIGHT - (y - WINDOW["ymin"]) / (WINDOW["ymax"] - WINDOW["ymin"]) * CANVAS_HEIGHT


# JS run inside the page: scans graph-canvas's pixels for f1's colour
# (allowing a small tolerance, and requiring a non-trivial alpha so a
# near-transparent antialiased edge pixel is not mistaken for a drawn
# line), within three column ranges: within 2px of the asymptote/pole,
# a wide band to its left, and a wide band to its right.
_COLUMN_SCAN_JS = """
([poleCol, leftBound, rightBound, targetRgb]) => {
  const canvas = document.getElementById('graph-canvas');
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  const data = ctx.getImageData(0, 0, width, height).data;
  const [tr, tg, tb] = targetRgb;
  const tol = 24;
  const alphaMin = 128;

  function matchesAt(x, y) {
    const i = (y * width + x) * 4;
    if (data[i + 3] < alphaMin) return false;
    return (
      Math.abs(data[i] - tr) <= tol &&
      Math.abs(data[i + 1] - tg) <= tol &&
      Math.abs(data[i + 2] - tb) <= tol
    );
  }

  function colRangeHasColor(colStart, colEnd) {
    const cs = Math.max(0, Math.floor(colStart));
    const ce = Math.min(width - 1, Math.ceil(colEnd));
    for (let x = cs; x <= ce; x++) {
      for (let y = 0; y < height; y++) {
        if (matchesAt(x, y)) return true;
      }
    }
    return false;
  }

  return {
    nearPole: colRangeHasColor(poleCol - 2, poleCol + 2),
    left: colRangeHasColor(0, leftBound),
    right: colRangeHasColor(rightBound, width - 1),
  };
}
"""

# JS run inside the page: true iff some pixel within `radius` px of
# (px, py) carries f1's colour (same tolerance/alpha rules as above).
_POINT_SCAN_JS = """
([px, py, radius, targetRgb]) => {
  const canvas = document.getElementById('graph-canvas');
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  const data = ctx.getImageData(0, 0, width, height).data;
  const [tr, tg, tb] = targetRgb;
  const tol = 24;
  const alphaMin = 128;

  function matchesAt(x, y) {
    const i = (y * width + x) * 4;
    if (data[i + 3] < alphaMin) return false;
    return (
      Math.abs(data[i] - tr) <= tol &&
      Math.abs(data[i + 1] - tg) <= tol &&
      Math.abs(data[i + 2] - tb) <= tol
    );
  }

  const xs = Math.max(0, Math.floor(px - radius));
  const xe = Math.min(width - 1, Math.ceil(px + radius));
  const ys = Math.max(0, Math.floor(py - radius));
  const ye = Math.min(height - 1, Math.ceil(py + radius));
  for (let x = xs; x <= xe; x++) {
    for (let y = ys; y <= ye; y++) {
      const dx = x - px;
      const dy = y - py;
      if (dx * dx + dy * dy <= radius * radius + 1e-9 && matchesAt(x, y)) {
        return true;
      }
    }
  }
  return false;
}
"""


@pytest.fixture
def graph_page(browser, live_server):
    page = browser.new_page()
    page.goto(live_server + "/")
    # "tab-graphs" is the panel itself (hidden until active); the clickable
    # control is its tab button, which carries data-tab="tab-graphs"
    # instead of its own id (graphcalc/static/index.html).
    page.click('button[data-tab="tab-graphs"]')
    # The page's own load-time "standard window" fetch
    # (graphWindowAction({action:"standard"}), app.js) fills the window
    # inputs asynchronously; wait for it so our own window below is not
    # clobbered by it landing late.
    page.wait_for_function("document.getElementById('graph-xmin').value !== ''")
    yield page
    page.close()


def _plot_f1(page, expr):
    """Sets f1 and the -5..5 window directly, fires exactly one plot fetch,

    and waits for graph-canvas to be redrawn from its response.
    """
    with page.expect_response("**/api/graph/plot"):
        page.evaluate(
            """([exprText, win]) => {
                document.getElementById('graph-f1').value = exprText;
                document.getElementById('graph-xmin').value = String(win.xmin);
                document.getElementById('graph-xmax').value = String(win.xmax);
                document.getElementById('graph-ymin').value = String(win.ymin);
                document.getElementById('graph-ymax').value = String(win.ymax);
                document.getElementById('graph-f1').dispatchEvent(new Event('change'));
            }""",
            [expr, WINDOW],
        )
    # graphRenderPlot runs in the fetch's own .then() chain, a microtask
    # queued once the response above resolves; give the page a tick to
    # actually run it before pixels are read.
    page.wait_for_timeout(100)


def _assert_broken_at(page, pole_x):
    pole_col = _px_x(pole_x)
    left_bound = _px_x(pole_x - 0.5)
    right_bound = _px_x(pole_x + 0.5)
    result = page.evaluate(_COLUMN_SCAN_JS, [pole_col, left_bound, right_bound, list(F1_RGB)])
    assert result["nearPole"] is False, f"f1 colour found within 2px of x={pole_x}"
    assert result["left"] is True, f"f1 colour missing left of x={pole_x - 0.5}"
    assert result["right"] is True, f"f1 colour missing right of x={pole_x + 0.5}"


def test_p34_one_over_x_pixels(graph_page):
    _plot_f1(graph_page, "1/x")
    _assert_broken_at(graph_page, 0)


def test_p34_tan_pixels(graph_page):
    _plot_f1(graph_page, "tan(x)")
    _assert_broken_at(graph_page, math.pi / 2)


def test_p34_shifted_pole_pixels(graph_page):
    _plot_f1(graph_page, "1/(x-1)")
    _assert_broken_at(graph_page, 1)


def test_p34_steep_line_pixels(graph_page):
    _plot_f1(graph_page, "10*x")
    px, py = _px_x(0.25), _px_y(2.5)
    found = graph_page.evaluate(_POINT_SCAN_JS, [px, py, 2, list(F1_RGB)])
    assert found is True, "f1 colour missing near canvas point for (0.25, 2.5)"
