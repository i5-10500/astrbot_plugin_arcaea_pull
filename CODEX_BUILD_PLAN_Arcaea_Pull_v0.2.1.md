# Codex CLI 构建方案：AstrBot Arcaea Pull（阶段一）

> 本文档用于直接交给 Codex CLI 执行。
>
> 项目目标：为 AstrBot 构建一个面向 Arcaea 音游群的基础设施插件。本阶段实现 **C 版更新检测、APK 自动拉取、QQ 闪传发送能力 PoC**，暂不实现 APK 解包。
>
> 开发声明要求：GitHub 仓库 README 中必须明确注明 **“本项目主要由 OpenAI Codex CLI 在用户指导下开发（Developed primarily with OpenAI Codex CLI under user direction）”**。  
> 不要把 `Codex` 或 `OpenAI` 填成 `metadata.yaml` 的项目作者；插件作者应使用实际 GitHub 仓库所有者/用户指定的作者信息。

---

## 0. 你的角色与执行权限

你是本项目的主要实现者。请自行完成需求分析、代码实现、测试、Git/GitHub 工作流和最终打包。

你被明确授权在本项目仓库范围内执行：

- 创建和修改源代码、测试、配置、README、CI 文件。
- 初始化 Git 仓库。
- 如果当前目录尚未绑定远端仓库，使用当前已登录的 GitHub/`gh` 身份创建对应 GitHub 仓库并推送；本项目按开源项目处理，默认创建为 public。
- 创建开发分支。
- commit / push。
- 创建、更新、关闭本项目 PR。
- 根据 review / CI 结果继续修改并 push。
- 在所有规定测试通过后自行 Merge PR。
- Merge 后同步本地 `main`/默认分支。
- 创建 Git tag / GitHub Release（如阶段流程需要）。
- 在最终通过本机测试后生成 AstrBot 可安装 ZIP。

以上授权仅限本项目仓库。

### 禁止事项

不得：

- 向仓库提交任何 GitHub Token、QQ 凭据、AstrBot 密钥、Cookie、密码或其他 secret。
- 绕过 GitHub branch protection / required checks。
- 使用 `--force` / `--force-with-lease` 覆盖公共分支历史，除非仅处理你自己刚建立且尚未共享的临时分支，并且确有必要。
- 删除与本任务无关的用户文件或其他仓库。
- 擅自修改用户 GitHub 账号级设置。
- 为了“让测试通过”而删除、跳过或弱化关键测试。
- 伪造 QQ 闪传已经可用。如果当前 NapCat/OneBot 实现不能主动发送闪传，必须明确记录真实结论。

若 GitHub 身份未登录、权限不足、网络被阻断等导致某一步无法完成，应继续完成本地所有可完成工作，并在最终报告中明确列出阻塞项；不要因此停止代码实现和测试。

---

# 1. 项目定位

推荐插件名：

```text
astrbot_plugin_arcaea_pull
```

定位：

> AstrBot 的 Arcaea 本地资源获取与分发基础设施插件。当前阶段负责监测 Arcaea 中国大陆版（C 版）APK 更新、可靠下载最新版 APK，并验证/实现通过 QQ 闪传向指定白名单群发送 APK 的能力。后续版本将在本地 APK 基础上加入解包和资源解析。

本阶段必须保持模块化，后续流程预期为：

```text
UpdateChecker
      │
      ├──> Notifier
      │
      └──> Downloader
               │
               ├──> FlashTransferDistributor
               │
               └──> [未来] Extractor
                            │
                            └──> ResourcePipeline
```

**QQ 分发与未来 APK 解包必须是下载成功后的两个独立消费者，不要让“闪传成功”成为未来“允许解包”的前置条件。**

---

# 2. 本阶段版本范围

本轮开发最终交付版本为：

```text
v0.2.1
```

但实现过程中按以下里程碑组织代码和 Git 历史。

