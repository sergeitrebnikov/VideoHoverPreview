from __future__ import annotations

import traceback


def main() -> int:
    try:
        from video_hover_preview.winapp import (
            APP_AUTHOR,
            ensure_icons,
            log,
            set_app_id,
            set_dpi_aware,
        )

        set_dpi_aware()
        set_app_id()
        ensure_icons()
        from video_hover_preview.app import main as app_main

        log("запуск")
        log(f"автор: {APP_AUTHOR}")
        return int(app_main() or 0)
    except Exception:
        try:
            from video_hover_preview.winapp import log

            log("crash:\n" + traceback.format_exc())
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
