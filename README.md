# GraphCalc: a local CAS graphing calculator in the browser

A local graphing calculator inspired by the TI-Nspire CX CAS. A Python HTTP server bound to 127.0.0.1 does all the math through a JSON API with one endpoint per operation, using sympy. It also serves one plain HTML/CSS/JS page with four tabs: Calculator, Graphs, Lists & Statistics, and CAS. The page only draws what the API returns. Every result can be checked over HTTP. A client mistake gets a 400 with a JSON error and never a 500. State is kept on disk, so it survives a restart.

## Run

<!-- scio:run -->
```
python -m graphcalc --version
```
<!-- scio:run-end -->

## Develop

```
pip install ruff pytest
ruff check --no-cache --select E9,F63,F7,F82,F821 --output-format concise .
python -m pytest -q --tb=short -p no:cacheprovider -rfE --no-header
```

Product specification: [PRODUCT.md](PRODUCT.md). Progress: `.scio/product/progress.json`.