## v0.1.0 — 更新检测与通知

实现：

- 每天定时检查 Arcaea C 版 APK 信息。
- 默认数据源：

```text
https://webapi.lowiro.com/webapi/serve/static/bin/arcaea/apk
```

- 从响应中解析至少：
  - `success`
  - `value.version`
  - `value.url`
- 数据源访问与解析必须封装，不允许散落在业务代码中。
- `remote_version != last_seen_version` 时认为检测到版本变化。
- 不要求自行进行语义版本排序。
- 记录最后观察到版本。
- 对配置的通知白名单会话主动发送更新通知。
- 提供管理员手动检查命令。
- HTTP 请求使用 AstrBot 推荐的异步库，如 `aiohttp` 或 `httpx`；不要使用同步 `requests` 阻塞事件循环。
- 带 timeout、有限重试和结构化错误处理。

## v0.2.0 — 可靠 APK 下载

实现：

- 可配置 `auto_download`，默认关闭。
- 检测到新版本时，若开启则自动拉取 APK。
- 支持管理员手动触发下载。
- 下载过程先写：

```text
*.apk.part
```

- 完整下载并通过基础检查后再原子 rename 为：

```text
arcaea_<version>.apk
```

- 至少记录：
  - version
  - source_url
  - filename/path
  - file size
  - SHA-256
  - downloaded_at
  - success/failure
- 下载失败不得更新 `last_downloaded_version`。
- 防止重复下载同一已成功版本。
- 对网络超时、403/4xx、5xx、不完整文件、磁盘异常分别留有可诊断日志。
- 不在 test 中真实下载完整生产 APK；使用 mock/local HTTP fixture。

## v0.2.1 — QQ 闪传发送 PoC

**这是本轮最重要的实机验证项。**

目标：

> 确认 AstrBot + aiocqhttp/OneBot v11 + NapCat 当前环境中，机器人是否存在可可靠调用的“主动创建 QQ 闪传”能力，并为后续 v0.3.0 自动分发做好稳定接口。

要求：

1. 首先检查当前 AstrBot 官方文档、当前 NapCat 文档和 NapCat 最新公开源码。
2. 不要根据旧博客或旧实现直接假定接口存在。
3. 优先级：
   1. NapCat 当前公开且稳定的闪传发送 API / OneBot 扩展 action；
   2. NapCat 已有可从 AstrBot 安全调用的内部/扩展接口；
   3. 若以上均不存在，分析最小 NapCat 侧扩展方案，但本轮不要为了完成指标而硬编码 QQ 私有协议。
4. 若可直接发送：
   - 实现独立 `FlashTransferBackend` / adapter。
   - 上层业务代码不得依赖 NapCat 具体 action 字段。
   - 实现仅允许向 `flash_transfer_targets` 白名单中的群发送。
   - 实现管理员手动 PoC/诊断命令。
5. 若当前公开接口不能主动发送 QQ 闪传：
   - **不得伪装成成功实现。**
   - 保留清晰的 `FlashTransferBackend` 抽象接口、异常类型和 mock 测试。
   - 写 `docs/flash-transfer-poc.md`，记录：
     - 检查的 AstrBot/NapCat 版本或 commit；
     - 找到的相关 API/源码；
     - 接收闪传和主动发送闪传分别支持到什么程度；
     - 当前阻塞点；
     - 下一步最小实现路径。
   - 手动命令应返回“当前后端不可用/未实现”的明确诊断，而不是 silently fallback 为普通群文件。
6. **QQ 普通文件发送不是 QQ 闪传。未经用户明确批准，不允许把普通群文件发送当作完成 v0.2.1 的替代方案。**

---

# 3. 当前已知技术背景

开始编码前请自行重新核验，不要只依赖以下信息。

截至 2026-08：

