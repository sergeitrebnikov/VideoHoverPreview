from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .config import Settings, save_settings
from .preview_window import ensure_tk_root
from .winapp import APP_ICO


def show_settings_dialog(
    settings: Settings,
    on_saved: Callable[[Settings], None] | None = None,
) -> None:
    """Модальное окно настроек. Только из потока hover-worker (общий Tk)."""
    root = ensure_tk_root()
    # overrideredirect-родитель ломает клики у Toplevel+grab — временно снимаем.
    try:
        root.overrideredirect(False)
    except tk.TclError:
        pass
    root.withdraw()

    dlg = tk.Toplevel(root)
    dlg.title("Video Hover Preview — настройки")
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    # Автор вшит в код и в окно настроек.
    if APP_ICO.is_file():
        try:
            dlg.iconbitmap(str(APP_ICO))
        except tk.TclError:
            pass

    frm = ttk.Frame(dlg, padding=14)
    frm.grid(row=0, column=0, sticky="nsew")

    continuous = tk.BooleanVar(value=settings.continuous_mode)
    sound_on = tk.BooleanVar(value=settings.sound_enabled)
    hover_ms = tk.IntVar(value=max(0, min(2000, int(settings.hover_delay_ms or 40))))
    seg_dur = tk.DoubleVar(value=settings.segment_duration_sec)
    seg_count = tk.IntVar(value=settings.segment_count)
    first_pct = tk.DoubleVar(value=settings.first_percent)
    cont_len = tk.DoubleVar(value=settings.preview_duration_sec)
    volume = tk.IntVar(value=max(0, min(100, int(settings.volume or 80))))

    seg_widgets: list[ttk.Widget] = []
    cont_widgets: list[ttk.Widget] = []

    def _sync_state(*_args) -> None:
        on = continuous.get()
        for w in seg_widgets:
            w.configure(state="disabled" if on else "normal")
        for w in cont_widgets:
            w.configure(state="normal" if on else "disabled")

    row = 0
    ttk.Label(frm, text="Общее", font=("", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky="w")
    row += 1

    ttk.Label(frm, text="Задержка наведения, мс").grid(
        row=row, column=0, sticky="w", pady=3
    )
    ttk.Spinbox(frm, textvariable=hover_ms, from_=0, to=2000, increment=10, width=10).grid(
        row=row, column=1, sticky="e", pady=3, padx=(12, 0)
    )
    row += 1

    ttk.Label(frm, text="Старт воспроизведения, % от длины файла").grid(
        row=row, column=0, sticky="w", pady=3
    )
    ttk.Spinbox(frm, textvariable=first_pct, from_=0.0, to=90.0, increment=5.0, width=10).grid(
        row=row, column=1, sticky="e", pady=3, padx=(12, 0)
    )
    row += 1

    ttk.Checkbutton(
        frm,
        text="Звук превью",
        variable=sound_on,
    ).grid(row=row, column=0, sticky="w", pady=3)
    vol_fr = ttk.Frame(frm)
    vol_fr.grid(row=row, column=1, sticky="e", pady=3, padx=(12, 0))
    ttk.Label(vol_fr, text="Громкость").pack(side="left", padx=(0, 6))
    ttk.Spinbox(vol_fr, textvariable=volume, from_=0, to=100, increment=5, width=6).pack(side="left")
    row += 1

    ttk.Checkbutton(
        frm,
        text="Непрерывное воспроизведение (без покадровых переходов)",
        variable=continuous,
        command=_sync_state,
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 10))
    row += 1

    ttk.Label(frm, text="Покадровый режим", font=("", 10, "bold")).grid(
        row=row, column=0, columnspan=2, sticky="w"
    )
    row += 1

    ttk.Label(frm, text="Длительность кадра, сек").grid(row=row, column=0, sticky="w", pady=3)
    sp_dur = ttk.Spinbox(frm, textvariable=seg_dur, from_=0.5, to=30.0, increment=0.5, width=10)
    sp_dur.grid(row=row, column=1, sticky="e", pady=3, padx=(12, 0))
    seg_widgets.append(sp_dur)
    row += 1

    ttk.Label(frm, text="Количество кадров").grid(row=row, column=0, sticky="w", pady=3)
    sp_cnt = ttk.Spinbox(frm, textvariable=seg_count, from_=1, to=12, increment=1, width=10)
    sp_cnt.grid(row=row, column=1, sticky="e", pady=3, padx=(12, 0))
    seg_widgets.append(sp_cnt)
    row += 1

    ttk.Label(frm, text="Непрерывный режим", font=("", 10, "bold")).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(12, 0)
    )
    row += 1

    ttk.Label(frm, text="Длина куска для цикла, сек").grid(row=row, column=0, sticky="w", pady=3)
    sp_cont = ttk.Spinbox(frm, textvariable=cont_len, from_=3.0, to=120.0, increment=1.0, width=10)
    sp_cont.grid(row=row, column=1, sticky="e", pady=3, padx=(12, 0))
    cont_widgets.append(sp_cont)
    row += 1

    ttk.Label(
        frm,
        text="Кадры равномерно от «старта %» до симметричной точки у конца.\n"
        "Звук по умолчанию выключен. Непрерывный режим — без склеек.",
        foreground="#555",
        wraplength=380,
        justify="left",
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 8))
    row += 1

    ttk.Label(
        frm,
        text="Автор: Требников Сергей",
        foreground="#777",
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
    row += 1

    result = {"saved": False}

    def _close() -> None:
        try:
            dlg.destroy()
        except tk.TclError:
            pass

    def _save() -> None:
        try:
            settings.continuous_mode = bool(continuous.get())
            settings.sound_enabled = bool(sound_on.get())
            settings.hover_delay_ms = int(float(hover_ms.get()))
            settings.segment_duration_sec = float(seg_dur.get())
            settings.segment_count = int(float(seg_count.get()))
            settings.first_percent = float(first_pct.get())
            settings.preview_duration_sec = float(cont_len.get())
            settings.volume = int(float(volume.get()))
        except (tk.TclError, ValueError, TypeError):
            return
        settings.hover_delay_ms = max(0, min(2000, settings.hover_delay_ms))
        settings.segment_count = max(1, min(12, settings.segment_count))
        settings.segment_duration_sec = max(0.5, min(60.0, settings.segment_duration_sec))
        settings.first_percent = max(0.0, min(90.0, settings.first_percent))
        settings.preview_duration_sec = max(3.0, min(120.0, settings.preview_duration_sec))
        settings.volume = max(0, min(100, settings.volume))
        save_settings(settings)
        result["saved"] = True
        _close()

    btns = ttk.Frame(frm)
    btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(6, 0))
    ttk.Button(btns, text="Отмена", command=_close).pack(side="right", padx=(6, 0))
    ttk.Button(btns, text="Сохранить", command=_save).pack(side="right")

    _sync_state()
    dlg.update_idletasks()
    w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
    sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
    dlg.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")

    dlg.protocol("WM_DELETE_WINDOW", _close)
    dlg.focus_force()
    dlg.lift()
    # Без grab_set — с overrideredirect-корнем grab часто «съедает» клики.
    dlg.wait_window()

    try:
        root.overrideredirect(True)
        root.withdraw()
        root.attributes("-alpha", 0)
    except tk.TclError:
        pass

    if result["saved"] and on_saved:
        on_saved(settings)
