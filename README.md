# astrbot_plugin_arcaea_pull

AstrBot 的 Arcaea 本地资源获取与分发基础设施插件。当前版本 **v0.3.2**
负责检测 Arcaea 中国大陆版（C 版）APK 更新、按白名单通知、可靠下载最新版
APK，并通过 NapCat QQ 闪传向显式白名单群可靠分发。

> 本阶段不包含 APK 解包或游戏资源解析。QQ 闪传仍是实验性能力，实际可用性取决于
> AstrBot、aiocqhttp、NapCat、QQ 客户端与账号环境。

> v0.3.2 默认 fail closed：必须由用户从自己持有、已人工确认来源的 C 版 APK
> 建立 signer 和 package 信任根。默认信任列表为空，因此初次安装会显示
> `SECURITY_HOLD: TRUST_NOT_CONFIGURED`，不会自动分发任何 APK。

## 功能

- 按时区以本地每天 `00:00` 为起点、按分钟间隔检查，
  并可合并额外固定检查时间。
- 使用独立 `notify_targets` 白名单发送版本变化通知。
- 可选 `auto_download`；管理员也可手动下载。
- APK 流式写入 `.apk.part`，仅限制连接及数据块空闲时间，不限制大文件总下载时长；
  校验大小、ZIP/APK 格式与 SHA-256 后原子改名。
- 使用 Android 官方 Build Tools 的 `apksigner` 做密码学签名验证并固定 signer
  证书 SHA-256；使用同一组件中的 `aapt2` 交叉读取 package、versionName 和完整
  versionCode（含 versionCodeMajor）。
- package/version 必须精确匹配，versionCode 低于最后可信记录时进入安全冻结；
  只有 `downloads/verified/` 内路径和 SHA-256 均匹配的 `VerifiedArtifact` 能分发。
- 持久化并分离记录已观察、已通知、已下载版本。
- NapCat `create_flash_task` + `send_flash_msg` 自动闪传；按版本和目标记录结果，
  成功不重发、失败会重试，且绝不回退为普通群文件。
- 从 AstrBot 活动平台管理器逐轮解析 aiocqhttp 客户端；多实例必须通过平台 ID
  或机器人 QQ 号消歧，避免使用重载前的陈旧客户端。
- 定时与手动操作共享互斥锁，避免重复通知和重复下载。

## 安装

在 AstrBot WebUI 的插件管理页上传
`astrbot_plugin_arcaea_pull-v0.3.2.zip`，或在 GitHub 仓库可访问后使用仓库 URL
安装：

```text
https://github.com/i5-10500/astrbot_plugin_arcaea_pull
```

运行时数据写入 AstrBot 的：

```text
data/plugin_data/astrbot_plugin_arcaea_pull/
```

其中 `state.json` 保存状态，`downloads/pending`、`verified`、`quarantine` 分隔
未验证、可信和冻结 APK。v0.3.0 旧 APK 不会被自动视为 VERIFIED，也不会被删除。

### Android 工具前置条件与信任初始化

只需安装 Android SDK Build Tools **26.0.2 或更新版本**；同一个组件同时提供
`apksigner` 和 `aapt2`，无需再安装 Command-Line Tools。可把工具加入 PATH、配置
`ANDROID_HOME` / `ANDROID_SDK_ROOT`，或在插件配置中显式填写两个工具路径。
以本轮实测的 Windows Build Tools 36 为例，官方压缩包下载量约 59 MiB，完整解压
约占 137 MiB；`apksigner` 还需要主机具备 Java 运行环境。插件不捆绑或下载这些
官方工具。

只对你已经人工确认来源、曾实际安装或使用过的 C 版 APK 执行：

```powershell
python scripts/inspect_trusted_apk.py "D:\path\known-good-arcaea.apk"
```

确认输出 `Cryptographic signature: VALID` 后，把 signer 指纹填入
`trusted_signer_sha256`，把 package 精确填入 `trusted_package_name`。该脚本只读
APK，不会自动修改信任配置；绝不能用刚从网络下载的 APK 自动建立信任。

## 配置

配置由 `_conf_schema.json` 提供给 AstrBot WebUI。常用选项：

- `check_enabled`、`timezone`：定时检查开关和 IANA 时区。
- `check_interval_minutes`：检查间隔（分钟），默认 `30`，只允许 `1`–`1440` 的整数。
- `extra_check_times`：额外检查时间列表，支持 `HH:MM` 和 `HH:MM:SS`。
- `notify_targets`：AstrBot 统一会话标识（UMO）列表，仅用于通知。
- `auto_download`：自动确保当前远端版本已下载；下载失败会在后续检查重试。
- `flash_transfer_targets`：QQ 群号列表，仅用于闪传。
- `request_timeout`：元数据请求总超时；`retry_count`：HTTP 最大尝试次数。
- `download_connect_timeout`、`download_read_timeout`：下载连接超时和数据块间空闲超时；
  APK 下载没有整体总超时。
