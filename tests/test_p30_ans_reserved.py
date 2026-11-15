"""Tests for treating "ans" as a reserved name (plan step P30, owner revision
2026-11-14: "ans:=5 refused").

"ans" is not one of graphcalc.calc._rad_names()'s constants/functions, but
graphcalc.calc.evaluate and graphcalc.state.CalcState both give it its own
dedicated, non-variable storage slot (the last plain evaluation's result --
see CalcState.set_ans/ans/clear_ans). Accepting "ans:=5" as an ordinary
"name:=expr" variable definition would silently create a second, unrelated
"ans" entry in CalcState's `variables` map while leaving the real stored
answer untouched -- never what a user typing "ans:=5" would expect, and
confusing to debug since evaluate() always prefers the dedicated ans slot
over a same-named stored variable.

graphcalc.names.RESERVED_NAMES now includes "ans" on top of calc._rad_names()
and {"i", "oo", "nan"}, so graphcalc.names.check_not_constant("ans") raises
the same CalcError every other reserved name already does, and graphcalc.
cli._handle_calc_evaluate's existing check_not_constant(name) call -- run for
both "name:=expr" and "f(x):=expr" before any evaluation or storage happens
-- rejects "ans:=5" (and "ans(x):=1") as a 400 "cannot redefine constant
ans", exactly like "pi:=3" is already rejected.
"""

import json
import threading
import urllib.error
import urllib.request

from graphcalc import names
from graphcalc.calc import CalcError
from graphcalc.cli import build_server


def _post(base, path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def _start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


def _stop(server):
    server.shutdown()
    server.server_close()


# ---- unit test: names.check_not_constant rejects "ans" directly ----


def test_check_not_constant_rejects_ans():
    assert "ans" in names.RESERVED_NAMES
    try:
        names.check_not_constant("ans")
    except CalcError as exc:
        assert str(exc) == "cannot redefine constant ans"
    else:
        raise AssertionError("check_not_constant('ans') did not raise")


# ---- F1: {"expr":"ans:=5"} is a 400, and "ans" keeps meaning 2+2's result ----


def test_ans_assignment_returns_400_and_leaves_ans_unchanged():
    srv = build_server(0)
    base = _start(srv)
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "2+2"})
        assert status == 200, body
        assert body["exact"] == "4", body

        status, body = _post(base, "/api/calc/evaluate", {"expr": "ans:=5"})
        assert status == 400, body
        assert body == {"error": "cannot redefine constant ans"}

        status, body = _post(base, "/api/calc/evaluate", {"expr": "ans"})
        assert status == 200, body
        assert body["exact"] == "4", body
    finally:
        _stop(srv)


def test_ans_assignment_rejected_before_any_history_or_state_change():
    srv = build_server(0)
    base = _start(srv)
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "2+2"})
        assert status == 200, body

        status, body = _post(base, "/api/calc/evaluate", {"expr": "ans:=5"})
        assert status == 400, body

        # "ans" was never stored as an ordinary variable.
        with urllib.request.urlopen(base + "/api/calc/vars") as res:
            vars_status = res.status
            vars_body = json.loads(res.read().decode("utf-8"))
        assert vars_status == 200
        assert vars_body == {"variables": {}, "functions": {}}

        # The history store still only has the one "2+2" entry.
        with urllib.request.urlopen(base + "/api/calc/history") as res:
            history_status = res.status
            history_body = json.loads(res.read().decode("utf-8"))
        assert history_status == 200
        assert [entry["expr"] for entry in history_body["history"]] == ["2+2"]
    finally:
        _stop(srv)


# ---- "ans(x):=1" (function syntax) is rejected the same way ----


def test_ans_function_definition_returns_400():
    srv = build_server(0)
    base = _start(srv)
    try:
        status, body = _post(base, "/api/calc/evaluate", {"expr": "ans(x):=1"})
        assert status == 400, body
        assert body == {"error": "cannot redefine constant ans"}
    finally:
        _stop(srv)
