# APK Authenticity / 真实性安全门

v0.3.2 在下载和 QQ 闪传之间保留强制真实性验证。文件 SHA-256 只说明“当前文件
是否与已记录文件相同”，不能证明发行者身份；发行者身份来自完整 APK 密码学签名
验证和用户固定的 signer 证书 SHA-256。

## 官方工具依赖

- Android SDK Build Tools 的 `apksigner`：执行 `verify --verbose --print-certs`。
  只有退出码为 0、至少一个 v2 或更新的整包签名方案明确验证成功、且能完整解析
  signer SHA-256 时才接受；不因仅针对 v1/JAR 的 `META-INF` 警告误拒绝已有 v2
  保护的官方 APK。
- 同一 Build Tools 组件的 `aapt2`：同时执行 `dump badging` 和
  `dump xmltree ... --file AndroidManifest.xml`，严格解析并交叉核对 package、
  versionName、versionCode；从 xmltree 读取 versionCodeMajor 并合成长版本码。

官方参考：

- <https://developer.android.com/tools/apksigner>
- <https://developer.android.com/tools/aapt2>
- <https://developer.android.com/tools/releases/build-tools>

工具会按以下顺序发现：显式配置路径、PATH、`ANDROID_HOME` / `ANDROID_SDK_ROOT`
下的最新 Build Tools 组件。最低使用 Build Tools 26.0.2，且无需安装 Command-Line
Tools。插件不会捆绑 Android SDK。任一工具缺失、超时、返回非预期
输出或无法启动都会进入 `SECURITY_HOLD`，不会警告后继续。

## 信任根初始化

信任根只能来自用户手中已经人工确认来源可靠、曾实际安装或使用过的 Arcaea C 版
APK。仓库和安装包不预置 signer 或 package，也不会从当前网络下载物自动学习。

```powershell
python scripts/inspect_trusted_apk.py "D:\path\known-good-arcaea.apk"
```

该命令先完整验证签名，再输出 package、versionName、versionCode 和 signer 证书
SHA-256。人工核对后配置：

```text
trusted_signer_sha256 = ["64位十六进制指纹"]
trusted_package_name = "精确 package name"
```

指纹输入允许大小写、冒号和空格，内部统一为大写 64 位十六进制。列表允许多个
signer，为人工批准的 key rotation 或多 signer APK 预留；APK 报告的每个 signer
都必须已配置。未知 signer 永远不会自动加入。

不要从第三方 APK 站、搜索结果、当前 lowiro 下载 URL，或任何尚未人工确认的 APK
建立信任。如果没有 known-good APK，保持默认空配置；这是预期的安全冻结状态。

## 验证规则

每次新文件依次执行：

1. 本地路径、大小和文件 SHA-256 与下载记录一致。
2. `apksigner` 对完整 APK 的密码学签名验证成功。
3. APK 的全部 signer 证书 SHA-256 都在显式信任列表。
4. manifest package 与 `trusted_package_name` 精确相等。
5. manifest versionName 与 lowiro API 版本字符串精确相等，不删除 `c` 后缀。
6. 相同 versionName 的 versionCode 必须与已验证记录相同；新 versionName 的
   versionCode 不得低于最后已验证值。
7. Android 工具运行后再次核对文件大小和 SHA-256，防止检查期间被替换。
8. 通过后发布到 `downloads/verified/`；分发服务只接受 `VerifiedArtifact`。

已验证文件复用前仍核对其路径必须直接位于 `verified/`、大小和 SHA-256 未变化、
package 仍匹配，且所有 signer 仍在当前信任列表。工具或信任根后来不可用时，即使
存在历史 VERIFIED 记录也拒绝分发。

验证失败的文件进入 `downloads/quarantine/`；工具/信任配置缺失时保留原文件等待
修复。v0.3.0 或更早版本位于旧 `downloads/` 根目录的 APK 保留原件，可以由
`/apull verify` 重新完整验证，但绝不因迁移状态自动成为 VERIFIED。

## 安全通知与恢复

失败通知按 `version + 实际文件 SHA-256 + verdict` 去重。失败不会修改
`last_verified_version` 或 `last_verified_version_code`，已有分发成功记录也不能
绕过新安全门。

恢复步骤：

1. `/apull status` 查看 `TRUST_NOT_CONFIGURED`、`VERIFIER_UNAVAILABLE` 或具体
   hold verdict。
2. 修复 Android 工具路径，或重新核对 known-good APK 后人工更新信任配置。
3. 对未知 signer/key rotation，先通过独立可信渠道确认，再手工添加新指纹；不要
   让插件自动接受。
4. 执行 `/apull verify`。只有返回 `VERIFIED` 后才能 `/apull distribute`。

## Threat model

本安全门旨在阻止：

- metadata URL、DNS、CDN 或网络链路被劫持后替换 APK；
- 攻击者用自己的证书签名另一个恶意 APK；
- 使用正确 signer 但 package/version 身份不符的文件；
- 回退到 versionCode 更低的旧 APK；
- 本地 VERIFIED 文件在后续被修改。

本安全门不能阻止：

- lowiro 官方 signing private key 泄露；
- 用户把恶意 signer 或 package 手工加入信任配置；
- lowiro 官方构建环境自身被攻陷；
- 运行 AstrBot 的主机已被高权限恶意程序完全控制。

这不是杀毒扫描，也不会上传 APK 到第三方服务。
