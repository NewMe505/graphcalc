"""Acceptance test for plan step P22/S2: the CAS tab is wired to every CAS
endpoint.

PRODUCT.md's first "checked in a real browser" P22 acceptance criterion is
a browser-rendered-text check, not a raw HTTP-response check -- the wiring
lives in graphcalc/static/app.js, which only a browser executes -- so this
module drives a headless Chromium page through the acceptance harness's
`browser` and `live_server` fixtures (tests/acceptance/conftest.py), the
same pattern tests/acceptance/test_p34_asymptote.py already uses for the
Graphs tab. Per that module's own convention, the whole module skips
outright when the harness has no browser (Playwright not installed, or no
Chromium binary downloaded), rather than failing.
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
