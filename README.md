# FieldLock

FieldLock is a simple multi-monitor lock screen utility for Windows 10 and newer.
It locks each physical screen with a fullscreen window displaying a wallpaper and
requires entering a numeric passcode to unlock.

## Features

- Configurable passcode and wallpaper
- Blocks in-app key combinations like `Alt+F4`
- Proper scaling on window resize
- Works across multiple monitors
- Keypad pops up automatically when you interact with the lock screen
- Smooth keypad shake animation on wrong passcode

## Requirements

- Python 3.11+
- [PySide6](https://pypi.org/project/PySide6/) Qt bindings

Install dependencies with:

```bash
pip install PySide6
```

## Usage

Run the application directly:

```bash
python fieldlock.py
```

A configuration file `config.json` will be created in the same folder on first
run. By default the passcode is `4123`. You can change it through the settings
window or by editing the JSON file.

To create a single-file executable you can use `pyinstaller`:

```bash
pyinstaller --onefile --noconsole fieldlock.py
```

Place a `wallpaper.jpg` next to the executable (or script) to customize the
background image.

## License

This project is provided as-is under the MIT license.
