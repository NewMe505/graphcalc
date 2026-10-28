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

## Develop

```
pip install ruff pytest
ruff check --no-cache --select E9,F63,F7,F82,F821 --output-format concise .
python -m pytest -q --tb=short -p no:cacheprovider -rfE --no-header
```

Product specification: [PRODUCT.md](PRODUCT.md). Progress: `.scio/product/progress.json`.
