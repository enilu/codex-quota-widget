"""Build the standalone macOS widget using the Python running this script."""
import argparse
import plistlib
import shutil
import ssl
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / ".build/Codex额度悬浮窗.app",
                        help="Application bundle output path")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("构建需要 macOS 和 Xcode Command Line Tools（swiftc）")
    if sys.version_info < (3, 12):
        raise SystemExit("请使用 Python 3.12 或更新版本构建")
    if not shutil.which("swiftc"):
        raise SystemExit("未找到 Swift 编译器，请先安装 Xcode Command Line Tools")
    if not ssl.create_default_context().cert_store_stats()["x509_ca"]:
        raise SystemExit("当前 Python 未加载 HTTPS 受信任 CA，请先修复此 Python 的证书配置，参见 README")
    app = args.output.expanduser().resolve()
    if app.suffix != ".app":
        raise SystemExit("输出路径必须以 .app 结尾")
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(exist_ok=True)
    module_cache = root / ".build/module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    subprocess.run(["swiftc", "-O", "-module-cache-path", str(module_cache), str(root / "QuotaWidget.swift"),
                    "-o", str(contents / "MacOS/CodexQuotaWidget"), "-framework", "Cocoa"], check=True)
    for name in ("quota.py", "updates.py"):
        shutil.copyfile(root / name, contents / "Resources" / name)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleExecutable": "CodexQuotaWidget", "CFBundleIdentifier": "local.ycwang.codex-quota-widget",
                      "CFBundleName": "Codex额度悬浮窗", "CFBundleVersion": "1", "CFBundleShortVersionString": "1.0",
                      "CFBundlePackageType": "APPL", "LSUIElement": True, "NSHighResolutionCapable": True,
                      "QuotaPython": sys.executable, "QuotaCache": str(root / "usage.local.json")}, handle)
    print("构建成功：" + str(app))


if __name__ == "__main__":
    main()
