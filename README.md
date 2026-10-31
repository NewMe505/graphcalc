# GraphCalc: a local CAS graphing calculator in the browser

A local graphing calculator inspired by the TI-Nspire CX CAS. A Python HTTP server bound to 127.0.0.1 does all the math through a JSON API with one endpoint per operation, using sympy. It also serves one plain HTML/CSS/JS page with four tabs: Calculator, Graphs, Lists & Statistics, and CAS. The page only draws what the API returns. Every result can be checked over HTTP. A client mistake gets a 400 with a JSON error and never a 500. State is kept on disk, so it survives a restart.

## Run

<!-- scio:run -->
```
python -m graphcalc --version
```
<!-- scio:run-end -->

## Use

Start the server, e.g. `python -m graphcalc --port 8000 --in-memory`, then open
`http://127.0.0.1:8000/` in a browser. `GET /` serves one plain HTML/CSS/JS
page (no build step, no CDN or other external resources) with four tabs:
Calculator, Graphs, Lists & Statistics, and CAS. The page only draws what the
JSON API returns.

The UI shell is served from two routes:
- `GET /` -- `text/html`, the tab page (`tab-calculator`, `tab-graphs`,
  `tab-lists`, `tab-cas`, and a `graph-canvas` canvas on the Graphs tab).
- `GET /static/<name>` -- the page's own `.js`/`.css`/`.html` files with an
  explicit content type (e.g. `application/javascript`, `text/css`). Any
  other path, including a traversal attempt, answers a JSON 404, never a 500.

The calculator's math goes through a JSON API, one endpoint per operation:
- `POST /api/calc/evaluate` -- body `{"expr": str, "mode": "rad"|"deg"}`
  (`mode` is optional, default `"rad"`). Parses `+ - * / ^`, parentheses and
  implied multiplication (e.g. `"2(3+1)^2"`). Answers 200 with
  `{"expr", "exact", "decimal", "complex", "domain_error"}`: `exact` is
  sympy's simplified result as a string, `decimal` is a 12-significant-digit
  string with no trailing zeros (e.g. `"1/3"` gives `"0.333333333333"`), and
  `complex`/`domain_error` are `null` unless set. A parse error or an invalid
  `mode` answers 400 with `{"error": <message>}`; a body with no `expr`
  answers 400 with `{"error": "missing parameter: expr"}`. Never a 500.

  ```
  curl -s -X POST http://127.0.0.1:8000/api/calc/evaluate \
    -H "Content-Type: application/json" \
    -d '{"expr": "1/3+1/6"}'
  # {"expr": "1/3+1/6", "exact": "1/2", "decimal": "0.5", "complex": null, "domain_error": null}
  ```

## Develop

```
pip install -e . ruff pytest
ruff check --no-cache --select E9,F63,F7,F82,F821 --output-format concise .
python -m pytest -q --tb=short -p no:cacheprovider -rfE --no-header
```

Product specification: [PRODUCT.md](PRODUCT.md). Progress: `.scio/product/progress.json`.
