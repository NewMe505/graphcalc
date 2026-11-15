import json
import urllib.error
import urllib.request


def test_health_endpoint_black_box(app_url):
    with urllib.request.urlopen(app_url + "/health", timeout=5) as resp:
        assert resp.status == 200
        body = json.loads(resp.read())
    assert body == {"status": "ok"}


def _post_evaluate(app_url, expr):
    data = json.dumps({"expr": expr}).encode("utf-8")
    req = urllib.request.Request(
        app_url + "/api/calc/evaluate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


# ---- P29/S1: malformed numbers still 400, as one bad number, never two
# numbers read as an implied product (owner revision, 2026-11-15) ----


def test_p29_reject_malformed_http(app_url):
    for expr in ("1..2", "1.2.3", "."):
        status, body = _post_evaluate(app_url, expr)
        assert status == 400, f"{expr!r} -> status {status}, body {body}"
        assert isinstance(body.get("error"), str), f"{expr!r} -> body {body}"


def test_p29_longest_run_http(app_url):
    for expr in ("1.2.3", "1..2", "1.5e3.2"):
        status, body = _post_evaluate(app_url, expr)
        assert status == 400, f"{expr!r} -> status {status}, body {body}"
        assert isinstance(body.get("error"), str), f"{expr!r} -> body {body}"


# ---- P29/S2: '.5' and '5.' accepted, as on a TI (owner revision,
# 2026-11-14/2026-11-15) ----


def test_p29_accept_http(app_url):
    status, body = _post_evaluate(app_url, ".5")
    assert status == 200, f".5 -> status {status}, body {body}"
    assert body["decimal"] == "0.5"

    status, body = _post_evaluate(app_url, "5.")
    assert status == 200, f"5. -> status {status}, body {body}"
    assert body["decimal"] == "5"

    status, body = _post_evaluate(app_url, "0005")
    assert status == 200, f"0005 -> status {status}, body {body}"
    assert body["exact"] == "5"

    # Mixed cases: implied and explicit multiplication must still work with
    # the newly-accepted leading-dot shape, never misread as a malformed
    # number.
    status, body = _post_evaluate(app_url, "2*.5")
    assert status == 200, f"2*.5 -> status {status}, body {body}"
    assert body["decimal"] == "1"

    status, body = _post_evaluate(app_url, ".5x")
    assert status == 200, f".5x -> status {status}, body {body}"
    assert body["exact"] == "0.5*x"
