"""Independent read-only Codex quota/reset-credit client. No CodexBar dependency."""
import argparse
import hashlib
import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HOST = "https://chatgpt.com"


class QuotaError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the local login token to another URL or host.
        return None


def auth(home=None):
    home = home or Path.home() / ".codex"
    try:
        tokens = json.loads((home / "auth.json").read_text(encoding="utf-8"))["tokens"]
        token, account = tokens["access_token"], tokens["account_id"]
        if not isinstance(token, str) or not token or not isinstance(account, str) or not account:
            raise ValueError()
        return token, account
    except (OSError, ValueError, TypeError, KeyError):
        raise QuotaError("未找到 Codex 登录状态，请先在 Codex 登录") from None


def account_hash(account):
    return hashlib.sha256(account.encode("utf-8")).hexdigest()


def get_json(path, token, account):
    if path not in {"/backend-api/wham/usage", "/backend-api/wham/rate-limit-reset-credits"}:
        raise QuotaError("不允许的读取接口")
    request = urllib.request.Request(HOST + path, headers={
        "Authorization": "Bearer " + token, "ChatGPT-Account-ID": account,
        "Accept": "application/json", "User-Agent": "CodexQuotaWidget/1.0",
    }, method="GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=12) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise QuotaError("服务响应过大，未处理")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise QuotaError(f"登录状态失效或访问被拒绝（HTTP {exc.code}），请在 Codex 重新登录") from None
        raise QuotaError(f"官方接口暂不可用（HTTP {exc.code}）") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise QuotaError("网络连接失败，请检查网络后手动刷新") from None
    except (ValueError, TypeError):
        raise QuotaError("官方接口未返回有效 JSON") from None


def finite_number(value, minimum, maximum):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and minimum <= value <= maximum and math.isfinite(value))


def timestamp(value):
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("时间缺少时区")
        value = parsed.timestamp()
    elif finite_number(value, 1, 253402300799000):
        value = float(value) / (1000 if value > 1e12 else 1)
    if not finite_number(value, 1, 253402300799):
        raise ValueError("无效时间")
    return float(value)


def normalize_usage(payload):
    limits = payload.get("rate_limit") if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        raise QuotaError("未返回 Codex 额度窗口，暂无法读取")
    windows = []
    for key in ("primary_window", "secondary_window"):
        value = limits.get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise QuotaError("额度窗口字段无效")
        used = value.get("used_percent")
        duration = value.get("limit_window_seconds")
        if (not finite_number(used, 0, 100) or
                not finite_number(duration, 1, 366 * 86400)):
            raise QuotaError("额度窗口字段无效")
        try:
            reset = timestamp(value.get("reset_at"))
        except ValueError:
            raise QuotaError("额度重置时间缺失") from None
        windows.append({"remaining": 100 - used, "resetsAt": reset, "seconds": duration})
    if not windows:
        raise QuotaError("当前账户没有可读取的额度窗口")
    # Prefer the weekly/longest common Codex window, matching the requested 5d 20h style.
    windows.sort(key=lambda value: value["seconds"], reverse=True)
    return windows[0]


def normalize_credits(payload, now=None):
    now = time.time() if now is None else now
    if not isinstance(payload, dict) or not isinstance(payload.get("credits"), list):
        raise QuotaError("重置卡返回格式无法识别")
    expires = []
    for credit in payload["credits"]:
        if not isinstance(credit, dict):
            raise QuotaError("重置卡返回格式无法识别")
        status = credit.get("status")
        if not isinstance(status, str) or status not in {"available", "used", "expired"}:
            raise QuotaError("重置卡状态缺失或无法识别")
        if status != "available":
            continue
        try:
            expiry = timestamp(credit.get("expires_at"))
        except ValueError:
            raise QuotaError("可用重置卡缺少到期时间") from None
        if expiry > now:
            expires.append(expiry)
    return sorted(expires)


def save_cache(path, value):
    path = Path(path)
    if not path.name.endswith(".local.json"):
        raise QuotaError("缓存文件必须使用 .local.json 后缀")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".local.json", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def read_cache(path, home=None):
    _, account = auth(home)
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("缓存格式无效")
        if value.get("accountHash") != account_hash(account):
            raise QuotaError("Codex 账号已变化，请手动刷新")
        if (not finite_number(value.get("remaining"), 0, 100) or
                not finite_number(value.get("windowSeconds"), 1, 366 * 86400)):
            raise ValueError("缓存额度无效")
        for field in ("resetsAt", "updatedAt"):
            # Cache timestamps are already seconds, never infer milliseconds again.
            if not finite_number(value.get(field), 1, 253402300799):
                raise ValueError("缓存时间无效")
        cards = value.get("creditExpiries")
        if cards is not None and (not isinstance(cards, list) or
                any(not finite_number(item, 1, 253402300799) for item in cards)):
            raise ValueError("缓存卡片无效")
        for field in ("creditError", "error"):
            if value.get(field) is not None and not isinstance(value[field], str):
                raise ValueError("缓存说明无效")
        return {key: value[key] for key in ("remaining", "resetsAt", "windowSeconds",
                "creditExpiries", "creditError", "updatedAt", "accountHash", "error") if key in value}
    except (OSError, ValueError):
        raise QuotaError("尚无额度数据，请点击刷新") from None


def refresh(path, home=None):
    token, account = auth(home)
    usage = normalize_usage(get_json("/backend-api/wham/usage", token, account))
    credits, credit_error = None, None
    try:
        credits = normalize_credits(get_json("/backend-api/wham/rate-limit-reset-credits", token, account))
    except QuotaError as exc:
        credit_error = str(exc)
    # Re-read account identity so a mid-request account switch cannot publish old data.
    if auth(home)[1] != account:
        raise QuotaError("Codex 账号已变化，请重新刷新")
    value = {"remaining": usage["remaining"], "resetsAt": usage["resetsAt"],
             "windowSeconds": usage["seconds"], "creditExpiries": credits,
             "creditError": credit_error, "updatedAt": time.time(), "accountHash": account_hash(account)}
    save_cache(path, value)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    try:
        value = refresh(args.cache) if args.refresh else read_cache(args.cache)
    except Exception as exc:
        try:
            value = read_cache(args.cache)
        except Exception:
            value = {}
        value["error"] = str(exc) if isinstance(exc, QuotaError) else "读取失败，请检查登录状态后重试"
    # Only normalized numbers/timestamps and safe diagnostics; no bearer or account ID.
    value.pop("accountHash", None)
    print(json.dumps(value, ensure_ascii=False))
