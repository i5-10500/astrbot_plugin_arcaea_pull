# astrbot_plugin_arcaea_pull

AstrBot 的 Arcaea 本地资源获取与分发基础设施插件。当前版本 **v0.2.3**
负责检测 Arcaea 中国大陆版（C 版）APK 更新、按白名单通知、可靠下载最新版
APK，并提供 NapCat QQ 闪传的管理员诊断 PoC。

> 本阶段不包含 APK 解包或游戏资源解析。QQ 闪传仍是实验性能力，实际可用性取决于
> AstrBot、aiocqhttp、NapCat、QQ 客户端与账号环境。

## 功能

- 按时区以本地每天 `00:00` 为起点、按分钟间隔检查，
  并可合并额外固定检查时间。
- 使用独立 `notify_targets` 白名单发送版本变化通知。
- 可选 `auto_download`；管理员也可手动下载。
- APK 流式写入 `.apk.part`，仅限制连接及数据块空闲时间，不限制大文件总下载时长；
  校验大小、ZIP/APK 格式与 SHA-256 后原子改名。
- 持久化并分离记录已观察、已通知、已下载版本。
- NapCat `create_flash_task` + `send_flash_msg` 闪传 PoC；仅允许当前
  `flash_transfer_targets` 白名单群，且绝不回退为普通群文件。
- 定时与手动操作共享互斥锁，避免重复通知和重复下载。

## 安装

在 AstrBot WebUI 的插件管理页上传
`astrbot_plugin_arcaea_pull-v0.2.3.zip`，或在 GitHub 仓库可访问后使用仓库 URL
安装：

```text
https://github.com/i5-10500/astrbot_plugin_arcaea_pull
```

运行时数据写入 AstrBot 的：

```text
data/plugin_data/astrbot_plugin_arcaea_pull/
```

其中 `state.json` 保存状态，`downloads/` 保存 APK。运行时数据不会写进插件源码目录。

## 配置

配置由 `_conf_schema.json` 提供给 AstrBot WebUI。常用选项：

- `check_enabled`、`timezone`：定时检查开关和 IANA 时区。
- `check_interval_minutes`：检查间隔（分钟），默认 `30`，只允许 `1`–`1440` 的整数。
- `extra_check_times`：额外检查时间列表，支持 `HH:MM` 和 `HH:MM:SS`。
- `notify_targets`：AstrBot 统一会话标识（UMO）列表，仅用于通知。
- `auto_download`：发现版本变化后自动下载，默认关闭。
- `flash_transfer_targets`：QQ 群号列表，仅用于闪传。
- `request_timeout`：元数据请求总超时；`retry_count`：HTTP 最大尝试次数。
- `download_connect_timeout`、`download_read_timeout`：下载连接超时和数据块间空闲超时；
  APK 下载没有整体总超时。
- `auto_flash_transfer`：v0.2.3 仅预留，当前不会自动分发 APK。

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
/apull flash_test
```

`flash_test` 必须在 aiocqhttp 的当前群聊中运行，当前群号也必须在
`flash_transfer_targets`。它只发送插件生成的小型无敏感文本文件，不发送 APK。

NapCatQQ 首次在 **v4.10.47** 发布 `create_flash_task` 与 `send_flash_msg` 扩展
action；建议使用 v4.10.47 或更新版本，并务必在目标机器执行实测。详见
[Flash Transfer PoC 记录](docs/flash-transfer-poc.md)。
已记录一组 Windows 10 + AstrBot v4.27.4 + NapCat v4.18.9 + QQ
9.9.26-44498 的完整实机通过结果，但新部署环境仍应独立执行 `flash_test`。

## 常见问题

- 元数据请求失败：检查到 `webapi.lowiro.com` 的 HTTPS 网络、超时与代理设置。
- 大型 APK 下载超时：v0.2.3 已取消整体总超时；如果长时间收不到新数据，
  调大 `download_read_timeout`。源站不支持断点续传时，失败重试仍会从头下载。
- 下载留下 `.part`：失败路径会自动清理；检查磁盘空间和目录权限后重试。
- 提示 action 不存在：升级 NapCat，确认 AstrBot 使用 aiocqhttp/OneBot v11 连接。
- 闪传群被拒绝：把当前纯 QQ 群号显式加入 `flash_transfer_targets`。
- 安装 v0.2.1 时出现 `No module named 'arcaea_pull'`：该版本的包内导入路径有误，请升级到 v0.2.2 或更新版本。
- `flash_test` 成功但未自动发 APK：这是 v0.2.3 的设计；自动分发属于后续版本。

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