- AstrBot 官方插件规范推荐插件名以 `astrbot_plugin_` 开头。
- `metadata.yaml` 是插件识别所需元数据。
- 少量用户配置适合 `_conf_schema.json`。
- 插件持久化数据应放在 AstrBot `data` 体系内，避免插件升级/重装覆盖数据。
- AstrBot 官方建议异步 HTTP 请求，并建议提交前使用 Ruff。
- AstrBot WebUI 支持从 URL 或本地文件上传方式安装插件。
- NapCat 公开代码中已有 Stream API/文件流上传相关实现。
- NapCat 代码已经能够识别 `flashtransfer` 类消息，但“主动发送 QQ 闪传”是否已形成公开、稳定、可从 OneBot 调用的发送接口必须由你在开发时重新验证。

任何与当前源码不一致的旧结论，以**当前官方文档 + 当前源码**为准。

---

# 4. 功能架构

建议结构：

```text
astrbot_plugin_arcaea_pull/
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── requirements.txt
├── README.md
├── LICENSE
├── pyproject.toml
│
├── arcaea_pull/
│   ├── __init__.py
│   ├── models.py
│   │
│   ├── core/
│   │   ├── api_client.py
│   │   ├── update_checker.py
│   │   ├── downloader.py
│   │   ├── notifier.py
│   │   └── state_manager.py
│   │
│   ├── distribution/
│   │   ├── base.py
│   │   └── napcat_flash_transfer.py
│   │
│   └── utils/
│       ├── filesystem.py
│       └── hashing.py
│
├── tests/
│   ├── test_api_client.py
│   ├── test_update_checker.py
│   ├── test_downloader.py
│   ├── test_state_manager.py
│   ├── test_whitelist.py
│   └── test_flash_transfer_backend.py
│
├── docs/
│   ├── architecture.md
│   └── flash-transfer-poc.md
│
└── .github/
    └── workflows/
        └── test.yml
```

允许根据 AstrBot 当前模板调整，但必须保证“业务逻辑”和 AstrBot event handler 不全部堆在 `main.py`。

---

# 5. 状态模型

不要只存一个 `current_version`。

至少独立记录：

```text
last_seen_version
last_notified_version
last_downloaded_version
```

并为未来预留：

```text
distribution_status
last_extracted_version
```

推荐状态结构示例：

```json
{
  "schema_version": 1,
  "remote": {
    "version": "6.x.xc",
    "url": "..."
  },
  "observed": {
    "version": "6.x.xc",
    "observed_at": "..."
  },
  "notification": {
    "last_notified_version": "6.x.xc"
  },
  "download": {
    "last_downloaded_version": "6.x.xc",
    "path": "...",
    "size": 0,
    "sha256": "...",
    "downloaded_at": "..."
  },
  "distribution": {}
}
```

### 写状态原则

- API 成功解析后，才允许更新 observed。
- 通知实际成功后，再更新相应通知状态。
- APK 下载、检查和最终 rename 全部成功后，才更新 downloaded。
- 任意后续步骤失败不得回滚已成功的前序状态。
- 状态文件写入应避免半写入，优先临时文件 + 原子替换。
- 为状态结构保留 `schema_version`，方便后续 migration。

---

# 6. 白名单与权限

至少分成：

```text
notify_targets
flash_transfer_targets
```

不能合并为同一个概念。

### `notify_targets`

允许收到：

- 发现新版本
- 下载成功/失败（按配置）
- 后续运行状态通知

### `flash_transfer_targets`

允许实际接收 APK 闪传。

要求：

- 闪传目标必须显式配置。
- 未在 `flash_transfer_targets` 中的群绝不能收到 APK。
- 普通聊天用户不得通过命令让机器人向任意 QQ 群发送文件。
- 手动闪传测试命令必须做管理员权限检查。
- 不要依赖 LLM 判断权限。
- 如 AstrBot 提供统一会话标识（UMO），优先保存/使用框架提供的稳定标识；若 NapCat 扩展 action 最终必须使用纯 QQ group_id，应在 adapter 层完成 UMO → 平台目标的转换/验证，不要污染核心业务模型。

