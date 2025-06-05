"""
FieldLock — Simple multi‑monitor lock screen for Windows 10+
Refactored May 2025
-----------------------------------------------------------
Highlights compared with v1.0
• clearer structure: Config / UI / helpers are isolated
• event‑filter blocks in‑app key combos (Alt+F4 …)
• resize‑aware wallpaper scaling
• unlock‑flag prevents unintended close()
• input buffer capped to passcode length
• config + resources resolved relative to the exe folder

Build one‑file exe:  pyinstaller --onefile --noconsole fieldlock.py
"""
from __future__ import annotations

import json
import sys
import math
from pathlib import Path
from typing import List

from PySide6.QtCore import (
    Qt,
    QTimer,
    QSize,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QPointF,
)
from PySide6.QtGui import (
    QPixmap,
    QGuiApplication,
    QCloseEvent,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QDialog,
    QFileDialog,
    QGridLayout,
    QMessageBox,
    QLineEdit,
)

APP_NAME = "FieldLock"
EXEC_DIR = Path(sys.argv[0]).resolve().parent
CONFIG_PATH = EXEC_DIR / "config.json"
DEFAULT_PASS = "4123"
DEFAULT_WALL = EXEC_DIR / "wallpaper.png"  # optional neighbouring file

# global flag to allow all windows to close once passcode is verified
UNLOCKED = False