- `auto_flash_transfer`：自动分发当前已下载 APK，必须同时启用 `auto_download`。
- `flash_transfer_platform_id`、`flash_transfer_self_id`：多 aiocqhttp 实例时用于
  选择唯一发送端；单实例保持空值。
- `notify_on_distribution_success`、`notify_on_distribution_failure`：分发摘要通知。
- `verification_enabled`：真实性安全门，默认启用；关闭时所有 APK 分发被拒绝。
- `apksigner_path`、`aapt2_path`：Android 官方 Build Tools 路径，留空时自动发现。
- `trusted_signer_sha256`：允许的 signer 证书 SHA-256 列表；默认空且不自动扩充。
- `trusted_package_name`：已人工确认 APK 的精确 package name；默认空。
- `notify_on_verification_failure`：相同“版本 × 文件 SHA-256 × verdict”只通知一次。

不要把 `notify_targets` 和 `flash_transfer_targets` 当成同一白名单；二者的标识
类型和权限意义不同。

例如，如需从每天 `00:00` 起每 15 分钟检查，并在 `04:05:30` 加查一次：

```text
check_interval_minutes = 15
extra_check_times = ["04:05:30"]
```

## 管理员命令

```text
/apull status
/apull check
/apull download
/apull verify
/apull distribute
/apull flash_test
```

`flash_test` 必须在 aiocqhttp 的当前群聊中运行，当前群号也必须在
`flash_transfer_targets`。它只发送插件生成的小型无敏感文本文件，不发送 APK。
`verify` 验证当前已下载 APK，不会隐式下载。`distribute` 只处理当前远端版本的
VERIFIED APK，不会隐式下载或绕过验证；已经成功的
“版本 × 群号 × SHA-256”组合会跳过。

NapCatQQ 首次在 **v4.10.47** 发布 `create_flash_task` 与 `send_flash_msg` 扩展
action；建议使用 v4.10.47 或更新版本，并务必在目标机器执行实测。详见
[Flash Transfer PoC 记录](docs/flash-transfer-poc.md)。
已记录一组 Windows 10 + AstrBot v4.27.4 + NapCat v4.18.9 + QQ
9.9.26-44498 的完整实机通过结果，但新部署环境仍应独立执行 `flash_test`。

## 常见问题

- 元数据请求失败：检查到 `webapi.lowiro.com` 的 HTTPS 网络、超时与代理设置。
- 大型 APK 下载超时：已取消整体总超时；如果长时间收不到新数据，
  调大 `download_read_timeout`。源站不支持断点续传时，失败重试仍会从头下载。
- 下载留下 `.part`：失败路径会自动清理；检查磁盘空间和目录权限后重试。
- 提示 action 不存在：升级 NapCat，确认 AstrBot 使用 aiocqhttp/OneBot v11 连接。
- 闪传群被拒绝：把当前纯 QQ 群号显式加入 `flash_transfer_targets`。
- 安装 v0.2.1 时出现 `No module named 'arcaea_pull'`：该版本的包内导入路径有误，请升级到 v0.2.2 或更新版本。
- 状态显示 `AUTO_FLASH_MISCONFIGURED`：启用了 `auto_flash_transfer`，但没有同时
  启用 `auto_download`；插件会拒绝隐式下载和自动分发。
- 状态显示多个 aiocqhttp 实例：配置 `flash_transfer_platform_id` 或
  `flash_transfer_self_id`，直到只匹配一个活动实例。
- 状态显示 `TRUST_NOT_CONFIGURED`：按上面的 known-good APK 流程建立 signer 和
  package 信任根；不要从当前网络下载物自动填充。
- 状态显示 `VERIFIER_UNAVAILABLE`：安装 Android SDK 工具或填写正确路径。
- 状态显示 `CONFIG_SECURITY_ERROR`：自动分发需要同时启用下载和真实性验证。

完整威胁模型、恢复步骤和 key rotation 规则见
[APK Authenticity](docs/apk-authenticity.md)。

## 开发与测试

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m pytest
.venv\Scripts\python scripts/build_release.py
```

测试不连接真实 QQ、不依赖真实 AstrBot runtime，也不会下载生产 APK。

## 数据源与许可

APK 元数据来自 lowiro 的公开 C 版接口：
`https://webapi.lowiro.com/webapi/serve/static/bin/arcaea/apk`。本项目与 lowiro、
Arcaea、QQ、NapCat 或 OpenAI 均无官方隶属关系。代码采用
[GNU Affero General Public License v3.0 or later](LICENSE)（`AGPL-3.0-or-later`）。

## 开发声明

Developed primarily with OpenAI Codex CLI under user direction.

本项目主要由 OpenAI Codex CLI 在用户指导下开发。

