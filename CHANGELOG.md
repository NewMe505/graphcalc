# Changelog

## [Unreleased]
### Added
- Walking skeleton: package, `--version`, smoke test, CI (SCIO bootstrap).
- `GET /` serves the static UI shell: one HTML page with the four tab panels
  (`tab-calculator`, `tab-graphs`, `tab-lists`, `tab-cas`) and a `graph-canvas`
  canvas, plus plain `app.js`/`style.css` -- no build step, no external
  resources.
- `GET /static/<name>` serves `graphcalc/static/*` with an explicit content
  type for `.js` (`application/javascript`), `.css` (`text/css`) and `.html`;
  any other extension, or a missing file, answers a JSON 404. The static
  files ship as package data (`pyproject.toml`'s `package-data`).

### Security
- Hardened the `/static/<name>` route against path traversal: reject a NUL
  byte, a backslash or an absolute segment in the decoded name outright, and
  require the resolved path to stay inside `STATIC_DIR.resolve()`. Unknown
  routes (e.g. `/server.py`) keep answering a JSON 404, never a 500.
