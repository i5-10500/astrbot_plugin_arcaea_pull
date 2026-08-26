# AGENTS.md

## Project

This repository contains `astrbot_plugin_arcaea_pull`, an AstrBot plugin that
checks the Arcaea China APK feed, optionally downloads APKs safely, and exposes
an experimental NapCat QQ Flash Transfer diagnostic path.

The current release target is `v0.2.3`. APK extraction is explicitly out of
scope. Flash Transfer and future extraction are independent consumers of a
successful download.

The verified minimum NapCat release exposing both `create_flash_task` and
`send_flash_msg` is `v4.10.47`; live compatibility still requires the
admin-only small-file diagnostic on the deployment machine.

## Layout

- `main.py`: thin AstrBot lifecycle and command adapter.
- `arcaea_pull/core/`: API, state, notification, update, and download logic.
- `arcaea_pull/distribution/`: backend abstraction and NapCat implementation.
- `arcaea_pull/utils/`: filesystem and hashing helpers.
- `tests/`: runtime-independent unit tests; do not contact production services.
- `docs/`: architecture and Flash Transfer source-research notes.
- `dist/`: generated install archives only; never commit its contents.

## Invariants

- Keep `last_seen_version`, `last_notified_version`, and
  `last_downloaded_version` independent.
- Compare remote version strings for inequality only; do not impose semantic
  version ordering.
- Persist state atomically in AstrBot's `data/plugin_data` directory.
- Stream downloads to `*.apk.part`, validate them, then atomically rename.
- Do not apply a whole-request timeout to APK transfers. Bound connection time
  and idle time between chunks so active large downloads can finish.
- Never advance downloaded state after a failed download.
- `notify_targets` and `flash_transfer_targets` are separate allowlists.
- Never treat a normal QQ file message as successful QQ Flash Transfer.
- Never send an APK to a target outside `flash_transfer_targets`.
- Do not commit secrets, runtime state, APKs, partial downloads, or research
  checkouts.
- Keep project licensing consistently declared as `AGPL-3.0-or-later`; do not
  replace the canonical GNU AGPL v3 text embedded in `LICENSE`.
- Treat the plugin directory as an imported package: production code must use
  package-relative imports so loading `data.plugins.<plugin>.main` does not
  depend on the plugin directory itself being present in `sys.path`.
- The schedule interval is a positive whole number of minutes, anchored at
  local midnight, at most 24 hours, and merged with explicitly configured extra
  wall-clock times.

## Commands

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest
python scripts/build_release.py
```

Run Ruff and the complete pytest suite before committing. Tests must use mocks
or local fixtures and must not download the production APK or contact QQ.

## Release packaging

The install ZIP must have plugin files at its archive root and include
`main.py`, `metadata.yaml`, `_conf_schema.json`, runtime requirements, package
source, README, and LICENSE. Exclude tests, CI files, caches, repository data,
APKs, partial files, and runtime state. Re-open the ZIP and verify its required
members and SHA-256 after building. The test suite must also extract the ZIP
and import its `main.py` through an AstrBot-style dotted package path from a
clean working directory.

## Source verification snapshot

Flash Transfer compatibility is based on the official source revisions recorded
in `docs/flash-transfer-poc.md`. Re-check those sources before changing action
payloads or claiming compatibility with a newer NapCat/AstrBot release.
