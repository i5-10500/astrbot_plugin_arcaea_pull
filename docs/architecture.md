# Architecture

The plugin keeps AstrBot-specific code in `main.py` and all testable behavior in
the `arcaea_pull` package.

```text
ArcaeaApiClient -> UpdateChecker -> Notifier
                         |
                         +-------> Downloader -> downloaded APK
                                                |          |
                                                |          +-> future Extractor
                                                +------------> FlashTransferBackend
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

Notification and Flash Transfer allowlists deliberately use different identity
types: notifications store AstrBot UMO values, while the NapCat adapter consumes
QQ group IDs. The adapter boundary is the only layer that knows NapCat action
names and payload fields.

