from __future__ import annotations

import ctypes
import time
from datetime import datetime
from pathlib import Path

import win32api
import win32event
import winerror
from PIL import Image, ImageDraw

APP_NAME = "Video Hover Preview"
APP_AUTHOR = "Требников Сергей"
APP_ID = "VideoHoverPreview.App"
MUTEX_NAME = "Local\\VideoHoverPreview.SingleInstance"

DATA_DIR = Path.home() / ".video-hover-preview"
LOG_PATH = DATA_DIR / "log.txt"
CLIP_DIR = DATA_DIR / "clips"

ROOT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
APP_ICO = ASSETS_DIR / "app.ico"
TRAY_ON_ICO = ASSETS_DIR / "tray-on.ico"
TRAY_OFF_ICO = ASSETS_DIR / "tray-off.ico"

_GREEN = (80, 200, 120, 255)
_RED = (220, 48, 48, 255)
_mutex = None


def log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


def set_app_id() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def set_dpi_aware() -> None:
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def ensure_icons() -> None:
    if APP_ICO.is_file() and TRAY_ON_ICO.is_file() and TRAY_OFF_ICO.is_file():
        return
    write_icon_files()


def acquire_single_instance() -> bool:
    global _mutex
    for _ in range(8):
        handle = win32event.CreateMutex(None, False, MUTEX_NAME)
        if win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS:
            _mutex = handle
            return True
        try:
            win32api.CloseHandle(handle)
        except Exception:
            pass
        time.sleep(0.15)
    return False


def notify_already_running() -> None:
    ctypes.windll.user32.MessageBoxW(
        None,
        f"{APP_NAME} уже запущена.",
        APP_NAME,
        0x40,
    )


def draw_play_icon(size: int, enabled: bool) -> Image.Image:
    color = _GREEN if enabled else _RED
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = max(1, size // 16)
    draw.rounded_rectangle(
        [m, m, size - 1 - m, size - 1 - m],
        radius=max(3, size // 5),
        fill=(30, 30, 30, 255),
    )
    left = size * 0.30
    top = size * 0.24
    bottom = size * 0.76
    right = size * 0.76
    draw.polygon([(left, top), (left, bottom), (right, size * 0.50)], fill=color)
    return img


def load_tray_icon(enabled: bool) -> Image.Image:
    path = TRAY_ON_ICO if enabled else TRAY_OFF_ICO
    try:
        img = Image.open(path).convert("RGBA")
        if img.size != (64, 64):
            img = img.resize((64, 64), Image.Resampling.LANCZOS)
        return img
    except OSError:
        return draw_play_icon(64, enabled)


def write_icon_files() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)]
    on = draw_play_icon(256, True)
    off = draw_play_icon(256, False)
    on.save(APP_ICO, sizes=sizes)
    on.save(TRAY_ON_ICO, sizes=sizes)
    off.save(TRAY_OFF_ICO, sizes=sizes)
