"""
FieldLock v2.0 — Redesigned multi-monitor lock screen for Windows 10+
=====================================================================
A reliable screen lock application for live event environments.

Features
--------
  * Full-screen lock on all connected displays
  * Customizable wallpaper with smooth aspect-ratio scaling
  * Large centered clock (time + date), always visible
  * Network status bar (IP address, hostname, connection state)
  * Numeric passcode unlock (4-8 digits) with dot indicators
  * Settings panel (wallpaper / passcode) protected by passcode
  * Auto-hiding control bar with fade animations
  * Blocks Alt+F4, Tab, Escape and other escape attempts

Build
-----
  pyinstaller --onefile --noconsole fieldlock.py
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QDateTime,
    QEasingCurve,
    QSize,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# ── Constants ──────────────────────────────────────────────────────

APP_NAME = "FieldLock"

# Resolve resource directory (works for both script and frozen exe)
if getattr(sys, "frozen", False):
    EXEC_DIR = Path(sys.executable).resolve().parent
else:
    EXEC_DIR = Path(sys.argv[0]).resolve().parent

CONFIG_PATH = EXEC_DIR / "config.json"
DEFAULT_PASS = "4123"
DEFAULT_WALL = EXEC_DIR / "Wallpaper.png"
UNLOCK_ICON_PATH = EXEC_DIR / "Unlock.png"
SETTINGS_ICON_PATH = EXEC_DIR / "Settings.png"

UI_FADE_MS = 400  # control bar fade duration
UI_HIDE_DELAY_MS = 8_000  # auto-hide after inactivity
CLOCK_INTERVAL_MS = 1_000  # clock refresh
NET_POLL_MS = 5_000  # network status poll


# ── Network helpers ────────────────────────────────────────────────


def _get_local_ip() -> str:
    """Return the primary LAN IP, or empty string on failure."""
    # UDP connect trick — asks the OS for the outbound interface without
    # actually sending any data.  Works on LANs without internet access.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip != "0.0.0.0":
            return ip
    except Exception:
        pass
    # Fallback
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip != "127.0.0.1":
            return ip
    except Exception:
        pass
    return ""


def _get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


# ── Config ─────────────────────────────────────────────────────────


class Config:
    """Persistent JSON configuration with safe defaults."""

    def __init__(self) -> None:
        self.passcode: str = DEFAULT_PASS
        self.wallpaper_path: str = str(DEFAULT_WALL)
        self.keypad_len: int = len(DEFAULT_PASS)
        self._load()

    def _load(self) -> None:
        try:
            if CONFIG_PATH.exists():
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                self.passcode = str(data.get("passcode", self.passcode))
                wp = data.get("wallpaper_path", self.wallpaper_path)
                p = Path(wp)
                if not p.is_absolute():
                    p = EXEC_DIR / p
                self.wallpaper_path = str(p)
                self.keypad_len = int(
                    data.get("keypad_length", len(self.passcode))
                )
        except Exception:
            pass  # use defaults

    def save(self) -> None:
        wp = Path(self.wallpaper_path)
        try:
            wp_store = str(wp.relative_to(EXEC_DIR))
        except ValueError:
            wp_store = str(wp)
        data = {
            "passcode": self.passcode,
            "wallpaper_path": wp_store,
            "keypad_length": self.keypad_len,
        }
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Keypad dialog ──────────────────────────────────────────────────

_KEYPAD_DOT_FILLED = (
    "color: white; font-size: 24px; border: none; background: transparent;"
)
_KEYPAD_DOT_EMPTY = (
    "color: rgba(255,255,255,100); font-size: 24px;"
    " border: none; background: transparent;"
)
_KEYPAD_BTN = """
    QPushButton {
        background-color: rgba(255, 255, 255, 15);
        color: white;
        border: 1px solid rgba(255, 255, 255, 30);
        border-radius: 28px;
        font-size: 22px;
        font-weight: 500;
    }
    QPushButton:hover { background-color: rgba(255, 255, 255, 30); }
    QPushButton:pressed { background-color: rgba(255, 255, 255, 50); }
"""
_KEYPAD_SPECIAL = """
    QPushButton {
        background-color: rgba(255, 255, 255, 8);
        color: rgba(255, 255, 255, 150);
        border: 1px solid rgba(255, 255, 255, 15);
        border-radius: 28px;
        font-size: 18px;
    }
    QPushButton:hover { background-color: rgba(255, 255, 255, 20); }
    QPushButton:pressed { background-color: rgba(255, 255, 255, 35); }
