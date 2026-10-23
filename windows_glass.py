"""Frameless Windows Acrylic UI; quota requests remain in the isolated reader."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

import quota
from windows_widget import ROOT, presentation, reader_command

PALETTES = {
    "graphite": ("#151d28", "#f4f7fc", "#9caabc", "#9dc8ff", 0xB5281D15),
    "fog": ("#eef3f9", "#192637", "#5d6c80", "#275fa8", 0xBAF9F3EE),
    "apricot": ("#f7eee3", "#392f29", "#7f7064", "#8e5932", 0xBAE3EEF7),
}


def acrylic(hwnd, theme):
    """Apply the native composition material, with an opaque paint fallback."""
    if os.name != "nt":
        return False

    class Accent(ctypes.Structure):
        _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int),
                    ("color", ctypes.c_uint32), ("animation", ctypes.c_int)]

    class Composition(ctypes.Structure):
        _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]

    class Margins(ctypes.Structure):
        _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]

    try:
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
        # Rounded corners, dark/light system material, and a frame extending behind the content.
        for attribute, value in ((33, 2), (20, int(theme == "graphite"))):
            number = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(number), ctypes.sizeof(number))
        dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(Margins(-1, -1, -1, -1)))
        user = ctypes.WinDLL("user32")
        user.SetWindowCompositionAttribute.argtypes = [wintypes.HWND, ctypes.POINTER(Composition)]
        user.SetWindowCompositionAttribute.restype = wintypes.BOOL
        policy = Accent(4, 2, PALETTES[theme][4], 0)  # ACCENT_ENABLE_ACRYLICBLURBEHIND
        settings = Composition(19, ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p), ctypes.sizeof(policy))
        return bool(user.SetWindowCompositionAttribute(hwnd, ctypes.byref(settings)))
    except (OSError, AttributeError):
        return False


class IconButton(QPushButton):
    def __init__(self, kind, tooltip, callback):
        super().__init__()
        self.kind, self.ink = kind, QColor("#9caabc")
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.clicked.connect(callback)
        self.setObjectName("iconButton")

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self.ink, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if self.kind == "close":
            p.drawLine(10, 10, 18, 18)
            p.drawLine(18, 10, 10, 18)
        elif self.kind == "minimize":
            p.drawLine(9, 15, 19, 15)
        elif self.kind == "refresh":
            p.drawArc(QRectF(8, 8, 12, 12), 40 * 16, 280 * 16)
            p.drawLine(19, 8, 19, 12)
            p.drawLine(19, 12, 15, 12)
        elif self.kind == "theme":
            p.drawEllipse(QRectF(8, 8, 12, 12))
            p.setBrush(self.ink)
            p.drawPie(QRectF(8, 8, 12, 12), 90 * 16, 180 * 16)
        elif self.kind == "pin":
            p.drawLine(11, 8, 17, 8)
            p.drawLine(12, 8, 12, 13)
            p.drawLine(16, 8, 16, 13)
            p.drawLine(12, 13, 9, 16)
            p.drawLine(16, 13, 19, 16)
            p.drawLine(9, 16, 19, 16)
            p.drawLine(14, 16, 14, 21)


class GlassWidget(QWidget):
    def __init__(self, home, demo=False):
        super().__init__()
        self.home, self.demo = home, demo
        self.cache, self.preferences = ROOT / "usage.local.json", ROOT / "windows.local.json"
        self.theme, self.pinned, self.material = "graphite", True, False
        self.data, self.process, self.next_refresh = {}, None, 0
        self.mutex = None
        self.setWindowTitle("Codex 额度悬浮窗" + (" · 演示" if demo else ""))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(344, 326)
        self.move(100, 100)
        if not demo:
            try:
                prefs = json.loads(self.preferences.read_text(encoding="utf-8"))
                if prefs.get("theme") in PALETTES:
                    self.theme = prefs["theme"]
                point = (prefs.get("glassX", 100), prefs.get("glassY", 100))
                if all(isinstance(v, int) for v in point):
                    for screen in QApplication.screens():
                        area = screen.availableGeometry()
                        if area.contains(point[0], point[1]) and area.contains(point[0] + 100, point[1] + 80):
                            self.move(*point)
                            break
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            if os.name == "nt":
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.CreateMutexW.restype = ctypes.c_void_p
                self.mutex = kernel.CreateMutexW(None, False, "Local\\CodexQuotaWidgetWindows")
                if not self.mutex:
                    raise OSError("无法创建应用实例锁")
                if ctypes.get_last_error() == 183:
                    self.release_mutex()
                    self.duplicate = True
                    return
        self.duplicate = False
        self.build_ui()
        for keys, callback in (("F5", self.refresh), ("Ctrl+T", self.cycle_theme),
                               ("Ctrl+P", self.toggle_pin), ("Ctrl+M", self.showMinimized),
                               ("Ctrl+Q", self.close)):
            QShortcut(QKeySequence(keys), self, activated=callback)
        if demo:
            now = time.time()
            self.data = dict(remaining=68, resetsAt=now + 3 * 86400, windowSeconds=604800,
                             updatedAt=now, creditExpiries=[now + 72000])
        else:
            try:
                self.data = quota.read_cache(self.cache, self.home)
            except quota.QuotaError:
                pass
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)
        self.apply_theme()
        self.tick()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setSpacing(2)
        self.brand = QLabel("◈  CODEX")
        self.brand.setObjectName("brand")
        header.addWidget(self.brand)
        header.addStretch()
        self.buttons = []
        for kind, tip, callback in (("pin", "取消置顶 · Ctrl+P", self.toggle_pin),
                                     ("theme", "切换配色 · Ctrl+T", self.cycle_theme),
                                     ("minimize", "最小化 · Ctrl+M", self.showMinimized),
                                     ("close", "退出 · Ctrl+Q", self.close)):
            button = IconButton(kind, tip, callback)
            header.addWidget(button)
            self.buttons.append(button)
        layout.addLayout(header)
        layout.addSpacing(17)
        hero = QHBoxLayout()
        hero.setSpacing(9)
        self.percent = QLabel("—")
        self.percent.setObjectName("percent")
        hero.addWidget(self.percent)
        subtitle = QLabel("剩余\n周期额度")
        subtitle.setObjectName("subtitle")
        hero.addWidget(subtitle, alignment=Qt.AlignmentFlag.AlignBottom)
        hero.addStretch()
        layout.addLayout(hero)
        layout.addSpacing(11)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        layout.addWidget(self.bar)
        layout.addSpacing(20)
        metrics = QHBoxLayout()
        metrics.setSpacing(22)
        reset_column = QVBoxLayout()
        reset_column.setSpacing(5)
        reset_title = QLabel("下次重置")
        reset_title.setObjectName("eyebrow")
        self.reset = QLabel("等待数据")
        self.reset.setObjectName("metric")
        self.date = QLabel("")
        self.date.setObjectName("detail")
        reset_column.addWidget(reset_title)
        reset_column.addWidget(self.reset)
        reset_column.addWidget(self.date)
        metrics.addLayout(reset_column, 3)
        budget_column = QVBoxLayout()
        budget_column.setSpacing(5)
        budget_title = QLabel("日均预算")
        budget_title.setObjectName("eyebrow")
        self.budget = QLabel("—")
        self.budget.setObjectName("metric")
        budget_detail = QLabel("按重置时间估算")
        budget_detail.setObjectName("detail")
        budget_column.addWidget(budget_title)
        budget_column.addWidget(self.budget)
        budget_column.addWidget(budget_detail)
        metrics.addLayout(budget_column, 2)
        layout.addLayout(metrics)
        layout.addSpacing(17)
        self.divider = QWidget()
        self.divider.setObjectName("divider")
        self.divider.setFixedHeight(1)
        layout.addWidget(self.divider)
        layout.addSpacing(12)
        self.cards = QLabel("重置卡  ·  状态未知")
        self.cards.setObjectName("cards")
        layout.addWidget(self.cards)
        layout.addStretch()
        footer = QHBoxLayout()
        self.status = QLabel("连接中…")
        self.status.setObjectName("detail")
        footer.addWidget(self.status, 1)
        self.refresh_button = IconButton("refresh", "刷新额度 · F5", self.refresh)
        self.buttons.append(self.refresh_button)
        footer.addWidget(self.refresh_button)
        layout.addLayout(footer)
        # A real application icon also makes the frameless window easy to restore.
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#182435"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, 64, 64, 15, 15)
        p.setPen(QPen(QColor("#9dc8ff"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(15, 15, 34, 34), 45 * 16, 285 * 16)
        p.end()
        self.setWindowIcon(QIcon(pixmap))

    def apply_theme(self):
        bg, fg, muted, accent, _ = PALETTES[self.theme]
        self.setStyleSheet(f"""
            QWidget {{ color: {fg}; font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 11px; background: transparent; }}
            QLabel#brand {{ font-size: 11px; font-weight: 600; letter-spacing: 2px; }}
            QLabel#percent {{ font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 58px; font-weight: 600; letter-spacing: -3px; }}
            QLabel#subtitle {{ color: {muted}; font-size: 11px; padding-bottom: 10px; line-height: 18px; }}
            QLabel#eyebrow {{ color: {muted}; font-size: 11px; }}
            QLabel#metric {{ font-size: 16px; font-weight: 600; }}
            QLabel#detail {{ color: {muted}; font-size: 10px; }}
            QLabel#cards {{ font-size: 11px; }}
            QWidget#divider {{ background: {'rgba(255,255,255,22)' if self.theme == 'graphite' else 'rgba(0,0,0,22)'}; }}
            QPushButton#iconButton {{ border: none; border-radius: 7px; padding: 0; }}
            QPushButton#iconButton:hover {{ background: {'rgba(255,255,255,20)' if self.theme == 'graphite' else 'rgba(0,0,0,15)'}; }}
            QPushButton#iconButton:pressed {{ background: rgba(128,128,128,45); }}
            QProgressBar {{ border: none; border-radius: 2px; background: {'rgba(255,255,255,25)' if self.theme == 'graphite' else 'rgba(0,0,0,22)'}; }}
            QProgressBar::chunk {{ border-radius: 2px; background: {accent}; }}
            QToolTip {{ color: {fg}; background: {bg}; border: 1px solid {muted}; padding: 5px; }}
        """)
        for button in self.buttons:
            button.ink = QColor(accent if button.kind == "pin" and self.pinned else muted)
            button.update()
        self.material = acrylic(int(self.winId()), self.theme)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        fill = QColor(PALETTES[self.theme][0])
        fill.setAlpha(38 if self.material else 248)
        p.setBrush(fill)
        p.setPen(QPen(QColor(255, 255, 255, 32 if self.theme == "graphite" else 150), 1))
        p.drawRoundedRect(rect, 14, 14)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.apply_theme)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.windowHandle().startSystemMove()

    def cycle_theme(self):
        names = list(PALETTES)
        self.theme = names[(names.index(self.theme) + 1) % len(names)]
        self.apply_theme()

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.pinned)
        self.show()
        self.buttons[0].setToolTip(("取消置顶" if self.pinned else "置顶") + " · Ctrl+P")
        self.apply_theme()

    def refresh(self):
        if self.process or self.demo:
            return
        self.next_refresh = time.monotonic() + 60
        try:
            self.process = subprocess.Popen(reader_command(self.cache, self.home), stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.started = time.monotonic()
            self.refresh_button.setEnabled(False)
        except OSError:
            self.data = {"error": "无法启动读取进程"}

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
        self.refresh_button.setEnabled(True)
        try:
            if timed_out:
                raise ValueError()
            value = json.loads(output.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError()
            self.data = value
        except (ValueError, UnicodeError):
            try:
                self.data = quota.read_cache(self.cache, self.home)
            except quota.QuotaError:
                self.data = {}
            self.data["error"] = "读取超时，请重试" if timed_out else "读取失败，请重试"

    def tick(self):
        self.poll_reader()
        if not self.demo and time.monotonic() >= self.next_refresh:
            self.refresh()
        if self.demo:
            self.data["updatedAt"] = time.time()
        value = presentation(self.data, time.time())
        self.percent.setText(value["percent"])
        self.bar.setValue(round(value["remaining"] * 10))
        reset, _, date = value["reset"].partition("\n")
        self.reset.setText(reset.removeprefix("距重置  "))
        self.date.setText(date)
        budget = value["budget"]
        self.budget.setText(budget.removeprefix("日均可用预算  ") if budget.startswith("日均") else "—")
        self.budget.setToolTip(budget)
        self.cards.setText(value["cards"].replace("重置卡：", "重置卡  ·  "))
        warning = "#e9b16e" if self.theme == "graphite" else "#925216"
        self.cards.setStyleSheet(f"color: {warning};" if value["urgent"] else "")
        status = "演示数据 · 离线预览" if self.demo else value["status"]
        if self.process:
            status = "正在刷新…"
        self.status.setText(self.status.fontMetrics().elidedText(status, Qt.TextElideMode.ElideRight, 260))
        self.status.setToolTip(status)

    def release_mutex(self):
        if self.mutex:
            kernel = ctypes.WinDLL("kernel32")
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self.mutex)
            self.mutex = None

    def closeEvent(self, event):
        self.timer.stop()
        if self.process:
            self.process.kill()
            self.process.communicate()
            self.process = None
        if not self.demo:
            try:
                prefs = json.loads(self.preferences.read_text(encoding="utf-8")) if self.preferences.exists() else {}
            except (OSError, ValueError):
                prefs = {}
            if not isinstance(prefs, dict):
                prefs = {}
            prefs.update(theme=self.theme, glassX=self.x(), glassY=self.y())
            try:
                quota.save_cache(self.preferences, prefs)
            except OSError:
                pass
        self.release_mutex()
        event.accept()


def run(home, demo=False):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("CodexQuotaWidget")
    app.setFont(QFont("Segoe UI", 9))
    widget = GlassWidget(home, demo)
    if widget.duplicate:
        return
    widget.show()
    app.exec()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    args = parser.parse_args()
    run(args.home, args.demo)