---

# 7. 推荐配置

使用 `_conf_schema.json`，至少覆盖：

```text
check_enabled              = true
check_time                 = "04:00"
timezone                   = "Asia/Shanghai"

notify_targets             = []
notify_on_update            = true
notify_on_download_success = true
notify_on_error             = false

auto_download              = false

auto_flash_transfer        = false
flash_transfer_targets     = []

request_timeout            = 30
retry_count                = 3

keep_old_versions          = true
```

本轮即使 `auto_flash_transfer` 尚未正式用于生产，也可提前保留配置项；必须明确标注 v0.2.1 仍属于 PoC。

数据下载目录和状态目录应使用 AstrBot 推荐的数据目录策略，不把运行时数据写入插件源码目录。

---

# 8. 定时任务与生命周期

要求：

- 使用 AstrBot 当前推荐的插件生命周期方式初始化后台任务。
- 插件加载后启动每日检查调度。
- 插件 terminate/unload 时正确取消任务。
- 不产生 zombie task。
- AstrBot 启动时不要无条件立即下载 APK。
- 时间调度应尊重配置 timezone。
- 每天执行一次即可，不进行高频轮询。
- 同一时刻只能存在一个更新检查/下载 pipeline，使用 asyncio lock 或等价方案防止：
  - 定时任务正在检查；
  - 管理员同时手动执行；
  - 导致重复下载/重复通知。

---

# 9. 管理命令

根据 AstrBot 当前 command API 实现合适的管理员命令。

建议至少提供等价功能：

```text
/apull status
/apull check
/apull download
/apull flash_test
```

具体命令语法可按 AstrBot 当前推荐方式调整。

### status

输出：

- 当前插件版本
- last_seen_version
- last_downloaded_version
- 自动检查开关
- 自动下载开关
- FlashTransfer backend 状态
- 不输出任何敏感配置

### check

立即运行一次更新检查。

### download

下载当前 API 返回的最新版 APK；若已经可靠存在则默认不重复下载，除非实现显式安全的 `force` 选项。

### flash_test

用于另一台实际 AstrBot/NapCat 机器上的 PoC。

要求：

- 仅管理员。
- 仅允许目标为 `flash_transfer_targets`。
- 如果当前 backend 不支持发送闪传，返回准确诊断。
- 如果支持，不要默认把一个完整 APK 发给所有白名单群。
- 最好允许对“当前会话且当前会话也在白名单中”执行单群测试。
- 若 API 必须使用本地文件，可使用插件自带/运行时生成的小型无敏感测试文件验证通道；真正 APK 发送留到后续确认。
- 不要把普通群文件冒充闪传测试成功。

---

# 10. HTTP 与下载安全

必须满足：

- 使用异步 HTTP。
- 设置 User-Agent。
- connect/read/overall timeout。
- 有界重试，例如最多 3 次。
- 指数退避或小幅 backoff。
- 只接受预期 HTTPS URL；如数据源返回异常 scheme，拒绝。
- 下载采用流式写入，不能一次把整个 APK 读进内存。
- 对 `.part` 文件进行清理/恢复策略。
- 下载完成后至少验证：
  - 文件非空；
  - 文件大小合理；
  - ZIP/APK 基本格式可打开或具有有效 ZIP 签名；
  - SHA-256 可计算。
- 不需要本轮进行 APK 签名真实性验证，但代码结构应允许未来添加 verifier。

---

# 11. 测试要求

**先写可测试架构，再实现功能。不得把网络、AstrBot runtime、NapCat 全部硬耦合导致无法单测。**

推荐：

```text
pytest
pytest-asyncio
ruff
```

如当前 AstrBot 项目生态推荐其他工具，可采用当前规范。

## 必须覆盖的测试

### API Client

