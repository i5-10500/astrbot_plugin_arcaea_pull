# AGENTS.md

## Project

This repository contains `astrbot_plugin_arcaea_pull`, an AstrBot plugin that
checks the Arcaea China APK feed, optionally downloads APKs safely, and exposes
an idempotent NapCat QQ Flash Transfer distribution path.

The current release target is `v0.3.1`. APK extraction is explicitly out of
scope. Flash Transfer and future extraction are independent consumers of a
`VerifiedArtifact`, never of a merely successful download.

The verified minimum NapCat release exposing both `create_flash_task` and
`send_flash_msg` is `v4.10.47`; live compatibility still requires the
admin-only small-file diagnostic on the deployment machine.

## Layout

- `main.py`: thin AstrBot lifecycle and command adapter.
- `arcaea_pull/core/`: API, state, notification, update, and download logic.
- `arcaea_pull/distribution/`: backend abstraction and NapCat implementation.
- `arcaea_pull/verification/`: official Android tool adapters and authenticity gate.
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
- Resolve the active aiocqhttp client from `Context.platform_manager` for every
  distribution round; never cache a message event or adapter client.
- Fail closed when multiple aiocqhttp platforms remain after configured
  platform-ID/self-ID selectors are applied.
- Distribution identity is version + target + APK SHA-256. Skip a matching
  success, retry failures, and treat newly allowlisted targets independently.
- `auto_flash_transfer` requires `auto_download`; never hide a download inside
  `/apull distribute` or an invalid automatic configuration.
- Distribution accepts `VerifiedArtifact` only. Never pass `DownloadRecord`
  directly or add an unverified bypass configuration.
- Verify cryptographic signatures with official `apksigner`; parsing a signer
  certificate without successful signature verification is insufficient.
- Read package/version identity through official `apkanalyzer`, never ZIP grep.
- Trust only configured signer certificate SHA-256 values and exact package
  identity obtained by the user from a known-good APK. Never bootstrap trust
  from a newly downloaded file or network search.
- Missing tools/trust, malformed output, signature/signer/package/version
  mismatch, file mutation, and versionCode rollback all fail closed.
- Preserve legacy downloaded APKs but never migrate them directly to VERIFIED.
- Reuse a verified artifact only after its verified-directory path, size,
  SHA-256, package, and current trusted signer set still match.
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
