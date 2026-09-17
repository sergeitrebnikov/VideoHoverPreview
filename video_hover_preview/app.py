from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pystray
import uiautomation as auto
import win32gui

from .config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, Settings, load_settings, save_settings
from .explorer import get_hovered_explorer_file, media_extension
from .preview_window import destroy_preview, hide_preview, pump_tk_events, show_image_preview
from .settings_ui import show_settings_dialog
from .video_preview import (
    find_ffplay,
    is_preview_active,
    play_video_preview,
    prefetch_preview_clip,
    stop_preview,
    warm_ffplay,
)
from .winapp import (
    APP_AUTHOR,
    APP_NAME,
    acquire_single_instance,
    ensure_icons,
    load_tray_icon,
    log as _log,
    notify_already_running,
    set_app_id,
    set_dpi_aware,
)


class HoverPreviewApp:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.enabled = self.settings.enabled
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._icon: pystray.Icon | None = None
        self._ffplay: Path | None = None
        self._pending_path: Path | None = None
        self._pending_since = 0.0
        self._showing_path: Path | None = None
        self._hover_anchor: tuple[int, int] | None = None
        self._hover_misses = 0
        self._want_settings = False

    def _make_icon_image(self):
        return load_tray_icon(self.enabled)

    def _refresh_icon(self) -> None:
        if self._icon:
            self._icon.icon = self._make_icon_image()
            suffix = "включено" if self.enabled else "выключено"
            self._icon.title = f"{APP_NAME}: {suffix}"

    def _cursor(self) -> tuple[int, int] | None:
        try:
            return win32gui.GetCursorPos()
        except Exception:
            return None

    def _remember_anchor(self) -> None:
        pos = self._cursor()
        if pos:
            self._hover_anchor = pos

    def _close_preview(self, *, keep_pending: bool = False) -> None:
        stop_preview(force=True)
        hide_preview()
        if not keep_pending:
            self._pending_path = None
        self._showing_path = None
        self._hover_anchor = None
        self._hover_misses = 0

    def _toggle_enabled(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self.enabled = not self.enabled
        self.settings.enabled = self.enabled
        save_settings(self.settings)
        if not self.enabled:
            self._close_preview()
        self._refresh_icon()

    def _shutdown(self) -> None:
        self._stop.set()
        stop_preview(force=True)
        hide_preview()
        destroy_preview()

    def _quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._shutdown()
        icon.visible = False
        icon.stop()

    def _open_settings(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._want_settings = True

    def _about(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            (
                f"{APP_NAME}\n"
                f"Автор: {APP_AUTHOR}\n\n"
                "Превью видео и изображений при наведении\n"
                "в Проводнике Windows.\n\n"
                "Бесплатная раздача. Авторство сохраняйте\n"
                "при доработках и похожих программах."
            ),
            f"О программе — {APP_NAME}",
            0x40,
        )

    def _run_settings_dialog(self) -> None:
        def _on_saved(updated: Settings) -> None:
            self.settings = updated
            self.enabled = updated.enabled
            _log(
                f"settings: continuous={updated.continuous_mode} sound={updated.sound_enabled} "
                f"vol={updated.volume} seg_dur={updated.segment_duration_sec} "
                f"count={updated.segment_count} first%={updated.first_percent} "
                f"cont_len={updated.preview_duration_sec}"
            )
            self._refresh_icon()

        try:
            show_settings_dialog(self.settings, on_saved=_on_saved)
        except Exception as exc:
            _log(f"settings dialog error: {exc}")

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: "Выключить превью" if self.enabled else "Включить превью",
                self._toggle_enabled,
            ),
            pystray.MenuItem("Настройки…", self._open_settings),
            pystray.MenuItem("О программе…", self._about),
            pystray.MenuItem("Выход", self._quit),
        )

    def _handle_file(self, path: Path) -> None:
        if self._showing_path == path:
            return
        ext = media_extension(path)
        if ext in VIDEO_EXTENSIONS:
            if not self._ffplay:
                _log("ffmpeg не найден")
                return
            ok = play_video_preview(path, self.settings, self._ffplay)
            if ok:
                self._showing_path = path
                self._remember_anchor()
                self._hover_misses = 0
            _log(f"video preview: {path.name} ok={ok}")
            return

        if ext in IMAGE_EXTENSIONS and self.settings.show_images:
            stop_preview()
            show_image_preview(path, self.settings.max_width)
            pump_tk_events()
            self._showing_path = path
            self._remember_anchor()
            self._hover_misses = 0
            _log(f"image preview: {path.name}")
            return

        stop_preview()
        hide_preview()
        self._showing_path = None

    def _loop(self) -> None:
        with auto.UIAutomationInitializerInThread():
            while not self._stop.is_set():
                try:
                    self._loop_once()
                except Exception as exc:
                    _log(f"hover loop error: {exc}")
                    time.sleep(0.2)

    def _loop_once(self) -> None:
        delay_sec = max(0, self.settings.hover_delay_ms) / 1000.0
        pump_tk_events()

        if self._want_settings:
            self._want_settings = False
            self._run_settings_dialog()
            return

        if not self.enabled:
            stop_preview()
            hide_preview()
            self._pending_path = None
            self._showing_path = None
            time.sleep(0.2)
            return

        item = None if self._stop.is_set() else get_hovered_explorer_file()

        if is_preview_active() or self._showing_path is not None:
            if item and self._showing_path and item.path == self._showing_path:
                self._hover_misses = 0
                self._remember_anchor()
            elif item and self._showing_path and item.path != self._showing_path:
                _log(f"close: switch → {item.path.name}")
                self._close_preview(keep_pending=True)
                self._pending_path = item.path
                self._pending_since = time.time()
                if media_extension(item.path) in VIDEO_EXTENSIONS and self._ffplay:
                    prefetch_preview_clip(item.path, self.settings, self._ffplay)
            else:
                near = False
                pos = self._cursor()
                if pos and self._hover_anchor is not None:
                    ax, ay = self._hover_anchor
                    near = abs(pos[0] - ax) <= 140 and abs(pos[1] - ay) <= 140
                if near:
                    self._hover_misses = 0
                else:
                    self._hover_misses += 1
                    if self._hover_misses >= 6:
                        _log("close: cursor left hover zone")
                        self._close_preview()
            time.sleep(0.04)
            return

        if not item:
            self._hover_misses += 1
            if self._hover_misses >= 5:
                if self._pending_path is not None or self._showing_path is not None:
                    stop_preview(force=True)
                    hide_preview()
                self._pending_path = None
                self._showing_path = None
                self._hover_anchor = None
            time.sleep(0.04)
            return

        self._hover_misses = 0

        path = item.path
        ext = media_extension(path)
        if ext not in VIDEO_EXTENSIONS and ext not in IMAGE_EXTENSIONS:
            self._close_preview()
            time.sleep(0.04)
            return

        now = time.time()
        if path != self._pending_path:
            self._pending_path = path
            self._pending_since = now
            self._showing_path = None
            stop_preview(force=True)
            hide_preview()
            if ext in VIDEO_EXTENSIONS and self._ffplay:
                prefetch_preview_clip(path, self.settings, self._ffplay)
        elif now - self._pending_since >= delay_sec:
            self._handle_file(path)

        time.sleep(0.04)

    def run(self) -> int:
        from .native_player import kill_runtime_players

        self._ffplay = find_ffplay(self.settings)
        if not self._ffplay:
            _log("старт: ffmpeg не найден (runtime\\ffmpeg\\bin)")
        else:
            _log(f"старт: ffmpeg={self._ffplay}")
            kill_runtime_players()
            warm_ffplay(self._ffplay)

        self._worker = threading.Thread(target=self._loop, name="hover-worker", daemon=True)
        self._worker.start()

        self._icon = pystray.Icon(
            APP_NAME,
            self._make_icon_image(),
            APP_NAME,
            menu=self._menu(),
        )
        try:
            self._icon.run()
        finally:
            self._shutdown()
            if self._worker and self._worker.is_alive():
                self._worker.join(timeout=0.5)
            os._exit(0)
        return 0


def main() -> int:
    set_dpi_aware()
    set_app_id()
    ensure_icons()
    if not acquire_single_instance():
        notify_already_running()
        return 0
    return HoverPreviewApp().run()
