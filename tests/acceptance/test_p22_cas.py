"""Acceptance tests for plan step P22 (S2 and S3): the CAS tab is wired to
every CAS endpoint, including its error handling.

PRODUCT.md's two "checked in a real browser" P22 acceptance criteria are
browser-rendered-text checks, not raw HTTP-response checks -- the wiring
lives in graphcalc/static/app.js, which only a browser executes -- so this
module drives a headless Chromium page through the acceptance harness's
`browser` and `live_server` fixtures (tests/acceptance/conftest.py), the
same pattern tests/acceptance/test_p34_asymptote.py already uses for the
Graphs tab. Per that module's own convention, the whole module skips
outright when the harness has no browser (Playwright not installed, or no
Chromium binary downloaded), rather than failing.

- test_cas_browser_expand_and_derivative (S2): the first criterion's two
  worked examples.
- test_cas_browser_error_then_valid (S3): the second criterion -- a
  malformed expression shows an error in cas-output, and a valid submit
  made right after it still shows its own result, with no trace of the
  earlier error left behind.
"""

import pytest


@pytest.fixture
def cas_page(browser, live_server):
    page = browser.new_page()
    page.goto(live_server + "/")
    # "tab-cas" is the panel itself (hidden until active); the clickable
    # control is its tab button, which carries data-tab="tab-cas" instead
    # of its own id (graphcalc/static/index.html).
    page.click('button[data-tab="tab-cas"]')
    yield page
    page.close()


def test_cas_browser_expand_and_derivative(cas_page):
    cas_page.fill("#cas-input", "(x+1)^2")
    cas_page.select_option("#cas-op", "expand")
    with cas_page.expect_response("**/api/cas/expand"):
        cas_page.click("#cas-submit")
    cas_page.wait_for_function(
        "document.getElementById('cas-output').textContent.includes('x^2 + 2*x + 1')"
    )
    assert "x^2 + 2*x + 1" in cas_page.inner_text("#cas-output")

    cas_page.select_option("#cas-op", "derivative")
    cas_page.fill("#cas-var", "x")
    cas_page.fill("#cas-input", "x*sin(x)")
    with cas_page.expect_response("**/api/cas/derivative"):
        cas_page.click("#cas-submit")
    cas_page.wait_for_function(
        "document.getElementById('cas-output').textContent.includes('x*cos(x) + sin(x)')"
    )
    assert "x*cos(x) + sin(x)" in cas_page.inner_text("#cas-output")


def test_cas_browser_error_then_valid(cas_page):
    """Plan step P22/S3: a malformed submit shows an error in cas-output,
    and the very next (valid) submit fully replaces it with its own result,
    never leaving the error text behind alongside the new one.
    """
    cas_page.fill("#cas-input", "x^^2")
    cas_page.select_option("#cas-op", "simplify")
    with cas_page.expect_response("**/api/cas/simplify"):
        cas_page.click("#cas-submit")
    cas_page.wait_for_function(
        "document.getElementById('cas-output').textContent.includes('rror')"
    )
    error_text = cas_page.inner_text("#cas-output")
    assert "rror" in error_text
    assert error_text.strip() != ""

    cas_page.fill("#cas-input", "(x+1)^2")
    cas_page.select_option("#cas-op", "expand")
    with cas_page.expect_response("**/api/cas/expand"):
        cas_page.click("#cas-submit")
    cas_page.wait_for_function(
        "document.getElementById('cas-output').textContent.includes('x^2 + 2*x + 1')"
    )
    result_text = cas_page.inner_text("#cas-output")
    assert "x^2 + 2*x + 1" in result_text
    assert error_text not in result_text
