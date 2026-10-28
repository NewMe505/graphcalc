# Changelog

## [Unreleased]
### Added
- Walking skeleton: package, `--version`, smoke test, CI (SCIO bootstrap).

### Security
- Hardened the `/static/<name>` route against path traversal: reject a NUL
  byte, a backslash or an absolute segment in the decoded name outright, and
  require the resolved path to stay inside `STATIC_DIR.resolve()`. Unknown
  routes (e.g. `/server.py`) keep answering a JSON 404, never a 500.
