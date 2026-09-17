from __future__ import annotations

import ctypes
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path

import win32api
import win32con
import win32gui
from PIL import Image

from .placement import preview_position
from .winapp import APP_ICO, APP_NAME

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = win32con.WS_EX_TOOLWINDOW
_TOPMOST_FLAGS = (
    win32con.SWP_NOMOVE
    | win32con.SWP_NOSIZE
    | win32con.SWP_NOACTIVATE
    | win32con.SWP_SHOWWINDOW
)

_gdi32 = ctypes.windll.gdi32
_kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


_hwnd: int | None = None
_class_atom: int | None = None
_lock = threading.Lock()
_clip_thread: threading.Thread | None = None
_clip_proc: subprocess.Popen | None = None
_audio_proc: subprocess.Popen | None = None
_session_stop: threading.Event | None = None
_session_id = 0
_playing = False
_anchor: tuple[int, int] | None = None


def _wnd_proc(hwnd, msg, wparam, lparam):
    # Мышь проходит сквозь превью — иначе WindowFromPoint/UIA
    # думают, что курсор уже не на файле, и превью сразу закрывается.
    if msg == win32con.WM_NCHITTEST:
        return win32con.HTTRANSPARENT
    if msg == win32con.WM_DESTROY:
        return 0
    if msg == win32con.WM_PAINT:
        win32gui.BeginPaint(hwnd)
        win32gui.EndPaint(hwnd)
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def _load_app_icon():
    if not APP_ICO.is_file():
        return 0
    try:
        return win32gui.LoadImage(
            0,
            str(APP_ICO),
            win32con.IMAGE_ICON,
            0,
            0,
            win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE,
        )
    except Exception:
        return 0


def _ensure_class() -> None:
    global _class_atom
    if _class_atom:
        return
    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc = _wnd_proc
    wc.lpszClassName = "VideoHoverPreviewNative"
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    wc.hbrBackground = win32gui.GetStockObject(win32con.BLACK_BRUSH)
    icon = _load_app_icon()
    if icon:
        wc.hIcon = icon
    try:
        _class_atom = win32gui.RegisterClass(wc)
    except win32gui.error:
        _class_atom = 1


def _hide_hwnd(hwnd: int | None) -> None:
    if not hwnd:
        return
    try:
        if win32gui.IsWindow(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
    except Exception:
        pass


def _hide_all_preview_windows() -> None:
    found: list[int] = []

    def _enum(hwnd, _):
        try:
            if win32gui.GetClassName(hwnd) == "VideoHoverPreviewNative":
                found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_enum, None)
    except Exception:
        return
    for hwnd in found:
        _hide_hwnd(hwnd)


def _destroy_hwnd_owned(hwnd: int | None) -> None:
    if not hwnd:
        return
    try:
        if win32gui.IsWindow(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            win32gui.DestroyWindow(hwnd)
    except Exception:
        pass


def _topmost(hwnd: int) -> None:
    try:
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            0,
            0,
            0,
            0,
            _TOPMOST_FLAGS,
        )
    except Exception:
        pass


def _ensure_window(width: int, height: int) -> int:
    global _hwnd, _anchor
    _ensure_class()

    if _anchor is None:
        try:
            cx, cy = win32gui.GetCursorPos()
        except Exception:
            cx, cy = 100, 100
        _anchor = preview_position(cx, cy, width, height)
    x, y = _anchor

    old = _hwnd
    if old and win32gui.IsWindow(old):
        _hide_hwnd(old)

    hwnd = win32gui.CreateWindowEx(
        win32con.WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | win32con.WS_EX_LAYERED,
        "VideoHoverPreviewNative",
        APP_NAME,
        win32con.WS_POPUP,
        x,
        y,
        width,
        height,
        0,
        0,
        win32api.GetModuleHandle(None),
        None,
    )
    win32gui.SetLayeredWindowAttributes(hwnd, 0, 255, win32con.LWA_ALPHA)
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
    _topmost(hwnd)
    with _lock:
        _hwnd = hwnd
    return hwnd


