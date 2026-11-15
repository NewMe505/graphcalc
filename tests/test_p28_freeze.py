"""Tests for the power-size guard (plan step P28/S1, Bug #20 fix).

Before this fix, sympy's parse_expr evaluated a power the instant it built
that AST node: "9^9^9" (9**(9**9), ~369,671,667 decimal digits) or
"10^10^10" (10**(10**10), 10,000,000,000 digits) made it try to materialize
an astronomically large exact integer, which could freeze graphcalc's
single-threaded HTTP server for every other request -- even a completely
unrelated "1+1" -- for minutes or far longer.

graphcalc.limits.is_power_too_large now estimates a power's result size
(via float log10 arithmetic, never computing the exact value) before
graphcalc.calc.evaluate's own, real parse_expr call ever runs; a power
estimated too large gets a quick domain_error instead. These tests go
through the HTTP API in-process (the same pattern tests/
test_p27_evaluator_hardening.py uses), proving both that the freeze-prone
requests answer quickly with a non-null domain_error or a 400 JSON error,
and that the request right after them still gets answered normally.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer

from graphcalc.calc import evaluate
from graphcalc.cli import Handler

# Generous relative to the 10-second acceptance budget, but still proves
# "answers quickly" rather than "the test's own timeout fired first".
TIMEOUT_SECONDS = 10


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _post(base, path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


# ---- F1: 9^9^9 and 10^10^10 each answer within 10s, then "1+1" still works ----


def test_p28_power_tower_then_simple_request_all_answered_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"

        for expr in ("9^9^9", "10^10^10"):
            t0 = time.monotonic()
            status, body = _post(base, "/api/calc/evaluate", {"expr": expr})
            elapsed = time.monotonic() - t0
            assert elapsed < TIMEOUT_SECONDS, (expr, elapsed, body)
            if status == 200:
                assert body.get("domain_error") is not None, (expr, body)
            else:
                assert status == 400, (expr, status, body)
                assert isinstance(body.get("error"), str) and body["error"], body

        # The server must still be responsive for the very next request.
        t0 = time.monotonic()
        status, body = _post(base, "/api/calc/evaluate", {"expr": "1+1"})
        elapsed = time.monotonic() - t0
        assert elapsed < TIMEOUT_SECONDS, (elapsed, body)
        assert status == 200, body
        assert body["exact"] == "2", body
    finally:
        server.shutdown()
        server.server_close()


def test_p28_power_tower_in_process_each_answers_within_10_seconds():
    for expr in ("9^9^9", "10^10^10"):
        t0 = time.monotonic()
        result = evaluate(expr)
        elapsed = time.monotonic() - t0
        assert elapsed < TIMEOUT_SECONDS, (expr, elapsed)
        assert result["domain_error"] is not None, (expr, result)
        assert result["exact"] is None, (expr, result)
        assert result["decimal"] is None, (expr, result)
        assert result["complex"] is None, (expr, result)

    # Evaluating right after the two towers answers exactly "2" -- nothing
    # about the guard's own extra parse leaks state into the next call.
    result = evaluate("1+1")
    assert result["exact"] == "2"
    assert result["domain_error"] is None


# ---- F1 (planner notes): no forbidden wording in any of these responses ----


def test_p28_power_tower_response_has_no_forbidden_wording_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        for expr in ("9^9^9", "10^10^10", "2^10000000"):
            _, body = _post(base, "/api/calc/evaluate", {"expr": expr})
            text = json.dumps(body)
            assert "Exceeds the limit" not in text, (expr, body)
            assert "unexpected error" not in text, (expr, body)
    finally:
        server.shutdown()
        server.server_close()


def test_p28_2_to_the_20000_flagged_before_pythons_own_str_digit_limit():
    # 2**20000 has ~6,021 decimal digits -- far below the astronomical
    # sizes "9^9^9"/"10^10^10"/"2^10000000" reach, but still past Python's
    # own default integer-to-string conversion limit (4300 digits on
    # 3.11+). Before MAX_POWER_DIGITS was lowered from 10**5 to 4_000, this
    # guard let such a result through, and graphcalc.calc.evaluate's later
    # str(result) call (building the "exact" field) raised ValueError
    # ("Exceeds the limit (4300 digits)..."), which graphcalc.cli's
    # catch-all turned into exactly the forbidden "unexpected error:
    # Exceeds the limit..." wording the acceptance criteria ban.
    result = evaluate("2^20000")
    assert result["domain_error"] is not None, result
    assert result["exact"] is None, result
    text = json.dumps(result)
    assert "Exceeds the limit" not in text, result
    assert "unexpected error" not in text, result


def test_p28_2_to_the_10000000_answers_within_10_seconds_no_forbidden_wording():
    t0 = time.monotonic()
    result = evaluate("2^10000000")
    elapsed = time.monotonic() - t0
    assert elapsed < TIMEOUT_SECONDS, elapsed
    text = json.dumps(result)
    assert "Exceeds the limit" not in text, result
    assert "unexpected error" not in text, result


# ---- F1 (planner notes): 10^1000 still gives exact decimal "1e1000" ----


def test_p28_10_to_the_1000_still_gives_decimal_1e1000():
    result = evaluate("10^1000")
    assert result["domain_error"] is None, result
    assert result["decimal"] == "1e1000", result


def test_p28_10_to_the_1000_still_gives_decimal_1e1000_over_http():
    server = _start_server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, body = _post(base, "/api/calc/evaluate", {"expr": "10^1000"})
        assert status == 200, body
        assert body["domain_error"] is None, body
        assert body["decimal"] == "1e1000", body
    finally:
        server.shutdown()
        server.server_close()