def gear_icon(size: int = 64) -> QIcon:
    """Generate a simple black gear icon."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    center = QPointF(size / 2, size / 2)
    teeth = 8
    outer = size * 0.45
    inner = size * 0.32
    path = QPainterPath()
    for i in range(teeth * 2):
        ang = math.pi * i / teeth
        r = outer if i % 2 == 0 else inner
        x = center.x() + r * math.cos(ang)
        y = center.y() + r * math.sin(ang)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.fillPath(path, Qt.black)
    painter.setCompositionMode(QPainter.CompositionMode_Clear)
    painter.drawEllipse(center, size * 0.18, size * 0.18)
    painter.end()
    return QIcon(pm)


# --------------------------------------------------------------------
#                             Config helper
# --------------------------------------------------------------------
class Config:
    """Tiny JSON wrapper with sane defaults."""

    def __init__(self):
        self.passcode: str = DEFAULT_PASS
        self.wallpaper_path: str = str(DEFAULT_WALL)
        self.keypad_len: int = 4
        self._load()

    # ----------------------------------------------------------------
    def _load(self):
        try:
            if CONFIG_PATH.exists():
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                self.passcode = str(data.get("passcode", self.passcode))
                self.wallpaper_path = data.get("wallpaper_path", self.wallpaper_path)
                self.keypad_len = int(data.get("keypad_length", self.keypad_len))
        except Exception as e:
            print(f"Config load failed → defaults ({e})")

    # ----------------------------------------------------------------
    def save(self):
        data = {
            "passcode": self.passcode,
            "wallpaper_path": self.wallpaper_path,
            "keypad_length": self.keypad_len,
        }
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --------------------------------------------------------------------
#                           Settings dialogue
# --------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} – Settings")
        self.cfg = cfg
        self.setModal(True)
        self.build_ui()

    # ----------------------------------------------------------------
    def build_ui(self):
        lay = QVBoxLayout(self)

        # wallpaper
        lay.addWidget(QLabel("Current wallpaper:"))
        wp_row = QHBoxLayout()
        self.wp_lbl = QLabel(Path(self.cfg.wallpaper_path).name)
        pick_btn = QPushButton("Browse…")
        pick_btn.clicked.connect(self.pick_wall)
        wp_row.addWidget(self.wp_lbl)
        wp_row.addWidget(pick_btn)
        wp_row.addStretch(1)
        lay.addLayout(wp_row)

        # passcode
        lay.addWidget(QLabel("Change passcode (4‑8 digits):"))
        self.new_edit = QLineEdit()
        self.new2_edit = QLineEdit()
        for e in (self.new_edit, self.new2_edit):
            e.setEchoMode(QLineEdit.Password)
        lay.addWidget(QLabel("New:"))
        lay.addWidget(self.new_edit)
        lay.addWidget(QLabel("Confirm:"))
        lay.addWidget(self.new2_edit)

        # buttons
        btn_row = QHBoxLayout()
        save = QPushButton("Save")
        cancel = QPushButton("Cancel")
        save.clicked.connect(self.apply)
        cancel.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(save)
        btn_row.addWidget(cancel)
        lay.addLayout(btn_row)

    # ----------------------------------------------------------------
    def pick_wall(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Wallpaper", str(EXEC_DIR), "Images (*.png *.jpg *.bmp)")
        if path:
            self.cfg.wallpaper_path = path
            self.wp_lbl.setText(Path(path).name)

    # ----------------------------------------------------------------
    def apply(self):
        if any((self.new_edit.text(), self.new2_edit.text())):
            if self.new_edit.text() != self.new2_edit.text():
                QMessageBox.warning(self, APP_NAME, "New passcode mismatch.")
                return
            if not (4 <= len(self.new_edit.text()) <= 8 and self.new_edit.text().isdigit()):
                QMessageBox.warning(self, APP_NAME, "Passcode must be 4–8 digits.")
                return
            self.cfg.passcode = self.new_edit.text()
            self.cfg.keypad_len = len(self.cfg.passcode)
        self.cfg.save()
        self.accept()


# --------------------------------------------------------------------
#                            Keypad dialogue
# --------------------------------------------------------------------
class KeypadDialog(QDialog):
    def __init__(self, cfg: Config, parent: QWidget | None = None, *, prompt: str = "Enter passcode to unlock"):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.cfg = cfg
        self.buffer = ""
        self.prompt = prompt
        self.build_ui()
        self.setModal(True)

    # ----------------------------------------------------------------
    def build_ui(self):
        grid = QGridLayout(self)
        grid.addWidget(QLabel(self.prompt), 0, 0, 1, 3, alignment=Qt.AlignCenter)
        # digits
        positions = [
            (1, 0), (1, 1), (1, 2),
            (2, 0), (2, 1), (2, 2),
            (3, 0), (3, 1), (3, 2),
            (4, 1),
        ]
        for num in range(10):
            r, c = positions[num]
            btn = QPushButton(str(num))
            btn.setFixedSize(QSize(80, 80))
            btn.clicked.connect(lambda _, n=num: self.push(n))
            grid.addWidget(btn, r, c)
        self.status_lbl = QLabel(" ")
        grid.addWidget(self.status_lbl, 5, 0, 1, 3, alignment=Qt.AlignCenter)

    # ----------------------------------------------------------------
    def push(self, digit: int):
        if len(self.buffer) >= self.cfg.keypad_len:
            return
        self.buffer += str(digit)
        if len(self.buffer) == self.cfg.keypad_len:
            self.check()

    # ----------------------------------------------------------------
    def keyPressEvent(self, e: QKeyEvent):
        if e.text().isdigit():
            self.push(int(e.text()))
        elif e.key() == Qt.Key_Backspace:
            self.buffer = self.buffer[:-1]
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            if len(self.buffer) == self.cfg.keypad_len:
                self.check()
        # ignore others

    # ----------------------------------------------------------------
    def check(self):
        if self.buffer == self.cfg.passcode:
            self.accept()
        else:
            self.status_lbl.setText("Incorrect")
            self.buffer = ""
            self.shake()

    def shake(self):
        orig = self.pos()
        sequence = [10, -10, 6, -6, 3, -3, 0]
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(len(sequence) * 20)
        for i, off in enumerate(sequence):
            anim.setKeyValueAt(i / (len(sequence) - 1), orig + QPoint(off, 0))
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._anim = anim  # keep reference


# --------------------------------------------------------------------
#                            Lock window
# --------------------------------------------------------------------
class LockWindow(QWidget):
    """One window per physical screen."""

    def __init__(self, cfg: Config, screen, primary: bool):
        super().__init__()
        self.cfg = cfg
        self.primary = primary
        self.keypad_open = False
        self.setScreen(screen)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.showFullScreen()
        self.setMouseTracking(True)
        self.build_ui()
        self.load_wall()
        self.installEventFilter(self)  # intercept Alt+F4 etc.

    # ----------------------------------------------------------------
    def build_ui(self):
        self.setStyleSheet("background-color: black;")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.wall_lbl = QLabel(alignment=Qt.AlignCenter)
        self.wall_lbl.setStyleSheet("background-color: black;")
        self.wall_lbl.setMouseTracking(True)
        self.wall_lbl.installEventFilter(self)
        v.addWidget(self.wall_lbl, 1)
        self.settings_btn = QPushButton()
        self.settings_btn.setIcon(gear_icon())
        self.settings_btn.setIconSize(QSize(80, 80))
        self.settings_btn.setFixedSize(100, 100)
        self.settings_btn.clicked.connect(self.settings)
        self.settings_btn.hide()
        v.addWidget(self.settings_btn, alignment=Qt.AlignHCenter | Qt.AlignBottom)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.settings_btn.hide)

    # ----------------------------------------------------------------
    def load_wall(self):
        path = Path(self.cfg.wallpaper_path)
        pm = QPixmap(str(path)) if path.exists() else QPixmap()
        if pm.isNull():
            pm = QPixmap(1, 1)
            pm.fill(Qt.black)
        self._orig_wall = pm
        self.rescale()

    def rescale(self):
        if self._orig_wall.isNull():
            return
        size = self.screen().geometry().size()
        scaled = self._orig_wall.scaled(
            size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        self.wall_lbl.setPixmap(scaled)
        self.wall_lbl.setFixedSize(size)

    # ----------------------------------------------------------------
    def resizeEvent(self, _):
        self.rescale()

    # keep top‑most
    def focusOutEvent(self, _):
        QTimer.singleShot(50, self.raise_)

    # open keypad on any interaction
    def mousePressEvent(self, _):
        self.request_unlock()

    def mouseMoveEvent(self, _):
        self.settings_btn.show()
        self.hide_timer.start(2000)
        super().mouseMoveEvent(_)

    def keyPressEvent(self, _):
        self.request_unlock()

    # guard against Alt+F4
    def closeEvent(self, e: QCloseEvent):
        if not UNLOCKED:
            e.ignore()

    # swallow key combos inside window
    def eventFilter(self, obj, ev: QEvent):
        if obj is self.wall_lbl:
            if ev.type() == QEvent.MouseMove:
                self.settings_btn.show()
                self.hide_timer.start(2000)
            elif ev.type() == QEvent.MouseButtonPress:
                self.request_unlock()
        if ev.type() == QEvent.KeyPress and isinstance(ev, QKeyEvent):
            key = ev.key()
            if key in (Qt.Key_Alt, Qt.Key_F4, Qt.Key_Tab, Qt.Key_Escape):
                return True  # block
        return super().eventFilter(obj, ev)

    # ----------------------------------------------------------------
    def unlock(self):
        if self.keypad_open:
            return
        self.keypad_open = True
        dlg = KeypadDialog(self.cfg, self)
        dlg.adjustSize()
        # center on this window
        dlg.move(self.geometry().center() - dlg.rect().center())
        if dlg.exec() == QDialog.Accepted:
            global UNLOCKED
            UNLOCKED = True
            QApplication.quit()
        self.keypad_open = False

    def request_unlock(self):
        # show keypad immediately upon interaction
        if not self.keypad_open:
            self.unlock()

    def settings(self):
        if self.keypad_open:
            return
        self.keypad_open = True
        kp = KeypadDialog(self.cfg, self, prompt="Enter passcode to change settings")
        kp.adjustSize()
        kp.move(self.geometry().center() - kp.rect().center())
        if kp.exec() == QDialog.Accepted:
            dlg = SettingsDialog(self.cfg, self)
            if dlg.exec() == QDialog.Accepted:
                self.load_wall()
        self.keypad_open = False


# --------------------------------------------------------------------
#                                 main
# --------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    cfg = Config()

    primary = QGuiApplication.primaryScreen()
    windows: List[LockWindow] = []
    for sc in QGuiApplication.screens():
        win = LockWindow(cfg, sc, sc == primary)
        windows.append(win)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
