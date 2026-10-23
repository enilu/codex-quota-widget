# Windows 适配

Windows 入口为 `windows_widget.py`，默认加载 `windows_glass.py` 的 Qt 无标题栏界面，通过 Windows 原生合成接口显示 Acrylic 毛玻璃。复用 `quota.py` 的固定 GET 请求、响应归一化与账号缓存隔离。需要 Python 3.12 和 PySide6-Essentials，不需要 macOS 或 Swift。已在 Windows 实机验证真实额度及重置卡读取。

首次安装：`python -m pip install -r requirements-windows.txt`。原 Tk 界面保留为 `python windows_widget.py --classic`，无 Qt 依赖。

## 启动和使用

- PowerShell：`./start-windows.ps1`，使用当前 Python 旁的 `pythonw.exe` 在后台启动，无控制台窗口。
- 排查启动问题：`python windows_widget.py`，在终端查看诊断。
- 预览：`./start-windows.ps1 -Demo`，只用虚构数据，不读取登录或额度缓存、不联网、不保存偏好。
- 默认无系统标题栏、圆角、置顶，拖动顶部空白区域移动；右上角图标依次为置顶、配色、最小化、退出。配色轮换深灰/雾灰/暖杏；最小化后点击任务栏图标恢复，Ctrl+Q 退出。
- 快捷键：Ctrl+T 切换配色，Ctrl+P 切换置顶，Ctrl+M 最小化。
- 启动立即刷新，每 60 秒再次读取；F5 或“刷新”手动读取，已有读取运行时不会重复启动。
- Windows 命名互斥锁避免同一用户会话重复启动。再次启动不会把已有最小化窗口自动恢复，请从任务栏恢复。

登录目录按 `--home`、`CODEX_HOME`、用户目录下 `.codex` 的顺序选择。仅有 API Key 或不可读的凭据存储不支持。不会刷新 token 或改写 `auth.json`。

额度快照与原版使用相同的 `usage.local.json`；主题与位置退出时存到 `windows.local.json`。Windows 文件权限沿用存放目录的 ACL，不声称具备 POSIX 的 0600 模式。请勿公开这些本地文件。

毛玻璃通过系统合成器实时模糊窗口后方内容，支持深浅色调；系统关闭透明效果或不支持 Acrylic 时可能显示纯色材质。Qt 自动适配高 DPI；无标题栏窗口仍保留任务栏入口和原生窗口拖动。未使用背景截图模拟模糊。

## 与 macOS 版本的差异

Windows 使用任务栏恢复窗口，暂无系统托盘菜单。暂不执行 Codex 版本检测，不查询 macOS 更新源；请使用 Codex 自身更新功能。未打包独立 EXE，源码和 Python 环境需要保留。重置卡少于 24 小时显示橙色；不提供系统通知、卡片兑换、账号管理或开机自启。

Windows GUI 启动隐藏的读取子进程，管道固定为 UTF-8，避免中文 Windows 默认编码影响 JSON 解析。读取超时为 35 秒，退出时终止并回收自己的读取进程。失败保留缓存前重新核对账号；过期额度不会推断为恢复到 100%。休眠恢复、长期驻留和多显示器场景仍需更多验证。

## 开发检查

```powershell
python -m unittest discover -s tests -v
python scripts/package_source.py --check
```

离线测试包含历史额度、重置卡未知/到期、读取超时与退出回收、自定义登录目录。Windows 缺少创建符号链接权限时，仅跳过源码打包中的符号链接用例；不需要为运行程序更改系统安全设置。
