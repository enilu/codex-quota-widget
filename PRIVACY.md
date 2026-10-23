# 数据与隐私说明

## 本地读取

- `~/.codex/auth.json`：读取 access token 和 account ID，用于请求当前账号的额度；版本检查还会从 ID token 中提取套餐类型。不会刷新、修改或复制此登录文件到项目。
- Codex 安装目录：读取 `Info.plist` 和 `app.asar` 中的版本、通道及更新源配置。
- `~/Library/Application Support/com.openai.codex/production-appcast-bootstrap.json`：读取既有安装实例标识和更新源开关，不生成或修改实例标识。
- 本工具的额度/版本缓存，以及用于配色和窗口位置的 macOS 用户偏好。

不读取浏览器 Cookie、其他额度工具的账号配置或聊天记录。凭据仅在读取子进程内存和向官方接口发出的 HTTPS 请求中使用。仅在默认登录文件包含所需字段时可用。

## 网络请求

| 目的 | 目标与方法 | 发送的信息 |
| --- | --- | --- |
| 额度 | `GET https://chatgpt.com/backend-api/wham/usage` | Authorization bearer token、ChatGPT account ID、固定 User-Agent |
| 重置卡 | `GET https://chatgpt.com/backend-api/wham/rate-limit-reset-credits` | 同上 |
| 版本提示 | `GET https://updates.oaistatic.com/codex/app/appcast`，或安装包配置的官方静态清单 | 在使用后端清单时发送已有 installation ID、架构、应用版本、系统版本、套餐类型和 `beta=false` |

额度接口拒绝重定向。版本清单仅允许 HTTPS 跳转到 `updates.oaistatic.com` 或 `persistent.oaistatic.com`，请求不携带登录凭据。所有请求保持默认 HTTPS 证书验证；Python 标准网络库可能遵循系统/环境的代理设置。

启动后额度每分钟读取，版本清单每小时检查，也可手动触发。没有分析 SDK、广告、项目作者服务器或主动遥测。官方服务仍会接收到请求 IP 和上述请求信息；其数据处理由服务提供方负责。

## 本地写入与删除

- `usage.local.json`：百分比、窗口周期、重置与卡片到期时间、读取时间、错误说明及 account ID 的 SHA-256 摘要。摘要用于阻止不同账号混用缓存，不等于匿名数据。
- `version.local.json`：安装/可用版本、构建号、检查时间及状态。
- 临时读取输出：使用随机文件名、0600 权限；正常结束、超时和受控退出时清理。系统崩溃或强制杀死应用时仍可能留有临时文件。
- macOS 用户偏好：配色、窗口位置。应用沿用 `local.ycwang.codex-quota-widget` 这一历史本地 bundle ID，它不是网络地址。
- `.build/`：构建和检查产物。生成应用的 plist 含本机 Python 与缓存绝对路径，因此不可作为通用安装包公开。

JSON 缓存使用 0600 临时文件原子替换，不写入 token、Cookie、邮箱或原始账号/卡片 ID。退出应用后可以删除本工具的两个缓存文件；下次启动将重新查询。切勿为清理本工具而删除 Codex 自身的登录文件。

## 公开与反馈

源码中的字段名、官方接口 URL 和测试中的 `TOKEN` / `ACCOUNT` 等虚构字符串不是实际凭据。真实缓存、个人路径、登录文件、构建应用、日志及历史账号截图均不应公开。

`PUBLIC_FILES.txt` 列出计划公开的文件；打包脚本仅复制清单中的文件并拒绝私有文件名和符号链接。Git 忽略规则只作用于 Git；浏览器手动上传文件时不会替你过滤。发布前应检查真实上传清单，任何文件清单或扫描工具都不能替代人工核对。

如反馈问题，请只提供脱敏后的错误提示、系统/解释器版本和最小复现步骤，不要上传 `auth.json`、原始请求响应、真实缓存、JWT 或带账号信息的截图。