def _blit_rgb(hwnd: int, rgb: bytes, width: int, height: int) -> None:
    img = Image.frombytes("RGB", (width, height), rgb)
    bgr = img.tobytes("raw", "BGR")
    row = width * 3
    flipped = b"".join(bgr[i : i + row] for i in range((height - 1) * row, -1, -row))

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 24
    bmi.bmiHeader.biCompression = 0
    bmi.bmiHeader.biSizeImage = len(flipped)

    hdc = win32gui.GetDC(hwnd)
    try:
        _gdi32.StretchDIBits(
            hdc,
            0,
            0,
            width,
            height,
            0,
            0,
            width,
            height,
            flipped,
            ctypes.byref(bmi),
            win32con.DIB_RGB_COLORS,
            win32con.SRCCOPY,
        )
    finally:
        win32gui.ReleaseDC(hwnd, hdc)


def _probe_wh(ffprobe: Path, clip: Path) -> tuple[int, int] | None:
    try:
        out = (
            subprocess.check_output(
                [
                    str(ffprobe),
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "csv=p=0:s=x",
                    str(clip),
                ],
                creationflags=CREATE_NO_WINDOW,
                timeout=3,
            )
            .decode("utf-8", errors="replace")
            .strip()
        )
        w_s, h_s = out.split("x")
        w, h = int(w_s), int(h_s)
        if w > 0 and h > 0:
            return w, h
    except Exception:
        return None
    return None


def _read_exact(stream, size: int) -> bytes | None:
    chunks: list[bytes] = []
    left = size
    while left > 0:
        chunk = stream.read(left)
        if not chunk:
            return None
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def _exe_path(pid: int) -> str:
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(32768)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def _kill_pid(pid: int) -> None:
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, int(pid))
        try:
            win32api.TerminateProcess(handle, 1)
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        pass


def kill_runtime_players() -> None:
    """Сразу гасит окно превью и все ffmpeg/ffplay из runtime (без WMI)."""
    _hide_all_preview_windows()
    bin_dir = str((Path(__file__).resolve().parents[1] / "runtime" / "ffmpeg" / "bin")).lower().replace("/", "\\")
    try:
        import win32process

        pids = win32process.EnumProcesses()
    except Exception:
        return
    for pid in pids:
        if not pid:
            continue
        path = _exe_path(pid).lower().replace("/", "\\")
        if not path:
            continue
        name = Path(path).name
        if name not in {"ffmpeg.exe", "ffplay.exe"}:
            continue
        if bin_dir in path:
            _kill_pid(pid)


def _stop_audio() -> None:
    global _audio_proc
    proc = _audio_proc
    _audio_proc = None
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=0.4)
        except Exception:
            pass


