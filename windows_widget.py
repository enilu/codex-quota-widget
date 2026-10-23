"""Windows quota widget using only Python's standard library and Tk."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone

import quota

ROOT = Path(__file__).resolve().parent
THEMES = {
    "graphite": ("#202329", "#f3f5f7", "#a7afb9", "#82d9ae"),
    "fog": ("#e9edf1", "#252d38", "#596779", "#167c60"),
    "apricot": ("#f6e8d7", "#44352c", "#806957", "#287354"),
}
GMT8 = timezone(timedelta(hours=8))


def countdown(seconds):
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{days}天 {hours:02}:{minutes:02}:{seconds:02}"


def presentation(data, now):
    """Calculate display fields without guessing that a reset restored quota."""
    result = dict(percent="—", reset="等待额度数据", budget="", cards="重置卡：状态未知",
                  status=data.get("error", "尚无数据"), urgent=False, remaining=0)
    if "remaining" not in data:
        return result
    remaining = data["remaining"]
    seconds = data["resetsAt"] - now
    age = now - data["updatedAt"]
    stale = age > 180 or age < -60 or bool(data.get("error")) or seconds <= 0
    result.update(percent=f"{remaining:.0f}%", remaining=remaining,
                  reset="等待刷新确认重置" if seconds <= 0 else f"距重置  {countdown(seconds)}")
    result["reset"] += "\n" + datetime.fromtimestamp(data["resetsAt"], GMT8).strftime("%m月%d日 %H:%M GMT+8")
    result["budget"] = ("历史额度 · 等待更新" if stale else
                        f"日均可用预算  {min(remaining, remaining / max(seconds / 86400, 1)):.1f}%")
    cards = data.get("creditExpiries")
    if cards is not None:
        valid = sorted(expiry for expiry in cards if expiry > now)
        result["cards"] = (f"重置卡：{len(valid)} 张 · {countdown(valid[0] - now)} 后到期"
                           if valid else "重置卡：无可用卡")
        result["urgent"] = bool(valid and valid[0] - now < 86400)
    if data.get("creditError"):
        result["cards"] = "重置卡：状态未知"
    updated = datetime.fromtimestamp(data["updatedAt"], GMT8).strftime("%H:%M:%S")
    result["status"] = data.get("error") or data.get("creditError") or ("数据已过期" if stale else f"更新于 {updated} · 每分钟刷新")
    return result


def reader_command(cache, home):
    # pythonw has no stdout; use python for the hidden, piped reader child.
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    return [str(executable), str(ROOT / "quota.py"), str(cache), "--home", str(home), "--refresh"]


class Widget:
    def __init__(self, root, home, demo=False):
        self.root, self.home, self.demo = root, home, demo
        self.cache = ROOT / "usage.local.json"
        self.preferences = ROOT / "windows.local.json"
        self.process = None
        self.next_refresh = 0
        self.data = {}
        self.theme = "graphite"
        self.pinned = True
        self.closed = False
        self.mutex = None
        if os.name == "nt" and not demo:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.restype = ctypes.c_void_p
            self.mutex = kernel.CreateMutexW(None, False, "Local\\CodexQuotaWidgetWindows")
            if not self.mutex:
                raise OSError("无法创建应用实例锁")
            if ctypes.get_last_error() == 183:
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                kernel.CloseHandle(self.mutex)
                root.destroy()
                self.closed = True
                return
        root.title("Codex 额度悬浮窗" + (" · 演示" if demo else ""))
        root.resizable(False, False)
        # Tk scales point-size fonts at high DPI, but geometry/padding use pixels.
        scale = root.winfo_fpixels("1i") / 96
        self.scale = scale
        root.geometry(f"{round(390 * scale)}x{round(355 * scale)}+100+100")
        try:
            prefs = {} if demo else json.loads(self.preferences.read_text(encoding="utf-8"))
            self.theme = prefs.get("theme") if prefs.get("theme") in THEMES else self.theme
            x, y = prefs.get("x"), prefs.get("y")
            if (isinstance(x, int) and isinstance(y, int) and
                    0 <= x < root.winfo_screenwidth() - 100 and 0 <= y < root.winfo_screenheight() - 80):
                root.geometry(f"+{x}+{y}")
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        self.container = tk.Frame(root, padx=round(22 * scale), pady=round(15 * scale))
        self.container.pack(fill="both", expand=True)
        self.title = tk.Label(self.container, text="CODEX  /  周期额度", anchor="w", font=("Microsoft YaHei UI", 10, "bold"))
        self.title.pack(fill="x")
        self.percent = tk.Label(self.container, anchor="w", font=("Segoe UI", 42, "bold"))
        self.percent.pack(fill="x")
        self.bar = tk.Canvas(self.container, height=5, highlightthickness=0)
        self.bar.pack(fill="x", pady=(0, 12))
        self.reset = tk.Label(self.container, justify="left", anchor="w", font=("Microsoft YaHei UI", 10))
        self.reset.pack(fill="x")
        self.budget = tk.Label(self.container, anchor="w", font=("Microsoft YaHei UI", 10))
        self.budget.pack(fill="x", pady=(8, 0))
        self.cards = tk.Label(self.container, anchor="w", font=("Microsoft YaHei UI", 9))
        self.cards.pack(fill="x", pady=(6, 0))
        self.status = tk.Label(self.container, anchor="w", justify="left", wraplength=round(345 * scale), font=("Microsoft YaHei UI", 8))
        self.status.pack(fill="x", pady=(8, 0))
        self.controls = tk.Frame(self.container)
        self.controls.pack(side="bottom", fill="x", pady=(10, 0))
        self.refresh_button = self.button("刷新", self.refresh)
        self.pin_button = self.button("置顶 ✓", self.toggle_pin)
        self.button("配色", self.cycle_theme)
        self.button("最小化", root.iconify)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<F5>", lambda event: self.refresh())
        root.bind("<Control-q>", lambda event: self.close())
        root.bind("<Control-t>", lambda event: self.cycle_theme())
        root.bind("<Control-p>", lambda event: self.toggle_pin())
        root.bind("<Control-m>", lambda event: root.iconify())
        self.apply_theme()
        if demo:
            now = time.time()
            self.data = dict(remaining=68, resetsAt=now + 3 * 86400, windowSeconds=604800,
                             updatedAt=now, creditExpiries=[now + 72000])
        else:
            try:
                self.data = quota.read_cache(self.cache, self.home)
            except quota.QuotaError:
                pass
        self.tick()

    def button(self, text, command):
        button = tk.Button(self.controls, text=text, command=command, relief="flat", borderwidth=0,
                           padx=10, pady=4, cursor="hand2", font=("Microsoft YaHei UI", 9))
        button.pack(side="left", padx=(0, 5))
        return button

    def apply_theme(self):
        bg, fg, muted, accent = THEMES[self.theme]
        self.root.configure(bg=bg)
        for widget in (self.container, self.controls, self.bar):
            widget.configure(bg=bg)
        for widget in (self.title, self.percent, self.reset, self.budget, self.cards, self.status):
            widget.configure(bg=bg, fg=fg)
        self.percent.configure(fg=accent)
        self.status.configure(fg=muted)
        for button in self.controls.winfo_children():
            button.configure(bg=bg, fg=fg, activebackground=accent, activeforeground=bg)

    def cycle_theme(self):
        names = list(THEMES)
        self.theme = names[(names.index(self.theme) + 1) % len(names)]
        self.apply_theme()

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self.pin_button.configure(text="置顶 ✓" if self.pinned else "置顶")

    def refresh(self):
        if self.process or self.demo:
            return
        self.next_refresh = time.monotonic() + 60
        try:
            self.process = subprocess.Popen(reader_command(self.cache, self.home), stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.started = time.monotonic()
            self.refresh_button.configure(text="读取中…", state="disabled")
        except OSError:
            self.data = {"error": "无法启动额度读取进程，请检查 Python 安装"}

    def poll_reader(self):
        if not self.process:
            return
        if self.process.poll() is None and time.monotonic() - self.started < 35:
            return
        timed_out = self.process.poll() is None
        if timed_out:
            self.process.kill()
        output, _ = self.process.communicate()
        self.process = None
        self.refresh_button.configure(text="刷新", state="normal")
        try:
            if timed_out:
                raise ValueError()
            value = json.loads(output.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError()
            self.data = value
        except (ValueError, UnicodeError):
            # Revalidate identity before retaining historical data after a failed reader.
            try:
                self.data = quota.read_cache(self.cache, self.home)
            except quota.QuotaError:
                self.data = {}
            self.data["error"] = "读取超时，请重试" if timed_out else "读取失败，请重试"

    def tick(self):
        self.poll_reader()
        if not self.demo and time.monotonic() >= self.next_refresh:
            self.refresh()
        value = presentation(self.data, time.time())
        self.percent.configure(text=value["percent"])
        self.reset.configure(text=value["reset"])
        self.budget.configure(text=value["budget"])
        self.cards.configure(text=value["cards"], fg="#e59a37" if value["urgent"] else THEMES[self.theme][1])
        self.status.configure(text="虚构演示数据 · 不读取账号或联网" if self.demo else value["status"])
        self.bar.delete("all")
        width = max(1, self.bar.winfo_width())
        self.bar.create_rectangle(0, 0, width, 5, fill=THEMES[self.theme][2], outline="")
        self.bar.create_rectangle(0, 0, width * value["remaining"] / 100, 5, fill=THEMES[self.theme][3], outline="")
        self.root.after(250, self.tick)

    def close(self):
        if self.process:
            self.process.kill()
            self.process.communicate()
        if not self.demo:
            try:
                quota.save_cache(self.preferences, dict(theme=self.theme, x=self.root.winfo_x(), y=self.root.winfo_y()))
            except OSError:
                pass
        if self.mutex:
            kernel = ctypes.WinDLL("kernel32")
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self.mutex)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Show synthetic data without reading login/cache or network")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    args = parser.parse_args()
    if os.name == "nt":
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    Widget(root, args.home, args.demo)
    root.mainloop()


if __name__ == "__main__":
    main()
