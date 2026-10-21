# Architecture

The plugin keeps AstrBot-specific code in `main.py` and all testable behavior in
the `arcaea_pull` package.

```text
ArcaeaApiClient -> UpdateChecker -> Notifier
                         |
                         +-------> Downloader -> pending APK
                                                |
                                                +-> AuthenticityVerifier
                                                        |
                                                        +-> verified APK
                                                                |          |
                                                                |          +-> future Extractor
                                                                +------------> DistributionService
                                                                  |
                                        Context.platform_manager -> BackendProvider
                                                                  |
                                                                  +-> NapCat backend
```

`UpdateChecker` serializes scheduled and manual checks with one `asyncio.Lock`.
It records a successfully parsed observation before invoking later consumers.
Notification and download state advance only after their respective operations
succeed, so a later failure never rolls back an earlier successful stage.

Downloads are streamed into a same-directory `.apk.part` file. Content length,
minimum size, ZIP signature, ZIP readability, and SHA-256 are checked before an
atomic `os.replace` publishes the final `arcaea_<version>.apk`.

Metadata requests retain a short whole-request deadline. APK transfers instead
use connection and socket-read inactivity deadlines with no whole-transfer
deadline, so a continuously progressing multi-gigabyte download is not aborted
because of its total duration.

The scheduler uses a positive whole-minute interval anchored at local midnight.
Extra `HH:MM`/`HH:MM:SS` wall times are merged into that schedule; coincident
triggers result in one pipeline run because the next trigger is always calculated
strictly after the current time.

Runtime state lives in AstrBot's `data/plugin_data/astrbot_plugin_arcaea_pull`
directory. Its schema version is explicit and writes use a temporary file plus
atomic replacement. Invalid JSON is quarantined with a timestamp before a clean
state is created.

Schema v2 migrates v1 state in place and adds per-version, per-target distribution
records. A successful record is reused only when its APK SHA-256 also matches;
failed or pending records remain eligible for a later retry. Removed allowlist
targets are not processed, while newly added targets have independent state.

Schema v3 adds verification state without changing distribution successes.
`apksigner` must cryptographically accept a v2-or-newer whole-file signature and
emit parseable signer certificate SHA-256 values. Build Tools `aapt2` then reads
the binary manifest through independent `badging` and `xmltree` views, cross-checks
their identity fields, and combines `versionCodeMajor` with the base version code.
The verifier pins every current signer, requires exact configured package and API
versionName equality, and rejects versionCode rollback. It recomputes file SHA-256
after the tools finish before publishing a `VerifiedArtifact`.

Runtime files use `downloads/pending`, `downloads/verified`, and
`downloads/quarantine`. Legacy root-level downloads are preserved and require a
fresh full verification. Distribution checks the verified path and SHA-256 again;
old distribution success state cannot promote or authorize an unverified file.

Managed APK retention keeps the current APK plus `old_versions_to_keep` archives
(0–20, default 1). Disabling `keep_old_versions` keeps only the current APK.
The downloader applies retention to pending files after successful download or
reuse. The verifier independently prunes verified files after a successful
verification or trusted cache reuse. Startup also applies the policy after
revalidating the last trusted artifact, even when scheduled checks are disabled.
Verified archive order uses recorded verification timestamps, falling back to
file modification times for unrecorded files; version strings stay opaque.
Only direct `arcaea_*.apk` files are candidates. Symlinks and Windows reparse
points, legacy root downloads, quarantine evidence, and partial files are
excluded. File deletion errors are logged and retried on later runs. Removed
artifact records are pruned while rollback high-water marks and distribution
history remain unchanged.

Notification and Flash Transfer allowlists deliberately use different identity
types: notifications store AstrBot UMO values, while the NapCat adapter consumes
QQ group IDs. The adapter boundary is the only layer that knows NapCat action
names and payload fields.

`BackendProvider` reads the active platform instances for each distribution round.
It selects only aiocqhttp, applies optional platform-ID and bot-self-ID selectors,
and fails closed on ambiguity. Bot self-IDs come from aiocqhttp's live reverse-
WebSocket connection map; AstrBot's `Platform.client_self_id` is only an internal
task UUID and must never be sent as a OneBot `self_id`. No message event or resolved
bot client is retained.