"""
_KEYPAD_CANCEL = """
    QPushButton {
        background-color: rgba(239, 83, 80, 40);
        color: #EF5350;
        border: 1px solid rgba(239, 83, 80, 60);
        border-radius: 28px;
        font-size: 18px;
    }
    QPushButton:hover { background-color: rgba(239, 83, 80, 80); }
    QPushButton:pressed { background-color: rgba(239, 83, 80, 120); }
"""


class KeypadDialog(QDialog):
    """Numeric keypad with visual dot indicators for passcode entry."""

    def __init__(
        self,
        cfg: Config,
        parent: QWidget | None = None,
        *,
        prompt: str = "Enter passcode",
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Dialog | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.cfg = cfg
        self.buffer: str = ""
        self._prompt_text = prompt
        self._build()
        self.setModal(True)
        self.setFixedWidth(320)

    # ── build ──────────────────────────────────────────────────────

    def _build(self) -> None:
        container = QFrame(self)
        container.setStyleSheet(
            "QFrame { background-color: rgba(24,24,28,240);"
            " border: 1px solid rgba(255,255,255,40);"
            " border-radius: 16px; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        # prompt
        prompt = QLabel(self._prompt_text)
        prompt.setAlignment(Qt.AlignCenter)
        prompt.setStyleSheet(
            "color: rgba(255,255,255,200); font-size: 16px;"
            " border: none; background: transparent;"
        )
        lay.addWidget(prompt)

        # dot indicators
        dots_row = QHBoxLayout()
        dots_row.setAlignment(Qt.AlignCenter)
        dots_row.setSpacing(12)
        self._dots: list[QLabel] = []
        for _ in range(self.cfg.keypad_len):
            dot = QLabel("\u25cb")  # ○
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet(_KEYPAD_DOT_EMPTY)
            self._dots.append(dot)
            dots_row.addWidget(dot)
        lay.addLayout(dots_row)

        # status
        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet(
            "color: #EF5350; font-size: 13px; min-height: 20px;"
            " border: none; background: transparent;"
        )
        lay.addWidget(self._status)

        # number grid
        grid = QGridLayout()
        grid.setSpacing(8)
        btn_size = QSize(56, 56)

        for i in range(1, 10):
            btn = QPushButton(str(i))
            btn.setFixedSize(btn_size)
            btn.setStyleSheet(_KEYPAD_BTN)
            btn.clicked.connect(lambda _, n=i: self._push(n))
            r, c = divmod(i - 1, 3)
            grid.addWidget(btn, r, c, alignment=Qt.AlignCenter)

        # bottom row: backspace · 0 · cancel
        bs = QPushButton("\u232b")  # ⌫
        bs.setFixedSize(btn_size)
        bs.setStyleSheet(_KEYPAD_SPECIAL)
        bs.clicked.connect(self._backspace)
        grid.addWidget(bs, 3, 0, alignment=Qt.AlignCenter)

        z = QPushButton("0")
        z.setFixedSize(btn_size)
        z.setStyleSheet(_KEYPAD_BTN)
        z.clicked.connect(lambda: self._push(0))
        grid.addWidget(z, 3, 1, alignment=Qt.AlignCenter)

        cancel = QPushButton("\u2715")  # ✕
        cancel.setFixedSize(btn_size)
        cancel.setStyleSheet(_KEYPAD_CANCEL)
        cancel.clicked.connect(self.reject)
        grid.addWidget(cancel, 3, 2, alignment=Qt.AlignCenter)

        lay.addLayout(grid)

    # ── helpers ────────────────────────────────────────────────────

    def _sync_dots(self) -> None:
        for i, dot in enumerate(self._dots):
            if i < len(self.buffer):
                dot.setText("\u25cf")  # ●
                dot.setStyleSheet(_KEYPAD_DOT_FILLED)
            else:
                dot.setText("\u25cb")  # ○
                dot.setStyleSheet(_KEYPAD_DOT_EMPTY)

    def _push(self, digit: int) -> None:
        if len(self.buffer) >= self.cfg.keypad_len:
            return
        self.buffer += str(digit)
        self._sync_dots()
        self._status.setText("")
        if len(self.buffer) == self.cfg.keypad_len:
            QTimer.singleShot(120, self._check)

    def _backspace(self) -> None:
        if self.buffer:
            self.buffer = self.buffer[:-1]
            self._sync_dots()
            self._status.setText("")

    def _check(self) -> None:
        if self.buffer == self.cfg.passcode:
            self.accept()
        else:
            self._status.setText("Incorrect passcode")
            self.buffer = ""
            self._sync_dots()
            self._shake()

    def _shake(self) -> None:
        origin = self.pos()
        offsets = [12, -12, 8, -8, 4, -4, 0]
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(len(offsets) * 30)
        for i, dx in enumerate(offsets):
            anim.setKeyValueAt(
                i / (len(offsets) - 1), origin + QPoint(dx, 0)
            )
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._anim = anim  # prevent GC

    # ── keyboard ───────────────────────────────────────────────────

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.text().isdigit():
            self._push(int(e.text()))
        elif e.key() == Qt.Key_Backspace:
            self._backspace()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            if len(self.buffer) == self.cfg.keypad_len:
                self._check()
        elif e.key() == Qt.Key_Escape:
            self.reject()


# ── Settings dialog ────────────────────────────────────────────────

_SETTINGS_LBL = (
    "color: rgba(255,255,255,180); font-size: 13px;"
    " border: none; background: transparent;"
)
_SETTINGS_HEADING = (
    "color: white; font-size: 18px; font-weight: 600;"
    " border: none; background: transparent;"
)
_SETTINGS_INPUT = """
    QLineEdit {
        background-color: rgba(255,255,255,10);
        color: white;
        border: 1px solid rgba(255,255,255,30);
        border-radius: 8px;
        padding: 8px 12px;
        font-size: 14px;
    }
    QLineEdit:focus { border: 1px solid rgba(79,195,247,150); }
