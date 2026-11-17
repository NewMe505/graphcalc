"""Real-browser tests for plan steps P18/S2 and P18/S3: the Lists &
Statistics tab's app.js wiring to /api/lists, /api/stats/onevar and
/api/stats/regression.

F3 (plan step P18, feature list): "Real browser: L1 [1,2,3,4,5] appears in
list-grid; choosing L1 in stats-list shows n 5 and mean 3 in stats-output."
test_p18_browser_onevar proves exactly that -- the fix lives in
graphcalc/static/app.js's loadLists()/statsRefreshOnevar(), which only a
browser executes, so this drives a headless Chromium page through a real
server the same way tests/acceptance/test_p34_asymptote.py's own `browser`
fixture does for the Graphs tab (plan step P34/S1): the whole module skips
outright -- never fails -- when Playwright or its Chromium build is not
available.

F4 (plan step P18, feature list): "Real browser: a linear regression of
L2 [2,4,6] on L1 [1,2,3] shows a = 2 and b = 0 in regression-output and
draws on stats-canvas (at least one pixel is not blank)."
test_p18_browser_regression proves exactly that, driving app.js's own
regressionRun() (plan step P18/S3) the same way test_p18_browser_onevar
drives statsRefreshOnevar() above -- both owner-revision (2026-11-17)
checks PRODUCT.md calls for.

The server itself is started the same way tests/test_p16_onevar.py's own
test_onevar_400_empty_list starts one: an on-disk CalcState backed by a
temporary data dir (tmp_path), rather than the in-memory default
build_server(0) tests/test_p14_graphs_ui.py uses, so this test's own
PUT /api/lists/L1 never touches another test's (or a real run's) state
file.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from graphcalc.cli import build_server
from graphcalc.history import StateBackedHistoryStore
from graphcalc.state import CalcState


def _put(base, path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


@pytest.fixture
def browser():
    """A Playwright Chromium browser, or a skip for this module when either
    Playwright or its Chromium build is unavailable -- same fixture shape as
    tests/acceptance/conftest.py's own module-scoped `browser` fixture (plan
    step P34/S1), kept local here since this file lives outside
    tests/acceptance/ and must still skip rather than fail without one.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    playwright = playwright_module.sync_playwright().start()
    try:
        instance = playwright.chromium.launch()
    except Exception as exc:
        playwright.stop()
        pytest.skip(f"no Chromium browser available: {exc}")
    try:
        yield instance
    finally:
        instance.close()
        playwright.stop()


@pytest.fixture
def live_server(tmp_path):
    """Starts graphcalc's own HTTP server on a free port, backed by a state
    file under a temporary data dir -- same pattern tests/test_p16_onevar.py's
    own test_onevar_400_empty_list uses to isolate one test's stored lists
    from every other test's.
    """
    state_path = tmp_path / "state.json"
    state = CalcState(str(state_path))
    server = build_server(0, history_store=StateBackedHistoryStore(state), state=state)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_p18_browser_onevar(browser, live_server):
    status, body = _put(live_server, "/api/lists/L1", {"values": ["1", "2", "3", "4", "5"]})
    assert status == 200, body

    page = browser.new_page()
    try:
        page.goto(live_server + "/")
        # "tab-lists" is the panel itself (hidden until active); the
        # clickable control is its tab button, which carries
        # data-tab="tab-lists" instead of its own id
        # (graphcalc/static/index.html). Clicking it also triggers app.js's
        # loadLists() a second time (plan step P18/S2's "Call it on
        # DOMContentLoaded and whenever the tab-lists tab button is
        # clicked"), which this test relies on just as much as the initial
        # DOMContentLoaded call.
        page.click('button[data-tab="tab-lists"]')

        # loadLists() does GET /api/lists then one GET /api/lists/<name>
        # per name, all asynchronous; wait until list-grid actually shows
        # L1's own heading before reading anything out of it.
        page.wait_for_function(
            "document.getElementById('list-grid').textContent.includes('L1')"
        )
        grid_text = page.inner_text("#list-grid")
        assert "L1" in grid_text, grid_text
        for value in ("1", "2", "3", "4", "5"):
            assert value in grid_text, grid_text

        # stats-list is filled by the same loadLists() call; select L1 to
        # fire statsRefreshOnevar()'s POST /api/stats/onevar.
        page.wait_for_function(
            "document.querySelector('#stats-list option[value=\"L1\"]') !== null"
        )
        page.select_option("#stats-list", "L1")

        # statsRenderOutput renders one <dt>/<dd> pair per returned key;
        # pull them into a plain object so "n" and "mean" are checked
        # exactly, not just as substrings somewhere in stats-output's text
        # (which could spuriously match e.g. "max" containing no "5", but
        # could just as easily collide with another key's own value).
        page.wait_for_function(
            "document.querySelectorAll('#stats-output dt').length > 0"
        )
        stats = page.evaluate(
            """() => {
                const out = {};
                document.querySelectorAll('#stats-output dt').forEach((dt) => {
                    out[dt.textContent] = dt.nextElementSibling.textContent;
                });
                return out;
            }"""
        )
        assert stats.get("n") == "5", stats
        assert stats.get("mean") == "3", stats
    finally:
        page.close()


def test_p18_browser_regression(browser, live_server):
    status, body = _put(live_server, "/api/lists/L1", {"values": ["1", "2", "3"]})
    assert status == 200, body
    status, body = _put(live_server, "/api/lists/L2", {"values": ["2", "4", "6"]})
    assert status == 200, body

    page = browser.new_page()
    try:
        page.goto(live_server + "/")
        page.click('button[data-tab="tab-lists"]')

        # loadLists() fills regression-x/regression-y the same way it
        # fills stats-list; wait until both L1 and L2 are offered in both
        # before selecting them.
        page.wait_for_function(
            "document.querySelector('#regression-x option[value=\"L1\"]') !== null"
            " && document.querySelector('#regression-y option[value=\"L2\"]') !== null"
        )
        page.select_option("#regression-model", "linear")
        page.select_option("#regression-x", "L1")
        page.select_option("#regression-y", "L2")
        page.click("#regression-run")

        # regressionRun() POSTs to /api/stats/regression and renders the
        # response's own coefficients as "key = value" lines
        # (statsRenderRegression); wait for the fit to land, then check
        # both coefficients as plain substrings of regression-output's text
        # -- exactly the strings PRODUCT.md's own acceptance text names.
        page.wait_for_function(
            "document.getElementById('regression-output').textContent.includes('a = 2')"
        )
        output_text = page.inner_text("#regression-output")
        assert "a = 2" in output_text, output_text
        assert "b = 0" in output_text, output_text

        # statsRenderRegressionPlot draws the data points and the fitted
        # line on stats-canvas in the same synchronous callback that just
        # set regression-output's text above, so by now the canvas is no
        # longer blank: at least one pixel's alpha channel must be
        # non-zero, the same "did it actually draw something" check
        # tests/acceptance/test_p34_asymptote.py uses for graph-canvas.
        has_pixel = page.evaluate(
            """() => {
                const canvas = document.getElementById('stats-canvas');
                const ctx = canvas.getContext('2d');
                const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                for (let i = 3; i < data.length; i += 4) {
                    if (data[i] !== 0) {
                        return true;
                    }
                }
                return false;
            }"""
        )
        assert has_pixel
    finally:
        page.close()
