from cx_Freeze import setup, Executable
import sys

# GUI application option
base = None
if sys.platform == "win32":
    base = "Win32GUI"

# Include additional files
include_files = [
    "Settings.png",
    "Unlock.png", 
    "Wallpaper.png",
    "AppIcon.png",
    "fieldlock.ico"
]

# Setup
setup(
    name="FieldLock",
    version="1.0",
    description="Simple multi-monitor lock screen for Windows",
    options={
        "build_exe": {
            "packages": ["PySide6"],
            "include_files": include_files,
            "excludes": ["tkinter"],
        }
    },
    executables=[
        Executable(
            "fieldlock.py",
            base=base,
            icon="fieldlock.ico",
            target_name="FieldLock.exe"
        )
    ]
) 