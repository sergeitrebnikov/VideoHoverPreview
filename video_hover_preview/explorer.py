from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import uiautomation as auto
import win32com.client
import win32gui

from .config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

EXPLORER_CLASS = "CabinetWClass"


@dataclass(frozen=True)
class HoveredItem:
    path: Path
    name: str


def _explorer_hwnd_at_point(x: int, y: int) -> int | None:
    hwnd = win32gui.WindowFromPoint((x, y))
    seen = set()
    while hwnd and hwnd not in seen:
        seen.add(hwnd)
        try:
            cls = win32gui.GetClassName(hwnd)
            if cls == EXPLORER_CLASS:
                return hwnd
            if cls == "VideoHoverPreviewNative":
                return None
        except Exception:
            pass
        hwnd = win32gui.GetParent(hwnd)
    return None


def _explorer_folder_for_hwnd(hwnd: int) -> Path | None:
    try:
        shell = win32com.client.Dispatch("Shell.Application")
        for window in shell.Windows():
            try:
                if int(window.HWND) != hwnd:
                    continue
                folder = window.Document.Folder.Self.Path
                if folder:
                    return Path(folder)
            except Exception:
                continue
    except Exception:
        return None
    return None


def _rect_contains(rect, x: int, y: int) -> bool:
    if not rect:
        return False
    try:
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    except AttributeError:
        return False
    if right <= left or bottom <= top:
        return False
    return left <= x <= right and top <= y <= bottom


def _list_item_name_at_point(root: auto.Control, x: int, y: int) -> str | None:
    best_name: str | None = None
    best_area: int | None = None
    stack: list[auto.Control] = [root]
    steps = 0
    while stack and steps < 4000:
        steps += 1
        current = stack.pop()
        try:
            ctype = current.ControlTypeName or ""
            if ctype == "ListItemControl":
                rect = current.BoundingRectangle
                if _rect_contains(rect, x, y):
                    name = (current.Name or "").strip()
                    if name:
                        area = (rect.right - rect.left) * (rect.bottom - rect.top)
                        if best_area is None or area < best_area:
                            best_area = area
                            best_name = name
            for child in current.GetChildren():
                stack.append(child)
        except Exception:
            continue
    return best_name


def _item_name_at_point_strict(x: int, y: int) -> str | None:
    """Имя элемента под курсором: только если курсор реально внутри его rect."""
    try:
        control = auto.ControlFromPoint(x, y)
    except Exception:
        return None
    current = control
    for _ in range(14):
        if not current:
            break
        try:
            ctype = current.ControlTypeName or ""
            name = (current.Name or "").strip()
            if ctype in {"ListItemControl", "TreeItemControl", "DataItemControl", "GroupControl"}:
                rect = current.BoundingRectangle
                if _rect_contains(rect, x, y):
                    if name and (
                        _looks_like_filename(name) or _looks_like_filename(_clean_item_name(name))
                    ):
                        return name
            elif _looks_like_filename(name) or _looks_like_filename(_clean_item_name(name)):
                rect = current.BoundingRectangle
                if _rect_contains(rect, x, y):
                    return name
            current = current.GetParentControl()
        except Exception:
            break
    return None


def _clean_item_name(name: str) -> str:
    name = re.sub(r"\s+\([^)]+\)\s*$", "", name).strip()
    return name


def _looks_like_filename(name: str) -> bool:
    if not name or len(name) > 260:
        return False
    if name in {".", ".."}:
        return False
    cleaned = _clean_item_name(name)
    if "/" in cleaned or "\\" in cleaned:
        return False
    # В проводнике расширения часто скрыты — точка в имени необязательна.
    return bool(cleaned)


def _resolve_file(folder: Path, item_name: str) -> Path | None:
    raw = (item_name or "").strip()
    if not raw:
        return None

    # Не чистить скобки заранее: «black cat (marvel) (2)» иначе
    # превращается в «black cat» и файл не находится.
    variants: list[str] = []
    for name in (raw, _clean_item_name(raw)):
        if name and name not in variants:
            variants.append(name)

    media_exts = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS

    def _as_file(path: Path) -> Path | None:
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            return None
        return None

    for name in variants:
        found = _as_file(folder / name)
        if found:
            return found
        if Path(name).suffix.lower() not in media_exts:
            for ext in media_exts:
                found = _as_file(folder / f"{name}{ext}")
                if found:
                    return found

    try:
        entries = [entry for entry in folder.iterdir() if entry.is_file()]
    except OSError:
        return None

    for name in variants:
        nlow = name.lower()
        suffix = Path(nlow).suffix
        nstem = Path(nlow).stem if suffix in media_exts else nlow
        for entry in entries:
            elow = entry.name.lower()
            if elow == nlow or entry.stem.lower() == nstem:
                return entry.resolve()

    raw_low = raw.lower()
    prefix = raw_low[: min(len(raw_low), 40)]
    if len(prefix) >= 8:
        for entry in entries:
            if entry.name.lower().startswith(prefix):
                return entry.resolve()
    return None


def get_hovered_explorer_file() -> HoveredItem | None:
    x, y = auto.GetCursorPos()

    hwnd = _explorer_hwnd_at_point(x, y)
    if not hwnd:
        return None

    folder = _explorer_folder_for_hwnd(hwnd)
    if not folder or not folder.is_dir():
        return None

    item_name = _item_name_at_point_strict(x, y)
    if not item_name:
        try:
            root = auto.ControlFromHandle(hwnd)
            if root:
                item_name = _list_item_name_at_point(root, x, y)
        except Exception:
            item_name = None

    if not item_name:
        return None

    candidate = _resolve_file(folder, item_name)
    if not candidate:
        return None
    return HoveredItem(path=candidate, name=candidate.name)


def media_extension(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".part"):
        name = name[:-5]
    return Path(name).suffix.lower()