- 正常响应。
- `success=false`。
- 缺少 `value`。
- 缺少 `version`。
- 缺少 `url`。
- 非 JSON。
- timeout。
- 4xx。
- 5xx。
- retry 成功。
- retry 最终失败。

### UpdateChecker

- 首次发现版本。
- 同版本再次检查不重复通知。
- 新版本触发通知。
- 通知失败不会错误标记为成功。
- 不做错误的语义版本排序假设。

### Downloader

- 下载成功。
- `.part` → 最终文件 rename。
- SHA-256 正确。
- 网络中断。
- HTTP 失败。
- 不完整下载。
- 非 APK/ZIP 基础格式。
- 已下载版本避免重复。
- 下载失败不更新状态。

### StateManager

- 首次创建。
- 正常读写。
- 原子写入。
- 无效 JSON 的可诊断恢复策略。
- schema version。
- 下载失败与观察状态相互独立。

### Whitelist

- notify 白名单允许。
- notify 白名单拒绝。
- flash 白名单允许。
- flash 白名单拒绝。
- 两者互不等价。

### FlashTransferBackend

- 通过 mock action 测试请求构造。
- 平台不支持时返回明确 typed error。
- action 失败能正确传播/转换。
- 不允许非白名单目标。
- 不把普通 file message fallback 视为 flash success。

### 并发

至少测试一次：

```text
scheduled check + manual check
```

不会产生重复下载/重复通知。

---

# 12. 测试分层

## Level A — 纯单元测试

要求：

- 无真实 QQ。
- 无真实 AstrBot。
- 无真实 lowiro APK 大文件下载。
- 可以 mock HTTP、filesystem、clock、NapCat adapter。

## Level B — 本地集成测试

如果开发环境允许：

- 加载 AstrBot 插件。
- 验证 metadata/config 能被解析。
- 验证插件初始化/terminate。
- 使用 mock/local HTTP endpoint。
- 不真实发送群消息。

## Level C — GitHub CI

创建 `.github/workflows/test.yml`。

至少：

- checkout
- 安装目标 Python 版本
- install dependencies
- Ruff check
- pytest
- 如采用类型检查，再运行类型检查

PR Merge 前 CI 必须通过。

## Level D — 用户异机实测

**不由 Codex 伪造。**

Codex 本地和 CI 完成后：

1. 生成安装 ZIP。
2. 用户将 ZIP 拿到另一台装有真实 AstrBot + QQ/NapCat 的机器。
3. 用户通过 AstrBot WebUI 本地上传安装。
4. 用户配置目标白名单群。
5. 用户实测：
   - 插件加载；
   - 手动 `status`；
   - 手动 `check`；
   - 小型文件 `flash_test`；
   - 若 PoC 成功，再决定后续 v0.3.0 自动 APK 闪传。

本轮交付不能把“用户尚未进行 Level D 实测”描述成“生产验证完成”。

---

# 13. Git / GitHub 工作流

推荐采用短生命周期 feature branch + PR。

建议里程碑：

```text
feat/v0.1-update-checker
feat/v0.2-downloader
feat/v0.2.1-flash-transfer-poc
```

可以根据现有仓库状态合并调整，但 Git 历史应清楚。

## 自动执行规则

每个阶段：

1. 从最新 `main` 创建分支。
2. 开发。
3. 运行本地测试。
4. Ruff/格式检查。
5. commit。
6. push。
7. 创建 PR。
8. 等待/读取 GitHub CI。
9. 若失败：
   - 定位失败；
   - 修改；
   - 本地重跑；
   - push；
   - 等待 CI。
10. 所有 required checks 通过后，Codex 被授权自行 Merge。
11. 优先使用 squash merge；若仓库既有约定不同，遵循仓库约定。
12. 更新本地 main。
13. 进入下一阶段。

如果 GitHub 仓库没有 branch protection，也仍然必须执行 PR + CI 流程，不要直接把未经测试代码 push 到 main。

