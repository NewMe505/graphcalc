"""Black-box acceptance tests: scio build runs them against the started app."""

import os
import threading
from http.server import HTTPServer

import pytest

from graphcalc.cli import Handler


@pytest.fixture
def app_url():
    url = os.environ.get("APP_URL")
    if not url:
        pytest.skip("APP_URL not set: scio build starts the app for these tests")
    return url


@pytest.fixture(scope="module")
def browser():
    """A Playwright Chromium browser, or a skip for any test that asks for one.

    This harness has no browser dependency of its own (every other
    acceptance check reads HTTP responses, never pixels). P34's tests need
    an actual rendered canvas, so this fixture provides one when Playwright
    and its Chromium build are available, and skips cleanly -- never
    fails -- when either is missing, per plan step P34/S1.
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
def live_server():
    """Starts graphcalc's own HTTP server on 127.0.0.1 for a browser to visit.

    Independent of APP_URL (which only scio build's own black-box run
    sets): a pixel test needs a real page in a real browser, served
    in-process here the same way tests/test_p14_graphs_ui.py and
    tests/test_calc_ui.py already start their own HTTPServer for their own
    (non-browser) HTTP checks.
    """
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
