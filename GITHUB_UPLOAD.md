# 第一次上传 GitHub

本指南使用浏览器上传，不需要先学习 Git 命令。执行打包脚本只准备本地文件，不会创建远程仓库或公开发布。

## 1. 生成干净的源码包

在项目目录执行：

```sh
python3 scripts/package_source.py
```

解压 `.build/codex-quota-widget-source.zip`，得到 `codex-quota-widget` 文件夹。这份解压目录是准备上传的源码，原始工作目录还包含私人缓存和构建产物，不要直接拖拽整个原始目录。

用 `PUBLIC_FILES.txt` 逐项核对文件。Finder 默认隐藏 `.gitignore` 和 `.github`：按 `Command + Shift + .` 显示隐藏文件，以免漏传。

## 2. 创建仓库

在 GitHub 登录后，点击右上角 `+` → `New repository`。

- Repository name：建议 `codex-quota-widget`。
- Description：可填“轻量 macOS Codex 额度悬浮窗，支持额度、重置卡到期和版本更新提示”。
- Visibility：第一次可先选 **Private**，检查上传内容后再决定是否改为 Public。
- 不要勾选自动生成 README，也不要另选 gitignore 或 license；源码包已包含这些文件。

点击 `Create repository`。

## 3. 上传解压后的文件

空仓库页点击 `uploading an existing file`；已有内容的仓库通常使用 `Add file` → `Upload files`。

打开解压得到的 `codex-quota-widget` 文件夹，选中它里面的文件和子目录上传。仓库根目录应该直接显示 `README.md`、`LICENSE`、`QuotaWidget.swift` 等，而不是再套一层同名文件夹。不要上传 ZIP 本身。

检查 `.gitignore`、`.github/workflows/checks.yml`、`tests`、`scripts` 和 `docs/images` 是否都在。上传完成后，填写提交说明，例如 `Prepare initial open-source version`，点击 `Commit changes`。

若网页限制上传 `.github/workflows`，可用仓库网页文件编辑器创建相同路径，或使用 GitHub Desktop 上传完整目录，不要省略自动检查文件。通过 Git 命令提交时应使用 Git 忽略规则；本指南的浏览器上传不会自动遵守 `.gitignore`。

## 4. 检查仓库页面

- README 能显示介绍和虚构数据截图，许可证显示为 MIT。
- 根目录只有公开清单中的文件，没有 `usage.local.json`、`version.local.json`、`.build`、登录文件、日志或历史本机检查记录。
- Actions 中的 `Offline checks` 已完成。它不需要配置 Codex 登录或 GitHub Secrets；首次远端运行前不能把工作流视为已经验证成功。
- 从 GitHub 下载一次源码，按 README 尝试构建。源码包与可直接安装的 macOS 应用不是一回事。

确认内容无误后，可在仓库 Settings 的可见性设置中改为 Public。公开后不要上传真实额度截图、登录文件或本机生成的 `.app`。

## 更新项目

修改后重新运行测试和打包命令，只从新源码包解压后的目录上传变动文件；如果删除或重命名了文件，也要在远程仓库删除旧文件，单纯上传不会替你删除。熟悉 GitHub 后，可改用 GitHub Desktop 管理提交和推送。

正式发布前请阅读 [发布检查](RELEASING.md)，不要把上传仓库与发布通用安装包混为一谈。

参考：[创建仓库](https://docs.github.com/en/repositories/creating-and-managing-repositories/quickstart-for-repositories)、[上传文件](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)、[Git 忽略规则](https://docs.github.com/en/get-started/git-basics/ignoring-files)。