---

# 14. README 要求

README 至少说明：

- 插件用途。
- 当前版本。
- 当前功能：
  - C 版更新检测；
  - 白名单通知；
  - 可选自动下载；
  - QQ 闪传 PoC 状态。
- 明确说明：
  - 本阶段不包含 APK 解包。
  - v0.2.1 的闪传属于实验性能力，具体可用性取决于当前 AstrBot/NapCat/QQ 环境。
- 安装方法：
  - AstrBot WebUI 本地 ZIP 安装；
  - GitHub URL 安装（若适用）。
- 配置方法。
- 管理命令。
- 数据目录。
- 常见错误。
- License。
- 上游/数据源说明。
- 开发声明：

```text
Developed primarily with OpenAI Codex CLI under user direction.
本项目主要由 OpenAI Codex CLI 在用户指导下开发。
```

不要声称这是 OpenAI 官方项目或由 OpenAI 官方维护。

---

# 15. metadata.yaml

遵循当前 AstrBot 官方规范。

至少保证：

- `name` 与插件目录/仓库身份一致。
- `author` 使用真实仓库作者，而不是 Codex/OpenAI。
- `version` 与发布版本一致。
- `repo` 指向实际 GitHub repo。
- `desc` 准确。
- `support_platforms` 根据实际能力填写；QQ/NapCat 方向通常对应 `aiocqhttp`，但开始前核验当前 AstrBot key。
- 如能够可靠确定最低 AstrBot 版本，填写 `astrbot_version`；否则不要瞎猜。

---

# 16. 打包规则

在最终 `v0.2.1` 的：

```text
local tests PASS
+
GitHub CI PASS
+
PR MERGED
```

之后，再生成测试安装包。

文件名建议：

```text
dist/astrbot_plugin_arcaea_pull-v0.2.1.zip
```

要求：

- 从 **merge 后的干净 main 工作树** 构建。
- 不把以下内容打入 ZIP：
  - `.git/`
  - `.github/`（安装包无需要时）
  - `.venv/`
  - `__pycache__/`
  - `.pytest_cache/`
  - `.ruff_cache/`
  - `tests/`（如果运行时不需要）
  - `dist/`
  - 本地 APK
  - `.part`
  - runtime state
  - secret
  - 开发日志
- ZIP 中必须包含：
  - `main.py`
  - `metadata.yaml`
  - `_conf_schema.json`
  - `requirements.txt`（若存在运行时第三方依赖）
  - Python package/source
  - README / LICENSE
- 在打包后重新打开 ZIP 检查文件列表。
- 可选：计算安装 ZIP 的 SHA-256，输出到：

```text
dist/SHA256SUMS.txt
```

- **不要把真实下载的 Arcaea APK 提交到 GitHub 仓库或打进插件 ZIP。**

---

# 17. 完成定义（Definition of Done）

本轮只能在以下条件同时满足时宣布完成：

## Repository

- [ ] GitHub 仓库存在并已同步。
- [ ] README 有 Codex CLI 开发声明。
- [ ] 没有 secret。
- [ ] `metadata.yaml` 正确。

## v0.1

- [ ] 能查询 C 版版本信息。
- [ ] 能正确识别版本变化。
- [ ] 有独立 notify 白名单。
- [ ] 支持定时检查。
- [ ] 支持手动检查。
- [ ] 状态可持久化。

## v0.2

- [ ] `auto_download` 可配置。
- [ ] 流式下载。
- [ ] `.part` 安全策略。
- [ ] SHA-256。
- [ ] 基础 APK 完整性检查。
- [ ] 不重复下载成功版本。
- [ ] 下载失败不污染状态。

## v0.2.1

满足以下二者之一即可认为 **PoC 阶段真实完成**：

### A. 当前 NapCat 支持主动 QQ 闪传

