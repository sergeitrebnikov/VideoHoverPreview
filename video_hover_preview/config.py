from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".video-hover-preview" / "config.json"

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v",
    ".mpg", ".mpeg", ".3gp", ".ts", ".m2ts", ".ogv", ".divx",
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff",
}


@dataclass
class Settings:
    enabled: bool = True
    hover_delay_ms: int = 120
    preview_duration_sec: float = 12.0
    max_width: int = 528
    volume: int = 80
    sound_enabled: bool = False
    show_images: bool = True
    # Длительность одного сегмента (кадра) в покадровом режиме.
    segment_duration_sec: float = 3.0
    # Сколько сегментов склеивать в превью.
    segment_count: int = 4
    # Процент длительности файла, с которого начинается первый сегмент (0–90).
    first_percent: float = 20.0
    # Без склеек: играть подряд с first_percent, пока курсор на файле.
    continuous_mode: bool = False
    # Устарело: если есть в конфиге — мигрируем в segment_count/first_percent.
    segment_percents: tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)
    fade_ms: float = 160.0
    ffplay_path: str = ""
    ffmpeg_path: str = ""


def _migrate_segment_fields(data: dict) -> dict:
    """Старый segment_percents → segment_count + first_percent."""
    if "segment_count" not in data and isinstance(data.get("segment_percents"), (list, tuple)):
        percents = [float(p) for p in data["segment_percents"]]
        if percents:
            data["segment_count"] = len(percents)
            data.setdefault("first_percent", round(percents[0] * 100.0, 1))
    if isinstance(data.get("segment_percents"), list):
        data["segment_percents"] = tuple(data["segment_percents"])
    return data


def load_settings() -> Settings:
    if not CONFIG_PATH.exists():
        return Settings()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return Settings()
        data = _migrate_segment_fields(data)
        known = {k: v for k, v in data.items() if k in Settings.__dataclass_fields__}
        settings = Settings(**known)
        # Нормализация границ.
        settings.segment_count = max(1, min(12, int(settings.segment_count)))
        settings.segment_duration_sec = max(0.5, min(60.0, float(settings.segment_duration_sec)))
        settings.first_percent = max(0.0, min(90.0, float(settings.first_percent)))
        settings.preview_duration_sec = max(3.0, min(120.0, float(settings.preview_duration_sec)))
        settings.volume = max(0, min(100, int(settings.volume)))
        settings.sound_enabled = bool(settings.sound_enabled)
        return settings
    except (json.JSONDecodeError, TypeError, ValueError):
        return Settings()


def save_settings(settings: Settings) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Синхронизируем segment_percents для старых читателей / прозрачности конфига.
    settings.segment_percents = tuple(segment_ratios(settings))
    CONFIG_PATH.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")


def segment_ratios(settings: Settings) -> list[float]:
    """Доли 0..1, где начинаются сегменты."""
    if settings.continuous_mode:
        return [max(0.0, min(0.95, settings.first_percent / 100.0))]

    count = max(1, min(12, int(settings.segment_count)))
    first = max(0.0, min(0.9, settings.first_percent / 100.0))
    # Последний сегмент симметрично к концу (как раньше 20→80 при first=20).
    last = min(0.95, max(first, 1.0 - first))
    if count == 1:
        return [first]
    return [round(first + (last - first) * i / (count - 1), 4) for i in range(count)]
