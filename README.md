# Video Hover Preview

Превью **видео и изображений** при наведении курсора на файл в Проводнике Windows.

**Автор:** Требников Сергей

## Возможности

- Наведение на `.mp4`, `.mkv`, `.mov`, `.webm` и др. → короткое превью
- Картинки: `.jpg`, `.png`, `.gif`, …
- Иконка в трее: вкл/выкл, настройки, «О программе»
- Покадровый или непрерывный режим
- Портативный запуск без установки Python

## Быстрый старт (готовая сборка)

1. Скачайте архив из [Releases](../../releases) (`VideoHoverPreview-Trebnikov.zip`)
2. Распакуйте в любую папку
3. Запустите `VideoHoverPreview.exe`
4. Наведите курсор на видео или картинку в Проводнике

## Запуск из исходников

Нужны Python 3.12+, зависимости из `requirements.txt` и `ffmpeg`/`ffplay` в `PATH` или в `runtime/ffmpeg/bin/`.

```bat
pip install -r requirements.txt
python -m video_hover_preview
```

Или через лаунчер (если есть portable runtime):

```bat
VideoHoverPreview.exe
```

## Структура

```
VideoHoverPreview.exe   — лаунчер
launch.py               — точка входа
video_hover_preview/    — код
runtime/ffmpeg/bin/     — ffmpeg / ffplay (в релизном zip)
runtime/python/tools/   — портативный Python (в релизном zip)
```

В git обычно лежит исходный код; полный portable-zip — в Releases (runtime тяжёлый).

## Лицензии сторонних компонентов

- **ffmpeg / ffplay** — свои лицензии (GPL/LGPL в зависимости от сборки)
- **Python** и библиотеки (`pystray`, `Pillow`, `pywin32`, `uiautomation`) — по своим лицензиям в `runtime`

## Авторство

Программа создана: **Требников Сергей**.

При бесплатной раздаче, доработках и создании похожих программ сохраняйте указание автора.

## Обратная связь

Issues в этом репозитории или профиль автора на FL.ru.
