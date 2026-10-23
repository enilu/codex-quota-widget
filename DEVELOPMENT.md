# 开发与项目结构

## 目录与职责

```text
QuotaWidget.swift       Cocoa 界面、定时器、展示计算、读取进程管理与离线自检
quota.py                默认登录读取、固定额度 GET、字段归一化、账号缓存隔离
updates.py              安装检测、官方 appcast 读取、稳定版本比较与版本缓存
build.py                使用当前 Python 调用 swiftc，组装本机 .app
scripts/package_source.py  按 PUBLIC_FILES.txt 生成纯源码 ZIP
tests/                  合成数据与临时文件/进程测试
.github/                离线 CI、问题模板与 PR 模板
docs/                   支持矩阵、开发/发布/上传说明、虚构数据截图
```

项目没有第三方 Python 依赖，不需要 `requirements.txt`；不是可供 pip 安装的 Python 包，也不是 Swift Package，因此不添加无实际用途的 `pyproject.toml` 或 `Package.swift`。

## 数据流

Cocoa 定时器或按钮 → 后台 `ReaderPool` 启动绑定的 Python → 读取并验证字段 → 私有 JSON 缓存及仅含展示字段的标准输出 → Swift 解码 → 主线程更新界面。

两个读取模块各自去重、超时与回读缓存。额度刷新后再次校验账号；版本检查后再次校验安装构建号。受控退出后，进程池拒绝新任务并清理当前自有子进程。UI 不保存 token，也不直接执行 HTTP 请求。

原生计算和进程检查位于 Swift 源码的检查模式中；Python 回归位于 `tests/`。该分工用于保持标准库和直接 `swiftc` 构建方式。

## 本地开发

使用满足 README 要求的同一个 Python 解释器运行构建与检查。构建前退出需要重建的应用，或使用独立输出路径，避免替换运行中的二进制：

```sh
python3 -m unittest discover -s tests -v
python3 build.py --output .build/Development.app
.build/Development.app/Contents/MacOS/CodexQuotaWidget --check-guidance
.build/Development.app/Contents/MacOS/CodexQuotaWidget --check-reader "$(command -v python3)"
python3 scripts/package_source.py --check
```

`--check-guidance` 检查预算、临期、时效和极端倒计时；`--check-reader` 检查正常/异常输出、缺失解释器、超时强制回收、退出清理与拒绝后续任务。它们不会启动真实账号请求。

## 公开截图

```sh
.build/Development.app/Contents/MacOS/CodexQuotaWidget \
  --preview .build/demo.png --demo --theme graphite
```

输出目录必须预先存在。此模式生成虚构额度与卡片，不读取登录和缓存，不访问网络或更改保存的配色。`fog` / `apricot` 可切换预览主题。

其他历史预览开关（如 `--urgent-card`、`--no-cards`、`--stale-data`、`--preview-update`）作用于缓存预览分支，不能与 `--demo` 叠加作为公开示例。公开截图统一使用上面的 demo 命令。

## CLI 与构建配置

| 入口 | 行为 |
| --- | --- |
| `python3 build.py` | 生成默认 `.build/Codex额度悬浮窗.app`，绑定当前解释器和源码目录缓存 |
| `python3 build.py --output 路径.app` | 修改应用包输出位置；不修改缓存位置或复制 Python 环境 |
| `python3 quota.py usage.local.json` | 读取且校验当前账号缓存，输出展示 JSON；仍需可读的登录文件，不联网 |
| `python3 quota.py usage.local.json --refresh` | 实际访问两个官方额度接口并更新缓存 |
| `python3 updates.py version.local.json` | 读取版本缓存并校验当前安装，不联网 |
| `python3 updates.py version.local.json --check` | 实际请求官方更新清单并更新版本缓存 |
| `python3 scripts/package_source.py --check` | 验证公开清单和安全路径，只打印文件名 |
| `python3 scripts/package_source.py` | 生成 `.build/codex-quota-widget-source.zip` |

两个读取 CLI 为了让 GUI 始终能解析诊断，失败时也可能以退出码 0 输出带 `error` 的 JSON；不能仅凭进程退出码判断官方读取成功。直接运行它们会显示真实数据，请勿把输出粘贴到公开 Issue。源码包导出仅检查清单与文件路径，不扫描任意内容或 Git 历史。

## 测试与手工检查

- 自动：Python 回归、Swift 原生计算、读取进程生命周期、公开清单检查和 macOS 编译。
- 手工：启动/退出、隐藏/恢复、置顶、配色重启恢复、菜单操作、多显示器、键盘及辅助功能。
- 使用真实服务的验证需另行进行；CI 不使用账号，不配置 Codex Secrets，不会证明内部服务始终兼容。

目前本地完成的检查及尚未验证的平台见 [支持范围](SUPPORT.md)。发布流程见 [RELEASING.md](RELEASING.md)。
