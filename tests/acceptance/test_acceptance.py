import json
import urllib.request


def test_health_endpoint_black_box(app_url):
    with urllib.request.urlopen(app_url + "/health", timeout=5) as resp:
        assert resp.status == 200
        body = json.loads(resp.read())
    assert body == {"status": "ok"}
