"""Tests for P33 (bug #27): a long result, value or error never widens the page.

PRODUCT.md's three acceptance criteria:
  - after {"expr":"10^1000"} is evaluated on the Calculator tab, the page in a
    1280px window is no wider than the window (document.documentElement
    .scrollWidth <= window.innerWidth): the 1,001-digit history entry wraps;
  - the same holds for {"expr":"a:=10^1000"} (the variable list),
    {"expr":"f(x):=x+10^1000"} (the function list), and a 400 whose error
    line echoes a long input (1,500 digits followed by "^^3");
  - GET /static/style.css sets overflow-wrap or word-break on body or
    .tab-panel, so long words break on every tab, including tabs built
    later.

The first two need an actual layout engine -- a real browser via Playwright
-- since document.documentElement.scrollWidth is meaningless in a plain
urllib/HTML-parser test. The last one is a plain static-content check.
"""

import re
import threading

import pytest
from http.server import HTTPServer

from graphcalc.cli import Handler

playwright_sync_api = pytest.importorskip("playwright.sync_api")

VIEWPORT = {"width": 1280, "height": 900}


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def base_url():
    server = _start_server()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def calc_page(base_url):
    with playwright_sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport=VIEWPORT)
            page.goto(base_url + "/")
            yield page
        finally:
            browser.close()


def _assert_page_not_wider_than_window(page):
    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width, (scroll_width, inner_width)


def _submit(page, expr):
    page.fill("#calc-input", expr)
    page.click("#calc-submit")


def test_long_result_does_not_widen_the_page(calc_page):
    """F1: {"expr":"10^1000"} wraps its 1,001-digit history entry."""
    _submit(calc_page, "10^1000")
    calc_page.wait_for_function(
        "document.querySelectorAll('#calc-history li').length > 0"
    )
    history_text = calc_page.inner_text("#calc-history")
    assert "0" * 50 in history_text.replace("\n", "")  # sanity: it rendered
    _assert_page_not_wider_than_window(calc_page)


def test_long_variable_value_does_not_widen_the_page(calc_page):
    """F2 (variable list): {"expr":"a:=10^1000"}."""
    _submit(calc_page, "a:=10^1000")
    calc_page.wait_for_function(
        "document.querySelectorAll('#calc-vars dt').length > 0"
    )
    _assert_page_not_wider_than_window(calc_page)


def test_long_function_body_does_not_widen_the_page(calc_page):
    """F2 (function list): {"expr":"f(x):=x+10^1000"}."""
    _submit(calc_page, "f(x):=x+10^1000")
    calc_page.wait_for_function(
        "document.querySelectorAll('#calc-vars dt').length > 0"
    )
    _assert_page_not_wider_than_window(calc_page)


def test_long_bad_input_error_does_not_widen_the_page(calc_page):
    """F2 (error line): a 400 whose error echoes 1,500 digits + "^^3"."""
    bad_expr = ("1" * 1500) + "^^3"
    _submit(calc_page, bad_expr)
    calc_page.wait_for_function(
        "document.getElementById('calc-error').textContent.length > 0"
    )
    error_text = calc_page.inner_text("#calc-error")
    assert "^^3" in error_text  # sanity: the long input was echoed
    _assert_page_not_wider_than_window(calc_page)


def test_style_css_sets_overflow_wrap_or_word_break_on_body_or_tab_panel():
    """F3: GET /static/style.css breaks long words on every tab."""
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        import urllib.request

        with urllib.request.urlopen(base + "/static/style.css") as res:
            assert res.status == 200
            css = res.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    pattern = re.compile(
        r"(body|\.tab-panel)\s*\{[^}]*(overflow-wrap|word-break)\s*:",
        re.DOTALL,
    )
    assert pattern.search(css), css
