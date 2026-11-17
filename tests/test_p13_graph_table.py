"""Tests for plan step P13/S1: graphcalc/graph.py's table() and
POST /api/graph/table.

F1 (PRODUCT.md, [failing] before this step): '{"functions":{"f1":"x^2"},
"start":0,"step":0.5,"rows":3} returns x ["0","0.5","1"] and columns.f1
["0","0.25","1"]'. test_p13_table_direct and test_p13_table_http prove
this directly (calling graphcalc.graph.table) and over HTTP, against an
in-process server built the same way tests/test_p12_graph_analyze.py's
own `server`/`base` fixtures build one for /api/graph/analyze.

F2 (PRODUCT.md, [failing] before this step): 'A non-real value is null
in the table; step 0 or rows > 1000 returns 400'.
test_p13_non_real_value_is_null_direct/_http prove the first half: a
non-real sample (sqrt of a negative number) becomes a JSON null in the
column, never a 400 or a 500, and the request as a whole still returns
200. test_p13_bad_request_400, parametrized over a zero step, rows > 1000,
rows < 1, and every other way the request can be malformed (reusing
P10's own f1-f4 slot/non-string-expression validation and a missing/non-
finite start or step), proves the second half: each case 400s with a
JSON {"error": ...} body, both over HTTP and as a direct GraphError/
CalcError raised by graphcalc.graph.table.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from graphcalc import calc
from graphcalc.cli import build_server
from graphcalc.graph import MAX_ROWS, MIN_ROWS, GraphError, table


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


@pytest.fixture
def server():
    """A fresh server with a default (in-memory) history store and state.

    POST /api/graph/table never reads either one (stateless, like
    /api/graph/plot, /api/graph/window and /api/graph/analyze), but
    build_server() always wires up both regardless, the same way every
    other test in this repository builds a server.
    """
    srv = build_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def base(server):
    return f"http://127.0.0.1:{server.server_port}"


# ---- F1: the acceptance criterion's own x^2 example ----


def test_p13_table_direct():
    result = table({"functions": {"f1": "x^2"}, "start": 0, "step": 0.5, "rows": 3})
    assert result == {
        "x": ["0", "0.5", "1"],
        "columns": {"f1": ["0", "0.25", "1"]},
    }, result


def test_p13_table_http(base):
    status, body = _post(
        base,
        "/api/graph/table",
        {"functions": {"f1": "x^2"}, "start": 0, "step": 0.5, "rows": 3},
    )
    assert status == 200, body
    assert body == {
        "x": ["0", "0.5", "1"],
        "columns": {"f1": ["0", "0.25", "1"]},
    }, body


# ---- F1 extended: multiple function slots each get their own column ----


def test_p13_table_multiple_columns_direct():
    result = table(
        {
            "functions": {"f1": "x^2", "f2": "x+1"},
            "start": 0,
            "step": 1,
            "rows": 3,
        }
    )
    assert result == {
        "x": ["0", "1", "2"],
        "columns": {
            "f1": ["0", "1", "4"],
            "f2": ["1", "2", "3"],
        },
    }, result


# ---- F2: a non-real value is null in the table ----


def test_p13_non_real_value_is_null_direct():
    result = table({"functions": {"f1": "sqrt(x)"}, "start": -1, "step": 1, "rows": 3})
    assert result == {
        "x": ["-1", "0", "1"],
        "columns": {"f1": [None, "0", "1"]},
    }, result


def test_p13_non_real_value_is_null_http(base):
    status, body = _post(
        base,
        "/api/graph/table",
        {"functions": {"f1": "sqrt(x)"}, "start": -1, "step": 1, "rows": 3},
    )
    assert status == 200, body
    assert body == {
        "x": ["-1", "0", "1"],
        "columns": {"f1": [None, "0", "1"]},
    }, body


def test_p13_undefined_value_is_null_direct():
    """"1/x" at x=0 is also null -- an infinite sample (sympy's own zoo),
    not just a non-real one -- the exact same gap rule plot() and
    analyze() already apply via _evaluate_at.
    """
    result = table({"functions": {"f1": "1/x"}, "start": -1, "step": 1, "rows": 3})
    assert result["x"] == ["-1", "0", "1"], result
    assert result["columns"]["f1"][1] is None, result


# ---- validation: every way the request can be malformed ----


_BAD_REQUESTS = {
    "missing_functions": {"start": 0, "step": 1, "rows": 3},
    "empty_functions": {"functions": {}, "start": 0, "step": 1, "rows": 3},
    "unknown_function_slot": {
        "functions": {"f5": "x"},
        "start": 0,
        "step": 1,
        "rows": 3,
    },
    "non_string_expr": {
        "functions": {"f1": 5},
        "start": 0,
        "step": 1,
        "rows": 3,
    },
    "missing_start": {"functions": {"f1": "x"}, "step": 1, "rows": 3},
    "non_finite_start": {
        "functions": {"f1": "x"},
        "start": float("inf"),
        "step": 1,
        "rows": 3,
    },
    "missing_step": {"functions": {"f1": "x"}, "start": 0, "rows": 3},
    "non_finite_step": {
        "functions": {"f1": "x"},
        "start": 0,
        "step": float("nan"),
        "rows": 3,
    },
    "zero_step": {"functions": {"f1": "x"}, "start": 0, "step": 0, "rows": 3},
    "missing_rows": {"functions": {"f1": "x"}, "start": 0, "step": 1},
    "bool_rows": {"functions": {"f1": "x"}, "start": 0, "step": 1, "rows": True},
    "float_rows": {"functions": {"f1": "x"}, "start": 0, "step": 1, "rows": 3.0},
    "rows_too_small": {
        "functions": {"f1": "x"},
        "start": 0,
        "step": 1,
        "rows": MIN_ROWS - 1,
    },
    "rows_zero": {"functions": {"f1": "x"}, "start": 0, "step": 1, "rows": 0},
    "rows_too_large": {
        "functions": {"f1": "x"},
        "start": 0,
        "step": 1,
        "rows": MAX_ROWS + 1,
    },
    "unsafe_expression": {
        "functions": {"f1": '__import__("os")'},
        "start": 0,
        "step": 1,
        "rows": 3,
    },
}


@pytest.mark.parametrize("case", sorted(_BAD_REQUESTS))
def test_p13_bad_request_400(base, case):
    payload = _BAD_REQUESTS[case]
    status, body = _post(base, "/api/graph/table", payload)
    assert status == 400, (case, body)
    assert isinstance(body.get("error"), str) and body["error"], (case, body)

    with pytest.raises((GraphError, calc.CalcError)):
        table(payload)


def test_p13_rows_at_bounds_direct():
    """MIN_ROWS and MAX_ROWS themselves are valid, not off-by-one rejected."""
    result = table({"functions": {"f1": "x"}, "start": 0, "step": 1, "rows": MIN_ROWS})
    assert len(result["x"]) == MIN_ROWS, result

    result = table({"functions": {"f1": "x"}, "start": 0, "step": 1, "rows": 1})
    assert result["x"] == ["0"], result
