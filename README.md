# FieldLock

Multi-monitor lock screen utility for Windows 10+.

## Features

- Multi-monitor support (locks all connected displays)
- Customizable wallpaper and passcode
- Always-visible time display
- 0.5s fade animations for UI elements
- Blocks key combinations (Alt+F4, etc.)
- Auto-hide UI after 10 seconds of inactivity

## Requirements

- Windows 10 or later
- Python 3.11+
- PySide6

```bash
pip install PySide6 Pillow cx_Freeze
```

## Usage

Run from source:
```bash
python fieldlock.py
```

Build executable:
```bash
python setup.py build
```

Default passcode is `4123`. Move mouse or press any key to show unlock/settings buttons.

## Configuration

Settings are stored in `config.json`:
```json
{
  "passcode": "4123",
  "wallpaper_path": "Wallpaper.png",
  "keypad_length": 4
}
```

- Passcode: 4-8 digits
- Wallpaper: PNG, JPG, or BMP format
- Delete config.json to reset to defaults

## Files

```
fieldlock.py          # Main application
setup.py              # Build configuration
AppIcon.png           # Application icon
Settings.png          # Settings button (64x64)
Unlock.png           # Unlock button (64x64)
Wallpaper.png        # Default wallpaper
config.json          # Auto-generated config
```

## Build

```bash
# Development
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Distribution
python setup.py build
# Output: build/exe.win-amd64-3.12/FieldLock.exe
```

## License

MIT