- [ ] 实现独立 backend。
- [ ] 单元测试完成。
- [ ] 有白名单。
- [ ] 有管理员 `flash_test`。
- [ ] 文档写清 API 与环境要求。
- [ ] 已生成待用户异机实测 ZIP。

### B. 当前 NapCat 不存在稳定主动发送接口

- [ ] 有源码/文档证据说明。
- [ ] 有 `FlashTransferBackend` 抽象。
- [ ] unsupported path 被测试。
- [ ] `flash_test` 给出明确诊断。
- [ ] `docs/flash-transfer-poc.md` 给出下一步最小方案。
- [ ] 没有用普通文件发送冒充闪传。
- [ ] 已生成待用户异机实测 ZIP。

## QA

- [ ] `pytest` 全部通过。
- [ ] Ruff/格式检查通过。
- [ ] GitHub CI 全部通过。
- [ ] PR 已完成并 Merge。
- [ ] main 工作树 clean。
- [ ] 最终 ZIP 来自 merge 后 main。
- [ ] ZIP 已检查可安装结构。
- [ ] 输出 ZIP SHA-256。

---

# 18. 最终交付

完成后向用户提供一份简洁报告，包括：

```text
Repository:
<GitHub repo>

Final version:
v0.2.1

Merged PRs:
#...

Tests:
pytest: PASS (... tests)
ruff: PASS
GitHub CI: PASS

FlashTransfer PoC:
SUPPORTED / BLOCKED / PARTIAL
简短说明真实结论

Install package:
dist/astrbot_plugin_arcaea_pull-v0.2.1.zip

SHA-256:
...

Manual test required:
是。需要在用户另一台真实 AstrBot + NapCat 机器上验证。
```

若 FlashTransfer 尚无公开发送能力，最终报告必须直接写 `BLOCKED` 或 `PARTIAL`，不要为了让项目显得完整而降低判定标准。

---

# 19. 后续版本（本轮不要实现）

当前代码结构需要为以下路线留出接口，但**不要提前实现**：

## v0.3.0

正式自动化：

```text
发现新版
  ↓
通知
  ↓
下载成功
  ↓
auto_flash_transfer?
  ↓
按 flash_transfer_targets 逐群闪传 APK
```

分发状态必须按“版本 + 群”分别记录：

```json
{
  "distribution": {
    "6.x.xc": {
      "group_A": "success",
      "group_B": "failed"
    }
  }
}
```

失败后只重试失败目标，避免群 A 重复收到 APK。

## v0.4.0

APK 文件级解包：

```text
下载完成
 ├──> QQ 闪传
 └──> APK Extractor
```

闪传失败不得阻断解包。

## v0.5+

围绕解包内容加入 ResourcePipeline：

- 游戏资源索引；
- 曲目数据；
- 谱面相关数据；
- 角色/图片资源；
- 剧情资源；
- 版本差异分析。

---

# 20. 执行要求

现在开始执行，不要只给设计建议。

顺序：

```text
检查当前目录 / Git 状态
        ↓
核验最新 AstrBot / NapCat 接口
        ↓
建立插件骨架
        ↓
实现 v0.1.0
        ↓
test → PR → CI → merge
        ↓
实现 v0.2.0
        ↓
test → PR → CI → merge
        ↓
研究并实现 v0.2.1 FlashTransfer PoC
        ↓
test → PR → CI → merge
        ↓
从 merge 后 main 构建 v0.2.1 ZIP
        ↓
校验 ZIP + SHA-256
        ↓
向用户报告仓库、PR、测试、PoC 结论和 ZIP 路径
```

遇到实现细节不确定时，优先阅读：

1. 当前 AstrBot 官方开发文档；
2. 当前 AstrBot 源码；
3. 当前 NapCat 官方文档；
4. 当前 NapCat 源码；
5. 对应 GitHub Issues / PR。

以当前代码事实为准，不要通过猜测补齐未公开 API。