"""


class SettingsDialog(QDialog):
    """Configuration dialog for wallpaper and passcode."""

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Dialog | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.cfg = cfg
        self.setModal(True)
        self.setFixedWidth(400)
        self._build()

    def _build(self) -> None:
        container = QFrame(self)
        container.setStyleSheet(
            "QFrame { background-color: rgba(24,24,28,245);"
            " border: 1px solid rgba(255,255,255,40);"
            " border-radius: 16px; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # title bar
        title_row = QHBoxLayout()
        title = QLabel(f"{APP_NAME} Settings")
        title.setStyleSheet(_SETTINGS_HEADING)
        title_row.addWidget(title)
        title_row.addStretch()

        close_btn = QPushButton("\u2715")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton { background-color: rgba(239,83,80,60);"
            " color: #EF5350; border: none; border-radius: 14px;"
            " font-size: 14px; }"
            " QPushButton:hover { background-color: rgba(239,83,80,120); }"
        )
        close_btn.clicked.connect(self.reject)
        title_row.addWidget(close_btn)
        lay.addLayout(title_row)

        # separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(
            "background-color: rgba(255,255,255,20);"
            " max-height: 1px; border: none;"
        )
        lay.addWidget(sep)

        # wallpaper
        lay.addWidget(self._lbl("Wallpaper"))

        wp_row = QHBoxLayout()
        self._wp_name = QLabel(Path(self.cfg.wallpaper_path).name)
        self._wp_name.setStyleSheet(
            "color: rgba(255,255,255,150); font-size: 14px;"
            " border: none; background: transparent;"
        )
        wp_row.addWidget(self._wp_name, 1)

        browse = QPushButton("Browse")
        browse.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,15);"
            " color: white; border: 1px solid rgba(255,255,255,30);"
            " border-radius: 8px; padding: 6px 16px; font-size: 13px; }"
            " QPushButton:hover { background-color: rgba(255,255,255,30); }"
        )
        browse.clicked.connect(self._pick_wallpaper)
        wp_row.addWidget(browse)
        lay.addLayout(wp_row)

        # passcode
        lay.addWidget(self._lbl("Change Passcode (4\u20138 digits)"))

        self._new_pass = QLineEdit()
        self._new_pass.setPlaceholderText("New passcode")
        self._new_pass.setEchoMode(QLineEdit.Password)
        self._new_pass.setStyleSheet(_SETTINGS_INPUT)
        lay.addWidget(self._new_pass)

        self._confirm_pass = QLineEdit()
        self._confirm_pass.setPlaceholderText("Confirm passcode")
        self._confirm_pass.setEchoMode(QLineEdit.Password)
        self._confirm_pass.setStyleSheet(_SETTINGS_INPUT)
        lay.addWidget(self._confirm_pass)

        # action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,10);"
            " color: rgba(255,255,255,150);"
            " border: 1px solid rgba(255,255,255,20);"
            " border-radius: 8px; padding: 8px 20px; font-size: 14px; }"
            " QPushButton:hover { background-color: rgba(255,255,255,20); }"
        )
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        save = QPushButton("Save")
        save.setStyleSheet(
            "QPushButton { background-color: rgba(79,195,247,80);"
            " color: white; border: 1px solid rgba(79,195,247,120);"
            " border-radius: 8px; padding: 8px 24px;"
            " font-size: 14px; font-weight: 600; }"
            " QPushButton:hover { background-color: rgba(79,195,247,120); }"
        )
        save.clicked.connect(self._apply)
        btn_row.addWidget(save)
        lay.addLayout(btn_row)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_SETTINGS_LBL)
        return lbl

    def _pick_wallpaper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Wallpaper",
            str(EXEC_DIR),
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if path:
            self.cfg.wallpaper_path = path
            self._wp_name.setText(Path(path).name)

    def _apply(self) -> None:
        new_p = self._new_pass.text()
        confirm = self._confirm_pass.text()
        if new_p or confirm:
            if new_p != confirm:
                QMessageBox.warning(self, APP_NAME, "Passcodes do not match.")
                return
            if not (4 <= len(new_p) <= 8 and new_p.isdigit()):
                QMessageBox.warning(
                    self, APP_NAME, "Passcode must be 4\u20138 digits."
                )
                return
            self.cfg.passcode = new_p
            self.cfg.keypad_len = len(new_p)
        self.cfg.save()
        self.accept()


# ── Lock window ────────────────────────────────────────────────────


class LockWindow(QWidget):
    """Full-screen lock covering a single physical display."""

    unlocked = Signal()

    def __init__(
        self, cfg: Config, screen, *, is_primary: bool = False
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self._is_primary = is_primary
        self._keypad_open = False
        self._ui_visible = False
        self._allow_close = False

        self.setScreen(screen)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: black;")

        self._build_wallpaper()
        self._build_status_bar()
        self._build_clock()
        self._build_controls()
        self._setup_timers()

        self.installEventFilter(self)
        self.showFullScreen()

    # ── wallpaper ──────────────────────────────────────────────────

    def _build_wallpaper(self) -> None:
        self._wall_lbl = QLabel(self)
        self._wall_lbl.setAlignment(Qt.AlignCenter)
        self._wall_lbl.setStyleSheet("background-color: black;")
        self._wall_lbl.setMouseTracking(True)
        self._wall_lbl.installEventFilter(self)
        self._load_wallpaper()

    def _load_wallpaper(self) -> None:
        path = Path(self.cfg.wallpaper_path)
        pm = QPixmap(str(path)) if path.exists() else QPixmap()
        if pm.isNull():
            pm = QPixmap(1, 1)
            pm.fill(Qt.black)
        self._orig_wall = pm
        self._rescale_wall()

    def _rescale_wall(self) -> None:
        if not hasattr(self, "_orig_wall") or self._orig_wall.isNull():
            return
        scaled = self._orig_wall.scaled(
            self.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self._wall_lbl.setPixmap(scaled)

    # ── status bar (top) ───────────────────────────────────────────

    def _build_status_bar(self) -> None:
        self._status_bar = QWidget(self)
        self._status_bar.setStyleSheet(
            "background-color: rgba(0,0,0,160);"
            " border-bottom: 1px solid rgba(255,255,255,20);"
        )
        self._status_bar.setFixedHeight(36)

        h = QHBoxLayout(self._status_bar)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(8)

        s_lbl = (
            "color: rgba(255,255,255,180); font-size: 13px;"
            " background: transparent; border: none;"
        )
        s_sep = (
            "color: rgba(255,255,255,40); font-size: 13px;"
            " background: transparent; border: none;"
        )

        # network dot
        self._net_dot = QLabel()
        self._net_dot.setFixedSize(10, 10)
        h.addWidget(self._net_dot)

        self._net_lbl = QLabel("Checking\u2026")
        self._net_lbl.setStyleSheet(s_lbl)
        h.addWidget(self._net_lbl)

        h.addWidget(self._sep_lbl(s_sep))

        self._ip_lbl = QLabel("--")
        self._ip_lbl.setStyleSheet(s_lbl)
        h.addWidget(self._ip_lbl)

        h.addWidget(self._sep_lbl(s_sep))

        self._host_lbl = QLabel(_get_hostname() or "--")
        self._host_lbl.setStyleSheet(s_lbl)
        h.addWidget(self._host_lbl)

        h.addStretch()

        app_lbl = QLabel(APP_NAME)
        app_lbl.setStyleSheet(
            "color: rgba(255,255,255,80); font-size: 12px;"
            " background: transparent; border: none;"
        )
        h.addWidget(app_lbl)

    @staticmethod
    def _sep_lbl(style: str) -> QLabel:
        lbl = QLabel("|")
        lbl.setStyleSheet(style)
        return lbl

    # ── clock (center) ─────────────────────────────────────────────

    def _build_clock(self) -> None:
        self._clock_box = QWidget(self)
        self._clock_box.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._clock_box.setStyleSheet("background: transparent;")

        v = QVBoxLayout(self._clock_box)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(4)

        self._time_lbl = QLabel()
        self._time_lbl.setAlignment(Qt.AlignCenter)
        self._time_lbl.setStyleSheet(
            "color: white; font-size: 96px; font-weight: 300;"
            " background: transparent; border: none;"
        )
        v.addWidget(self._time_lbl)

        self._date_lbl = QLabel()
        self._date_lbl.setAlignment(Qt.AlignCenter)
        self._date_lbl.setStyleSheet(
            "color: rgba(255,255,255,160); font-size: 22px; font-weight: 300;"
            " background: transparent; border: none;"
        )
        v.addWidget(self._date_lbl)

    # ── control bar (bottom) ───────────────────────────────────────

    def _build_controls(self) -> None:
        self._ctrl_bar = QWidget(self)
        self._ctrl_bar.setStyleSheet("background: transparent;")
        self._ctrl_bar.setFixedHeight(80)

        h = QHBoxLayout(self._ctrl_bar)
        h.setAlignment(Qt.AlignCenter)
        h.setSpacing(16)

        btn_css = (
            "QPushButton {{ background-color: rgba(0,0,0,160);"
            " color: white; border: 1px solid rgba(255,255,255,60);"
            " border-radius: {r}px; font-size: 14px; padding: 0 20px; }}"
            " QPushButton:hover {{ background-color: rgba(60,60,60,200);"
            " border: 1px solid rgba(255,255,255,120); }}"
            " QPushButton:pressed {{ background-color: rgba(100,100,100,200); }}"
        )

        self._unlock_btn = QPushButton("  Unlock")
        if UNLOCK_ICON_PATH.exists():
            self._unlock_btn.setIcon(QIcon(str(UNLOCK_ICON_PATH)))
            self._unlock_btn.setIconSize(QSize(24, 24))
        self._unlock_btn.setFixedSize(140, 48)
        self._unlock_btn.setStyleSheet(btn_css.format(r=24))
        self._unlock_btn.clicked.connect(self._request_unlock)
        h.addWidget(self._unlock_btn)

        self._settings_btn = QPushButton("  Settings")
        if SETTINGS_ICON_PATH.exists():
            self._settings_btn.setIcon(QIcon(str(SETTINGS_ICON_PATH)))
            self._settings_btn.setIconSize(QSize(24, 24))
        self._settings_btn.setFixedSize(140, 48)
        self._settings_btn.setStyleSheet(btn_css.format(r=24))
        self._settings_btn.clicked.connect(self._open_settings)
        h.addWidget(self._settings_btn)

        # fade effect for entire control bar
        self._ctrl_effect = QGraphicsOpacityEffect()
        self._ctrl_bar.setGraphicsEffect(self._ctrl_effect)
        self._ctrl_effect.setOpacity(0.0)

        self._ctrl_anim = QPropertyAnimation(self._ctrl_effect, b"opacity")
        self._ctrl_anim.setDuration(UI_FADE_MS)
        self._ctrl_anim.setEasingCurve(QEasingCurve.InOutQuad)

    # ── timers ─────────────────────────────────────────────────────

    def _setup_timers(self) -> None:
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(CLOCK_INTERVAL_MS)
        self._tick_clock()

        self._net_timer = QTimer(self)
        self._net_timer.timeout.connect(self._poll_network)
        self._net_timer.start(NET_POLL_MS)
        self._poll_network()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

    def _tick_clock(self) -> None:
        now = QDateTime.currentDateTime()
        self._time_lbl.setText(now.toString("HH:mm:ss"))
        self._date_lbl.setText(now.toString("yyyy/MM/dd  dddd"))

    def _poll_network(self) -> None:
        ip = _get_local_ip()
        connected = bool(ip) and ip != "127.0.0.1"
        if connected:
            self._net_dot.setStyleSheet(
                "background-color: #66BB6A; border-radius: 5px; border: none;"
            )
            self._net_lbl.setText("Connected")
            self._ip_lbl.setText(ip)
        else:
            self._net_dot.setStyleSheet(
                "background-color: #EF5350; border-radius: 5px; border: none;"
            )
            self._net_lbl.setText("No Network")
            self._ip_lbl.setText("--")
        self._host_lbl.setText(_get_hostname() or "--")

    # ── show / hide controls ───────────────────────────────────────

    def _show_ui(self) -> None:
        if not self._ui_visible:
            self._ui_visible = True
            self._ctrl_anim.stop()
            self._ctrl_anim.setStartValue(self._ctrl_effect.opacity())
            self._ctrl_anim.setEndValue(1.0)
            self._ctrl_anim.start()
        self._hide_timer.start(UI_HIDE_DELAY_MS)

    def _fade_out(self) -> None:
        if self._ui_visible and not self._keypad_open:
            self._ui_visible = False
            self._ctrl_anim.stop()
            self._ctrl_anim.setStartValue(self._ctrl_effect.opacity())
            self._ctrl_anim.setEndValue(0.0)
            self._ctrl_anim.start()

    # ── layout on resize ───────────────────────────────────────────

    def resizeEvent(self, _) -> None:
        w, h = self.width(), self.height()
        self._wall_lbl.setGeometry(0, 0, w, h)
        self._rescale_wall()
        self._status_bar.setGeometry(0, 0, w, 36)

        clock_w, clock_h = 500, 160
        self._clock_box.setGeometry(
            (w - clock_w) // 2,
            (h - clock_h) // 2 - 30,
            clock_w,
            clock_h,
        )

        self._ctrl_bar.setGeometry(0, h - 100, w, 80)

    # ── focus / close guards ───────────────────────────────────────

    def focusOutEvent(self, _) -> None:
        if not self._allow_close:
            QTimer.singleShot(50, self.raise_)

    def closeEvent(self, e: QCloseEvent) -> None:
        if not self._allow_close:
            e.ignore()

    # ── input events ───────────────────────────────────────────────

    def mousePressEvent(self, _) -> None:
        self._show_ui()

    def mouseMoveEvent(self, _) -> None:
        self._show_ui()

    def keyPressEvent(self, _) -> None:
        self._show_ui()

    def eventFilter(self, obj, ev: QEvent) -> bool:
        # forward child label events
        if obj is self._wall_lbl:
            if ev.type() in (QEvent.MouseMove, QEvent.MouseButtonPress):
                self._show_ui()
        # block escape key combos
        if ev.type() == QEvent.KeyPress and isinstance(ev, QKeyEvent):
            if ev.key() in (
                Qt.Key_Alt,
                Qt.Key_F4,
                Qt.Key_Tab,
                Qt.Key_Escape,
            ):
                return True
        return super().eventFilter(obj, ev)

    # ── unlock / settings ──────────────────────────────────────────

    def _request_unlock(self) -> None:
        if self._keypad_open:
            return
        self._keypad_open = True
        dlg = KeypadDialog(
            self.cfg, self, prompt="Enter passcode to unlock"
        )
        dlg.adjustSize()
        dlg.move(self.geometry().center() - dlg.rect().center())
        if dlg.exec() == QDialog.Accepted:
            self.unlocked.emit()
        self._keypad_open = False

    def _open_settings(self) -> None:
        if self._keypad_open:
            return
        self._keypad_open = True
        kp = KeypadDialog(
            self.cfg, self, prompt="Enter passcode for settings"
        )
        kp.adjustSize()
        kp.move(self.geometry().center() - kp.rect().center())
        if kp.exec() == QDialog.Accepted:
            sd = SettingsDialog(self.cfg, self)
            sd.adjustSize()
            sd.move(self.geometry().center() - sd.rect().center())
            if sd.exec() == QDialog.Accepted:
                self._load_wallpaper()
        self._keypad_open = False


# ── Application entry ──────────────────────────────────────────────


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    cfg = Config()
    primary = QGuiApplication.primaryScreen()
    windows: list[LockWindow] = []

    def on_unlocked() -> None:
        for w in windows:
            w._allow_close = True
        app.quit()

    for screen in QGuiApplication.screens():
        win = LockWindow(cfg, screen, is_primary=(screen is primary))
        win.unlocked.connect(on_unlocked)
        windows.append(win)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
