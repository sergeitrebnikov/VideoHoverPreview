from __future__ import annotations

import win32api
import win32con


def work_area_at(x: int, y: int) -> tuple[int, int, int, int]:
    monitor = win32api.MonitorFromPoint((x, y), win32con.MONITOR_DEFAULTTONEAREST)
    info = win32api.GetMonitorInfo(monitor)
    return info["Work"]


def preview_position(
    cursor_x: int,
    cursor_y: int,
    width: int,
    height: int,
    *,
    tip_dx: int = 14,
    tip_dy: int = 22,
    margin: int = 10,
) -> tuple[int, int]:
    """Позиция превью поверх всплывающей подсказки Проводника (тип файла и т.п.).

    Подсказка обычно чуть справа и ниже курсора — ставим окно туда же,
    чтобы закрыть её; курсор остаётся у левого верхнего края, не внутри окна.
    """
    left, top, right, bottom = work_area_at(cursor_x, cursor_y)
    max_w = max(80, right - left - margin * 2)
    max_h = max(80, bottom - top - margin * 2)
    width = min(width, max_w)
    height = min(height, max_h)

    # Как у tooltip Explorer: отступ от курсора вправо-вниз.
    x = cursor_x + tip_dx
    y = cursor_y + tip_dy

    if x + width > right - margin:
        x = cursor_x - width - tip_dx
    if y + height > bottom - margin:
        y = cursor_y - height - tip_dy

    x = max(left + margin, min(x, right - width - margin))
    y = max(top + margin, min(y, bottom - height - margin))

    # Не накрывать точку курсора — иначе hover «теряет» файл.
    if x <= cursor_x <= x + width and y <= cursor_y <= y + height:
        # Сдвинуть так, чтобы курсор был чуть левее/выше окна.
        x = min(max(left + margin, cursor_x + tip_dx), right - width - margin)
        y = min(max(top + margin, cursor_y + tip_dy), bottom - height - margin)
        if x <= cursor_x <= x + width and y <= cursor_y <= y + height:
            x = max(left + margin, cursor_x - width - tip_dx)
            y = max(top + margin, cursor_y - height - tip_dy)

    return x, y
