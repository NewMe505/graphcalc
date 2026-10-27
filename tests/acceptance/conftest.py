"""Black-box acceptance tests: scio build runs them against the started app."""

import os

import pytest


@pytest.fixture
def app_url():
    url = os.environ.get("APP_URL")
    if not url:
        pytest.skip("APP_URL not set: scio build starts the app for these tests")
    return url
