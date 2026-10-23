"""Export only the files explicitly listed in PUBLIC_FILES.txt. No credentials are read."""
import argparse
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def public_files(root=ROOT):
    entries = []
    for line in (root / "PUBLIC_FILES.txt").read_text(encoding="utf-8").splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name or name in entries:
            raise ValueError("公开文件清单包含重复或不安全路径")
        source = root / name
        if (not source.is_file() or any(parent.is_symlink() for parent in
                [source, *source.parents] if parent != root.parent)):
            raise ValueError("公开文件缺失或使用了符号链接：" + name)
        if (name.endswith((".local.json", ".local.md", ".pem", ".key", ".p12", ".log"))
                or any(part in {".build", ".git", ".codex", ".env", "__pycache__"} for part in path.parts)
                or any(part.startswith(".env.") and part != ".env.example" for part in path.parts)
                or path.name in {"auth.json", ".DS_Store"}):
            raise ValueError("公开文件清单包含私有文件：" + name)
        entries.append(name)
    if not entries:
        raise ValueError("公开文件清单为空")
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate and print file names without packaging")
    args = parser.parse_args()
    names = public_files()
    for name in names:
        print(name)
    if args.check:
        print(f"公开文件清单有效：{len(names)} 个文件；此检查不替代凭据扫描")
        return
    output = ROOT / ".build/codex-quota-widget-source.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".zip", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.write(ROOT / name, "codex-quota-widget/" + name)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print("源码上传包：" + str(output))
    print("请先解压，再上传包内文件；不要把 ZIP 本身当作 GitHub 仓库源码。")


if __name__ == "__main__":
    main()
