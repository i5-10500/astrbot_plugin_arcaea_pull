# QQ Flash Transfer PoC

Status: **SUPPORTED ON THE RECORDED LIVE ENVIRONMENT; VERIFY EACH NEW DEPLOYMENT**

## Live validation

A user-provided checklist completed on 2026-08-26 reports an end-to-end pass on
Windows 10 with AstrBot v4.27.4, NapCat core v4.18.9, and QQ 9.9.26-44498.
NapCat returned success for both actions, produced a valid `fileSetId`, and the
test group displayed a real QQ Flash Transfer card containing only the generated
`flash-transfer-probe.txt`. Non-allowlisted groups and private chats were rejected
before an action call. No ordinary group-file fallback occurred.

This result establishes support for that exact environment, not every account,
QQ build, or deployment. The source checklist retained an older v0.2.1 artifact
label, so it is environment-level Flash Transfer evidence rather than a claim
that the known-broken v0.2.1 installation archive is valid.

## Source snapshot

Research was performed on 2026-08-26 against:

- AstrBot commit `2ffdb9a1fa27e590dd3cae4b3e550015f0f1d60a`.
- NapCatQQ commit `af07479351c5b974e72ae1c7183f2272e79ffc1c`.
- NapCatQQ introduction commit `b0114206fc2da81a2e7a077923850be9ddeb6b94`
  from PR #1541.

Official source links:

- [NapCat Flash action registration](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/action/router.ts)
- [`create_flash_task` implementation](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/action/file/flash/CreateFlashTask.ts)
- [`send_flash_msg` implementation](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/action/file/flash/SendFlashMsg.ts)
- [NapCat core Flash API](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-core/apis/flash.ts)
- [AstrBot aiocqhttp event implementation](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/platform/sources/aiocqhttp/aiocqhttp_message_event.py)

## Version boundary

Direct inspection of adjacent release trees shows that
`packages/napcat-onebot/action/file/flash/SendFlashMsg.ts` is absent from
`v4.10.46` and present in `v4.10.47`. Therefore **NapCat v4.10.47 is the minimum
known release with the public send path**. NapCat v4.8.115 introduced Stream API,
which solves a different transport problem and must not be confused with QQ
Flash Transfer creation/sending.

## Capability

NapCat exposes two required OneBot v11 extension actions:

1. `create_flash_task` accepts `files`, optional `name`, and optional
   `thumb_path`; its result contains `createFlashTransferResult.fileSetId`.
2. `send_flash_msg` accepts `fileset_id` and either `group_id` or `user_id`.

AstrBot's current aiocqhttp event exposes its `CQHttp` client as `event.bot`, and
the client supports arbitrary extension calls via `bot.call_action`. The plugin
therefore binds the backend only during `/apull flash_test`, after confirming the
event is a group conversation and its QQ group ID is allowlisted.

Receiving a `flashtransfer` message segment is also represented by NapCat, but
receiving support alone is not used as evidence for active sending.

## Safety and remaining validation

- `flash_transfer_targets` is separate from `notify_targets`.
- The PoC sends only a small generated text probe to the current allowlisted
  group. It does not send the APK.
- No ordinary group-file fallback exists.
- Missing actions, rejected uploads, malformed results, and failed sends are
  surfaced as typed errors.
- The repository can prove request construction with mocks, but it cannot prove
  compatibility with a user's QQ build, account policy, NapCat configuration,
  or live network. Run the admin-only command on the target machine.

## Validation for each new environment

Install the generated ZIP on the real AstrBot + aiocqhttp + NapCat machine,
ensure NapCat is at least v4.10.47, add only the test group ID to
`flash_transfer_targets`, and run `/apull flash_test`. Record both action results
and the NapCat log before relying on Flash Transfer or enabling any future
automatic APK distribution.

