"""Read-only hourly Codex desktop release check. Never download/install packages."""
import argparse
import base64
import json
import platform
import plistlib
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.parsers.expat import ExpatError
from pathlib import Path

from quota import save_cache, finite_number

SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
BACKEND = "https://updates.oaistatic.com/codex/app/appcast"


class UpdateError(Exception):
    pass


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urllib.parse.urlparse(newurl)
        if (url.scheme != "https" or url.hostname not in {"updates.oaistatic.com", "persistent.oaistatic.com"}
                or url.username or url.password):
            raise UpdateError("更新清单跳转到非官方地址，已停止")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)*", value):
        raise UpdateError("版本格式无法识别")
    parts = [int(part) for part in value.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def asar_package(path):
    with path.open("rb") as handle:
        prefix = handle.read(16)
        if len(prefix) != 16:
            raise UpdateError("应用元数据不完整")
        _, header_size, _, json_size = struct.unpack("<4I", prefix)
        if not 0 < json_size < 16 * 1024 * 1024 or header_size < json_size:
            raise UpdateError("应用元数据格式不支持")
        header = json.loads(handle.read(json_size))
        entry = header["files"]["package.json"]
        size, offset = int(entry["size"]), int(entry["offset"])
        if not 0 < size < 128 * 1024 or offset < 0:
            raise UpdateError("应用元数据格式不支持")
        handle.seek(8 + header_size + offset)
        return json.loads(handle.read(size))


def installed_app(paths=None):
    paths = paths or [Path("/Applications/ChatGPT.app"), Path("/Applications/Codex.app")]
    candidates = []
    for app in paths:
        info = app / "Contents/Info.plist"
        if not info.exists():
            continue
        try:
            data = plistlib.loads(info.read_bytes())
            if not isinstance(data, dict) or data.get("CFBundleIdentifier") != "com.openai.codex":
                continue
            package = asar_package(app / "Contents/Resources/app.asar")
            if not isinstance(package, dict):
                continue
            if package.get("codexBuildFlavor") != "prod" or package.get("codexReleaseChannel", "prod") != "prod":
                continue
            version(data["CFBundleVersion"])
            version(data["CFBundleShortVersionString"])
            candidates.append({"installedVersion": data["CFBundleShortVersionString"],
                               "installedBuild": data["CFBundleVersion"], "package": package})
        except (OSError, ValueError, TypeError, KeyError, OverflowError, ExpatError,
                plistlib.InvalidFileException, UpdateError):
            # One incomplete/obsolete installation must not hide another valid copy.
            continue
    if candidates:
        return max(candidates, key=lambda item: version(item["installedBuild"]))
    raise UpdateError("未找到本机 Codex 桌面应用")


def plan_type(home):
    try:
        data = json.loads((home / ".codex/auth.json").read_text(encoding="utf-8"))
        token = data["tokens"]["id_token"]
        if not isinstance(token, str):
            return "unknown"
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        scope = claims.get("https://api.openai.com/auth") if isinstance(claims, dict) else None
        plan = scope.get("chatgpt_plan_type") if isinstance(scope, dict) else None
        return plan if isinstance(plan, str) and plan in {"pro", "plus", "free", "team", "business", "enterprise", "edu"} else "unknown"
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return "unknown"


def feed_url(installed, home=None):
    home = home or Path.home()
    state_path = home / "Library/Application Support/com.openai.codex/production-appcast-bootstrap.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    if state.get("backendAppcastEnabled") is True:
        identity = state.get("installationId")
        if not isinstance(identity, str) or not identity:
            raise UpdateError("缺少现有 Codex 更新标识，请先启动 Codex")
        machine = platform.machine()
        if machine not in {"x86_64", "arm64"}:
            raise UpdateError("当前机器架构不支持版本检查")
        query = urllib.parse.urlencode({"installation_id": identity, "arch": "x64" if machine == "x86_64" else "arm64",
                                       "app_version": installed["installedVersion"], "beta": "false",
                                       "os-version": platform.mac_ver()[0], "plan_type": plan_type(home)})
        return BACKEND + "?" + query
    url = installed["package"].get("codexSparkleFeedUrl", "")
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "persistent.oaistatic.com" or
            not parsed.path.startswith("/codex-app-") or not parsed.path.endswith(".xml") or
            parsed.username or parsed.password or parsed.query):
        raise UpdateError("未找到受支持的官方 Codex 更新源")
    return url


def parse_feed(raw, installed, os_version=None):
    root = ET.fromstring(raw)
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise UpdateError("官方更新清单格式无法识别")
    current = version(installed["installedBuild"])
    system = version(os_version or platform.mac_ver()[0])
    choices = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        release_channel = item.findtext(SPARKLE + "channel", "")
        if release_channel not in {"", "stable", "prod"}:
            continue
        minimum = item.findtext(SPARKLE + "minimumSystemVersion")
        maximum = item.findtext(SPARKLE + "maximumSystemVersion")
        if minimum and version(minimum) > system or maximum and version(maximum) < system:
            continue
        build = item.findtext(SPARKLE + "version") or enclosure.get(SPARKLE + "version")
        if not build:
            raise UpdateError("官方更新清单缺少版本号")
        human = item.findtext(SPARKLE + "shortVersionString") or enclosure.get(SPARKLE + "shortVersionString") or build
        if version(build) > current:
            choices.append((version(build), human, build))
    newest = max(choices) if choices else None
    return {"state": "available" if newest else "up_to_date", "installedVersion": installed["installedVersion"],
            "installedBuild": installed["installedBuild"], "availableVersion": newest[1] if newest else None,
            "availableBuild": newest[2] if newest else None, "checkedAt": time.time(), "error": None}


def check(cache):
    installed = installed_app()
    request = urllib.request.Request(feed_url(installed), headers={"User-Agent": "CodexQuotaWidget/1.0", "Accept": "application/xml"})
    try:
        with urllib.request.build_opener(OfficialRedirect).open(request, timeout=15) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise UpdateError("更新清单过大")
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"更新源暂不可用（HTTP {exc.code}）") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateError("版本检查网络失败，将在下次小时检查重试") from None
    result = parse_feed(raw, installed)
    if installed_app()["installedBuild"] != installed["installedBuild"]:
        raise UpdateError("安装版本已变化，请重新检查")
    save_cache(cache, result)
    return result


def cached(cache):
    if not Path(cache).exists():
        return {"state": "unknown", "error": "尚未检查版本"}
    value = json.loads(Path(cache).read_text(encoding="utf-8"))
    current = installed_app()
    if not isinstance(value, dict):
        raise UpdateError("版本缓存格式无效")
    if value.get("installedBuild") != current["installedBuild"]:
        return {"state": "unknown", "installedVersion": current["installedVersion"], "error": "安装版本已变化，等待检查"}
    if value.get("state") not in {"available", "up_to_date"} or not finite_number(value.get("checkedAt"), 1, 253402300799):
        raise UpdateError("版本缓存无效")
    if value["state"] == "available":
        if version(value.get("availableBuild")) <= version(current["installedBuild"]):
            raise UpdateError("版本缓存无效")
        version(value.get("availableVersion"))
    return {key: value[key] for key in ("state", "installedVersion", "installedBuild",
            "availableVersion", "availableBuild", "checkedAt") if key in value}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = check(args.cache) if args.check else cached(args.cache)
    except Exception as exc:
        try:
            result = cached(args.cache)
        except Exception:
            result = {"state": "unknown"}
        result["error"] = str(exc) if isinstance(exc, UpdateError) else "版本检查失败，请稍后重试"
    print(json.dumps(result, ensure_ascii=False))