def _start_audio(ffplay: Path, clip: Path, volume: int) -> None:
    global _audio_proc
    _stop_audio()
    vol = max(0, min(100, int(volume)))
    try:
        _audio_proc = subprocess.Popen(
            [
                str(ffplay),
                "-nodisp",
                "-vn",
                "-loop", "0",
                "-volume", str(vol),
                "-loglevel", "quiet",
                str(clip),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError:
        _audio_proc = None


def _clip_reader(
    ffmpeg: Path,
    ffprobe: Path | None,
    clip: Path,
    max_width: int,
    stop_event: threading.Event,
    session_id: int,
    sound_enabled: bool,
    volume: int,
    ffplay: Path | None,
) -> None:
    global _clip_proc, _playing, _hwnd

    wh = _probe_wh(ffprobe, clip) if ffprobe else None
    if wh:
        src_w, src_h = wh
        if src_w > max_width:
            display_w = max_width - (max_width % 4)
            display_h = max(2, int(src_h * (display_w / src_w)))
            if display_h % 2:
                display_h -= 1
        else:
            display_w = src_w - (src_w % 4)
            display_h = src_h - (src_h % 2)
    else:
        display_w = max_width - (max_width % 4)
        display_h = max(2, int(display_w * 9 / 16))
        if display_h % 2:
            display_h -= 1
    display_w = max(4, display_w)
    display_h = max(2, display_h)

    if stop_event.is_set() or session_id != _session_id:
        return

    frame_bytes = display_w * display_h * 3
    hwnd = None
    try:
        hwnd = _ensure_window(display_w, display_h)
        _playing = True
        if sound_enabled and ffplay is not None:
            _start_audio(ffplay, clip, volume)

        while not stop_event.is_set() and session_id == _session_id:
            if sound_enabled and ffplay is not None and (
                _audio_proc is None or _audio_proc.poll() is not None
            ):
                _start_audio(ffplay, clip, volume)
            cmd = [
                str(ffmpeg),
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-re",
                "-i", str(clip),
                "-an",
                "-vf", f"scale={display_w}:{display_h}",
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "pipe:1",
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
            except OSError:
                break

            _clip_proc = proc
            assert proc.stdout is not None
            frame_interval = 1.0 / 30.0
            next_frame_at = time.perf_counter()
            frame_i = 0
            try:
                while not stop_event.is_set() and session_id == _session_id:
                    raw = _read_exact(proc.stdout, frame_bytes)
                    if raw is None:
                        break
                    if stop_event.is_set() or session_id != _session_id:
                        break
                    if not win32gui.IsWindow(hwnd):
                        break
                    _blit_rgb(hwnd, raw, display_w, display_h)
                    frame_i += 1
                    if frame_i % 30 == 1:
                        _topmost(hwnd)
                    next_frame_at += frame_interval
                    delay = next_frame_at - time.perf_counter()
                    if delay > 0:
                        if stop_event.wait(timeout=delay):
                            break
                    else:
                        next_frame_at = time.perf_counter()
            finally:
                try:
                    proc.kill()
                except Exception:
                    pass
                if _clip_proc is proc:
                    _clip_proc = None

            if stop_event.is_set() or session_id != _session_id:
                break
            time.sleep(0.01)
    finally:
        _playing = False
        _stop_audio()
        owned = hwnd
        with _lock:
            if _hwnd == owned:
                _hwnd = None
        _destroy_hwnd_owned(owned)


def start_clip_playback(
    clip: Path,
    ffmpeg: Path,
    *,
    max_width: int,
    ffprobe: Path | None = None,
    sound_enabled: bool = False,
    volume: int = 80,
    ffplay: Path | None = None,
) -> bool:
    global _clip_thread, _anchor, _session_stop, _session_id

    stop_clip_playback()
    _session_id += 1
    session_id = _session_id
    stop_event = threading.Event()
    _session_stop = stop_event
    _anchor = None

    _clip_thread = threading.Thread(
        target=_clip_reader,
        args=(
            ffmpeg,
            ffprobe,
            clip,
            max_width,
            stop_event,
            session_id,
            sound_enabled,
            volume,
            ffplay,
        ),
        name="clip-native",
        daemon=True,
    )
    _clip_thread.start()
    return True


def stop_clip_playback() -> None:
    global _clip_thread, _clip_proc, _playing, _session_stop, _session_id, _hwnd, _anchor

    _session_id += 1
    stop_event = _session_stop
    if stop_event is not None:
        stop_event.set()
    _session_stop = None

    kill_runtime_players()

    proc = _clip_proc
    _clip_proc = None
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
    _stop_audio()

    hwnd = _hwnd
    with _lock:
        _hwnd = None
    _anchor = None
    _playing = False
    _hide_hwnd(hwnd)
    _hide_all_preview_windows()

    thread = _clip_thread
    _clip_thread = None
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=0.2)
    kill_runtime_players()


def destroy_native() -> None:
    stop_clip_playback()


def is_clip_playing() -> bool:
    thread = _clip_thread
    stop_event = _session_stop
    return bool(
        _playing
        and thread
        and thread.is_alive()
        and stop_event is not None
        and not stop_event.is_set()
    )
