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
    QDateTime,
    QEasingCurve,
)
from PySide6.QtGui import (
    QPixmap,
    QGuiApplication,
    QCloseEvent,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QIcon,
    QFont,
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
    QGraphicsOpacityEffect,
)

APP_NAME = "FieldLock"
EXEC_DIR = Path(sys.argv[0]).resolve().parent
CONFIG_PATH = EXEC_DIR / "config.json"
DEFAULT_PASS = "4123"
DEFAULT_WALL = EXEC_DIR / "wallpaper.png"  # optional neighbouring file
UNLOCK_ICON = EXEC_DIR / "Unlock.png"
SETTINGS_ICON = EXEC_DIR / "Settings.png"

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
        self.setWindowTitle(f"{APP_NAME} – Settings")
        self.cfg = cfg
        self.setModal(True)
        self.build_ui()

    # ----------------------------------------------------------------
    def build_ui(self):
        lay = QVBoxLayout(self)
        
        # 閉じるボタンを右上に配置
        title_row = QHBoxLayout()
        title_row.addStretch(1)
        close_btn = QPushButton("×")
        close_btn.setFixedSize(30, 30)
        close_btn.clicked.connect(self.reject)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 0, 0, 150);
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 0, 0, 200);
            }
        """)
        title_row.addWidget(close_btn)
        lay.addLayout(title_row)

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
        
        # 閉じるボタンを右上に配置
        close_btn = QPushButton("×")
        close_btn.setFixedSize(30, 30)
        close_btn.clicked.connect(self.reject)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 0, 0, 150);
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 0, 0, 200);
            }
        """)
        grid.addWidget(close_btn, 0, 2, alignment=Qt.AlignRight | Qt.AlignTop)
        
        grid.addWidget(QLabel(self.prompt), 0, 0, 1, 2, alignment=Qt.AlignCenter)
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
        self.setMouseTracking(True)
        self.build_ui()
        self.load_wall()
        self.showFullScreen()
        self.installEventFilter(self)  # intercept Alt+F4 etc.

    # ----------------------------------------------------------------
    def build_ui(self):
        self.setStyleSheet("background-color: black;")
        
        # 壁紙ラベルを全画面に設定
        self.wall_lbl = QLabel(self)
        self.wall_lbl.setAlignment(Qt.AlignCenter)
        self.wall_lbl.setStyleSheet("background-color: black;")
        self.wall_lbl.setMouseTracking(True)
        self.wall_lbl.installEventFilter(self)
        
        # 現在時刻ラベル（左下）- 常に表示
        self.time_lbl = QLabel(self)
        self.time_lbl.setStyleSheet("""
            color: white;
            font-size: 64px;
            font-weight: bold;
            background-color: rgba(0, 0, 0, 100);
            padding: 10px;
            border-radius: 10px;
        """)
        # 時刻は常に表示
        
        # アンロックボタン（画面中央下部）
        self.unlock_btn = QPushButton(self)
        if UNLOCK_ICON.exists():
            self.unlock_btn.setIcon(QIcon(str(UNLOCK_ICON)))
        else:
            self.unlock_btn.setText("🔓")
        self.unlock_btn.setIconSize(QSize(64, 64))
        self.unlock_btn.setFixedSize(80, 80)
        self.unlock_btn.clicked.connect(self.request_unlock)
        # hide()を削除 - 代わりにopacityで制御
        self.unlock_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 0, 0, 150);
                border: 2px solid rgba(255, 255, 255, 100);
                border-radius: 40px;
                outline: none;
            }
            QPushButton:hover {
                background-color: rgba(50, 50, 50, 200);
                border: 2px solid rgba(255, 255, 255, 200);
            }
            QPushButton:pressed {
                background-color: rgba(100, 100, 100, 200);
            }
        """)
        
        # 設定ボタン（画面中央下部）
        self.settings_btn = QPushButton(self)
        if SETTINGS_ICON.exists():
            self.settings_btn.setIcon(QIcon(str(SETTINGS_ICON)))
        else:
            self.settings_btn.setIcon(gear_icon())
        self.settings_btn.setIconSize(QSize(64, 64))
        self.settings_btn.setFixedSize(80, 80)
        self.settings_btn.clicked.connect(self.settings)
        # hide()を削除 - 代わりにopacityで制御
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 0, 0, 150);
                border: 2px solid rgba(255, 255, 255, 100);
                border-radius: 40px;
                outline: none;
            }
            QPushButton:hover {
                background-color: rgba(50, 50, 50, 200);
                border: 2px solid rgba(255, 255, 255, 200);
            }
            QPushButton:pressed {
                background-color: rgba(100, 100, 100, 200);
            }
        """)
        
        # ボタンにOpacityエフェクトを追加
        self.unlock_effect = QGraphicsOpacityEffect()
        self.unlock_btn.setGraphicsEffect(self.unlock_effect)
        self.unlock_effect.setOpacity(0.0)  # 初期状態は透明
        
        self.settings_effect = QGraphicsOpacityEffect()
        self.settings_btn.setGraphicsEffect(self.settings_effect)
        self.settings_effect.setOpacity(0.0)  # 初期状態は透明
        
        # フェードアニメーション
        self.unlock_anim = QPropertyAnimation(self.unlock_effect, b"opacity")
        self.unlock_anim.setDuration(500)  # 0.5秒
        self.unlock_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
        self.settings_anim = QPropertyAnimation(self.settings_effect, b"opacity")
        self.settings_anim.setDuration(500)  # 0.5秒
        self.settings_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
        # UIを隠すタイマー（10秒）
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out_ui)
        
        # 時刻更新タイマー（1秒ごと）
        self.time_timer = QTimer(self)
        self.time_timer.timeout.connect(self.update_time)
        self.time_timer.start(1000)
        self.update_time()
        
        # UI状態の管理
        self.ui_visible = False
        
        # ボタンを表示状態にする（透明度で見えないが、クリック可能にする）
        self.unlock_btn.show()
        self.settings_btn.show()

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
        if not hasattr(self, '_orig_wall') or self._orig_wall.isNull():
            return
        size = self.size()
        scaled = self._orig_wall.scaled(
            size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        self.wall_lbl.setPixmap(scaled)

    def update_time(self):
        """現在時刻を更新"""
        current_time = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.time_lbl.setText(current_time)
        self.time_lbl.adjustSize()  # テキストに合わせてサイズを調整

    def show_ui(self):
        """UIコントロールをフェードインで表示"""
        if not self.ui_visible:
            self.ui_visible = True
            # ボタンを確実に表示状態にする
            self.unlock_btn.show()
            self.settings_btn.show()
            
            # フェードイン
            self.unlock_anim.setStartValue(0.0)
            self.unlock_anim.setEndValue(1.0)
            self.unlock_anim.start()
            
            self.settings_anim.setStartValue(0.0)
            self.settings_anim.setEndValue(1.0)
            self.settings_anim.start()
        
        # タイマーリセット
        self.hide_timer.start(10000)  # 10秒後に隠す

    def fade_out_ui(self):
        """UIコントロールをフェードアウトで隠す"""
        if self.ui_visible:
            self.ui_visible = False
            # フェードアウト
            self.unlock_anim.setStartValue(1.0)
            self.unlock_anim.setEndValue(0.0)
            self.unlock_anim.start()
            
            self.settings_anim.setStartValue(1.0)
            self.settings_anim.setEndValue(0.0)
            self.settings_anim.start()

    # ----------------------------------------------------------------
    def resizeEvent(self, _):
        self.rescale()
        # 壁紙ラベルを全画面に設定
        self.wall_lbl.setGeometry(self.rect())
        
        # 時刻ラベルを左下に配置
        self.time_lbl.move(20, self.height() - self.time_lbl.height() - 20)
        
        # ボタンを画面中央下部に配置
        center_x = self.width() // 2
        bottom_y = self.height() - 120
        
        # アンロックボタンを中央左
        self.unlock_btn.move(center_x - 100, bottom_y)
        
        # 設定ボタンを中央右
        self.settings_btn.move(center_x + 20, bottom_y)

    # keep top‑most
    def focusOutEvent(self, _):
        QTimer.singleShot(50, self.raise_)

    # UIを表示
    def mousePressEvent(self, event):
        self.show_ui()
        # ボタンがクリックされた場合の処理（透明度に関係なく）
        if self.unlock_btn.geometry().contains(event.pos()):
            # アンロックボタンがクリックされた
            self.request_unlock()
        elif self.settings_btn.geometry().contains(event.pos()):
            # 設定ボタンがクリックされた
            self.settings()
        else:
            # 画面の何もないところをクリックした場合
            self.request_unlock()

    def mouseMoveEvent(self, _):
        self.show_ui()
        super().mouseMoveEvent(_)

    def keyPressEvent(self, _):
        self.show_ui()

    # guard against Alt+F4
    def closeEvent(self, e: QCloseEvent):
        if not UNLOCKED:
            e.ignore()

    # swallow key combos inside window
    def eventFilter(self, obj, ev: QEvent):
        if obj is self.wall_lbl:
            if ev.type() == QEvent.MouseMove:
                self.show_ui()
            elif ev.type() == QEvent.MouseButtonPress:
                self.show_ui()
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
