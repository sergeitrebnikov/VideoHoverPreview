from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path

import win32con
import win32gui
from PIL import Image, ImageTk

from .placement import preview_position
from .winapp import APP_ICO, APP_NAME

_window: tk.Tk | None = None
_label: tk.Label | None = None
_photo: ImageTk.PhotoImage | None = None
_current: Path | None = None
_lock = threading.Lock()


def _apply_icon(window: tk.Tk) -> None:
    if not APP_ICO.is_file():
        return
    try:
        window.iconbitmap(str(APP_ICO))
    except tk.TclError:
        pass


def _ensure_window() -> tuple[tk.Tk, tk.Label]:
    global _window, _label
    if _window is None:
        _window = tk.Tk()
        _window.withdraw()
        _window.title(APP_NAME)
        _apply_icon(_window)
        _window.overrideredirect(True)
        _window.attributes("-topmost", True)
        try:
            _window.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        _window.configure(bg="#202020")
        _window.attributes("-alpha", 0)
        _label = tk.Label(_window, bg="#202020", borderwidth=1, relief="solid")
        _label.pack()
    return _window, _label  # type: ignore[return-value]


def _raise_topmost(window: tk.Tk) -> None:
    try:
        hwnd = window.winfo_id()
        root = win32gui.GetParent(hwnd) or hwnd
        win32gui.SetWindowPos(
            root,
            win32con.HWND_TOPMOST,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
        )
    except Exception:
        pass


def _show_image(img: Image.Image, max_width: int) -> None:
    global _photo
    from . import native_player

    native_player.stop_clip_playback()

    window, label = _ensure_window()
    img = img.convert("RGB")
    w, h = img.size
    if w > max_width:
        ratio = max_width / w
        display_w = max_width
        display_h = max(1, int(h * ratio))
        img = img.resize((display_w, display_h), Image.Resampling.LANCZOS)
    else:
        display_w, display_h = w, h

    _photo = ImageTk.PhotoImage(img)
    label.configure(image=_photo, width=display_w, height=display_h)

    cx, cy = window.winfo_pointerx(), window.winfo_pointery()
    x, y = preview_position(cx, cy, display_w + 2, display_h + 2)
    window.geometry(f"{display_w + 2}x{display_h + 2}+{x}+{y}")
    window.attributes("-alpha", 1)
    window.deiconify()
    window.lift()
    _raise_topmost(window)


def ensure_tk_root() -> tk.Tk:
    return _ensure_window()[0]


def hide_preview() -> None:
    global _current
    with _lock:
        _current = None
        if _window is not None:
            try:
                _window.attributes("-alpha", 0)
                _window.withdraw()
            except tk.TclError:
                pass


def destroy_preview() -> None:
    global _window, _label, _photo, _current
    from . import native_player

    native_player.destroy_native()
    with _lock:
        _current = None
        window = _window
        _window = None
        _label = None
        _photo = None
    if window is not None:
        try:
            window.destroy()
        except tk.TclError:
            pass


def show_image_preview(image_path: Path, max_width: int) -> None:
    global _current
    with _lock:
        if _current == image_path and _window and _window.winfo_viewable():
            return
        _current = image_path
        with Image.open(image_path) as img:
            _show_image(img, max_width)


def pump_tk_events() -> None:
    if _window is None:
        return
    try:
        if not _window.winfo_exists():
            return
        _window.update_idletasks()
        if _current is not None:
            _window.update()
    except tk.TclError:
        pass
