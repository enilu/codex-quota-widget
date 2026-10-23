# Codex 额度悬浮窗

一个轻量的 macOS 原生小工具，把 Codex 剩余额度、重置时间和重置卡到期提醒放在桌面上。

使用 Swift / Cocoa 绘制界面，Python 标准库读取数据，无第三方运行依赖，也不依赖 CodexBar。

> 个人社区项目，与 OpenAI 无隶属关系。当前提供源码构建；仅支持 macOS。额度接口及更新清单属于客户端内部契约，可能随上游版本变化。

![深灰配色示例](docs/images/graphite.png)

*图片使用程序生成的虚构数据，不代表真实账号额度。*

## 功能

- 显示周期最长的 Codex 额度窗口，通常为周额度；显示剩余百分比、重置倒计时及 GMT+8 时间。
- 根据剩余额度和距重置的天数，显示日均可用预算；这不是消耗速度或可用时长预测。
- 显示可用重置卡数量和最早到期时间；不足 24 小时显示橙色，不足 3 小时显示红色。
- 启动读取一次，之后每分钟刷新额度，每秒更新本地倒计时；支持手动刷新。
- 每小时检查 Codex 稳定版更新，有更新时显示圆点。只提示，不下载或安装更新。
- 支持拖动、置顶、隐藏、菜单栏恢复，以及深灰、雾灰、暖杏三套配色。
- 读取失败时保留可验证为同一账号的历史缓存；过期数据有提示，不假定重置后额度已经恢复。

## 使用前准备

1. 一台 Mac，以及 Xcode Command Line Tools（提供 `swiftc`）。如果尚未安装，在终端执行 `xcode-select --install`，按系统提示完成安装。
2. Python **3.12+**，且该解释器能加载受信任的 HTTPS CA 证书；已验证版本及平台见下方支持说明。
3. 已安装并登录 Codex 桌面应用，登录数据可从默认位置 `~/.codex/auth.json` 读取。

不支持 Windows / Linux。仅有 API Key、凭据仅存在钥匙串、使用自定义 `CODEX_HOME` 或第三方多账号管理器的环境，目前不在支持范围内。应用检测目前扫描 `/Applications/Codex.app` 和 `/Applications/ChatGPT.app` 中的 Codex 稳定版安装。

本地已验证 macOS 26.7.1 / Intel x86_64 / Python 3.12.14 构建；Python 3.13.2 仅完成离线 Python 测试。Apple Silicon、其他 macOS 和所有账号套餐尚未逐项验证，没有承诺最低 macOS 版本或后续 Python 版本兼容。

## 构建与启动

下载源码并解压，在终端进入 `codex-quota-widget` 目录，然后执行：

```sh
python3 --version
swiftc --version
python3 build.py
open .build/Codex额度悬浮窗.app
```

构建脚本使用运行它的 Python 解释器。若 `python3` 版本过旧，可改用已安装的 `python3.12` 或更新版本执行所有 Python 命令。构建时不查询账号或联网下载依赖，`open` 启动应用后才开始读取数据。

构建包位于 `.build/Codex额度悬浮窗.app`。也可在 Finder 按 `Command + Shift + G`，输入源码目录中的 `.build` 路径，再双击应用。

**请保持源码目录及 Python 环境的位置不变。** 当前构建会绑定本机解释器和源码目录中的缓存路径；移动源码、删除 Python 环境后需要重新构建。生成的 `.app` 不是适合直接发给其他人的通用安装包，也尚未做开发者签名和公证。首次运行遇到系统拦截时请遵循 macOS 的安全提示，不需要全局关闭安全保护。

启动后可通过窗口按钮操作，或点击菜单栏的额度仪表图标恢复隐藏窗口、刷新、切换配色。隐藏不影响后台刷新；从菜单或窗口点击退出会停止定时器并回收读取进程。项目不会自动安装登录启动项。

## 当前局限性

- 只展示周期最长的一个额度窗口；周额度充足不代表短窗口仍可使用，不统计本地 token、API 余额或账单。
- 提醒为窗口内的颜色变化，没有系统通知、声音或后台推送。
- 日期固定为 GMT+8，界面为中文，暂不支持时区/语言设置。
- 配色和窗口位置会保存；隐藏与置顶状态不跨启动保存，启动默认显示并置顶。
- 不支持多账号管理、自动使用卡片、自动更新 Codex，也没有多实例协调。
- 接口、登录存储、安装位置和上游清单结构变化可能使部分功能不可用；未完成长期驻留、睡眠恢复和全平台验证。

完整行为、异常处理、环境验证与未支持事项见 [支持范围与已知限制](docs/SUPPORT.md)。

## 更新与卸载

更新源码前先退出旧应用，在原目录更新源码并重新构建，再启动新应用；不要同时运行多个副本。只更新源码不会自动替换应用包内的 Python 文件。

卸载时先从菜单或窗口退出，再删除本工具的 `.app`、源码目录及其中的两个缓存即可。配色/窗口偏好存于 macOS 用户偏好中，可按需单独清除；不要删除 Codex 的 `~/.codex` 登录目录。若曾自行设置登录启动，请同时在系统设置中移除对应启动项。

## 数据与隐私

完整说明见 [PRIVACY.md](PRIVACY.md)。主要行为：

- 仅使用本机 Codex 登录数据，读取额度和重置卡；不兑换卡片，不刷新或改写登录文件，不读取浏览器 Cookie。
- 额度请求仅向 `chatgpt.com` 的两个固定 HTTPS GET 接口发送 access token 和账号范围，并拒绝重定向。
- 版本检查使用官方更新源，可能发送已有的安装实例标识、系统/应用版本、架构及套餐类型；不携带登录 token 或 Cookie。
- 缓存只存额度、时间、状态和账号摘要等必要信息。摘要仍属于账号关联信息，不应公开。
- 不向项目作者发送遥测或使用数据。

`usage.local.json`、`version.local.json` 和 `.build/` 都是本地文件，已加入 Git 忽略规则。请不要上传整个工作目录或真实账号截图。

## 开发与验证

```sh
python3 -m unittest discover -s tests -v
python3 build.py
.build/Codex额度悬浮窗.app/Contents/MacOS/CodexQuotaWidget --check-guidance
.build/Codex额度悬浮窗.app/Contents/MacOS/CodexQuotaWidget --check-reader "$(command -v python3)"
```

Python 用例使用模拟响应和临时文件；两种 Swift 检查模式仅执行计算或可丢弃子进程，不访问真实账号或接口。GitHub Actions 已配置相同的离线检查与 macOS 编译，首次上传后可查看运行结果。

项目结构、构建选项、CLI 语义和手工验证见 [开发说明](docs/DEVELOPMENT.md)。

生成不读取账号、缓存或网络的文档预览：

```sh
.build/Codex额度悬浮窗.app/Contents/MacOS/CodexQuotaWidget \
  --preview .build/demo.png --demo --theme graphite
```

配色参数还支持 `fog` / `apricot`。只有 `--preview` 与 `--demo` 同时使用才会生成虚构数据；不带 `--demo` 的预览会回读本机缓存，请勿用于公开截图。

## 常见问题

**构建提示没有受信任 CA？** 这是当前 Python 的证书配置问题。若使用 python.org 的 macOS 安装包，可检查其应用程序目录中的 `Install Certificates.command`。修复后使用同一解释器重新构建，不要关闭 HTTPS 校验。

**显示登录失效或暂不可用？** 先确认 Codex 本身可正常使用，再点击刷新。若仍失败，接口结构或登录存储方式可能已经变化。提交问题时只提供已脱敏的错误提示、系统和 Python 版本，切勿附带登录文件。

**“状态未知”是否意味着没有卡？** 不是。字段缺失、未知状态或网络失败时会显示未知；只有成功读取并确认没有未到期可用卡片时才显示无卡。

**是否支持 beta 更新、自动升级或多账号切换？** 目前只提示稳定版更新，不执行升级。每次读取默认 Codex 登录位置；切换账号后需等待下一次刷新或手动刷新，不支持管理多份账号配置。

## 上传 GitHub

首次上传请使用 [GitHub 上传指南](docs/GITHUB_UPLOAD.md) 和 [公开文件清单](PUBLIC_FILES.txt)。运行以下命令可生成只含公开文件的源码包：

```sh
python3 scripts/package_source.py
```

请解压 `.build/codex-quota-widget-source.zip`，再把解压后的文件上传为仓库源码；不要直接上传 ZIP 或整个本地工作目录。此脚本只验证文件清单与路径，不是凭据扫描器。

## 参与与许可证

欢迎提交问题和改进，见 [贡献指南](CONTRIBUTING.md)；安全问题见 [SECURITY.md](SECURITY.md)。

当前仍为首次公开发布前的源码准备状态，尚未发布正式 GitHub Release。更新记录见 [CHANGELOG.md](CHANGELOG.md)，维护者发布前请按 [发布检查](docs/RELEASING.md) 核对。

本项目采用 [MIT 许可证](LICENSE)，允许使用、修改、分发和商用，需保留版权和许可声明。许可证仅覆盖本项目代码，不授予第三方产品商标或服务访问权限。
