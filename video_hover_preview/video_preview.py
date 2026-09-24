from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .config import Settings, segment_ratios
from .native_player import is_clip_playing, start_clip_playback, stop_clip_playback
from .winapp import CLIP_DIR, log as _log

_lock = threading.Lock()
_current_video: Path | None = None
_segment_stop = threading.Event()
_duration_cache: dict[str, float] = {}
_segment_thread: threading.Thread | None = None
_ffmpeg_proc: subprocess.Popen | None = None
_prefetch_thread: threading.Thread | None = None
_prefetch_stop = threading.Event()
_prefetch_video: Path | None = None

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _real_exe(path: Path) -> Path:
    try:
        return Path(os.path.realpath(str(path)))
    except OSError:
        return path


def _bundled_exe(name: str) -> Path | None:
    path = Path(__file__).resolve().parents[1] / "runtime" / "ffmpeg" / "bin" / name
    if path.is_file():
        return _real_exe(path)
    return None


def _resolve_ffmpeg(settings: Settings, hint: Path | None = None) -> Path | None:
    if settings.ffmpeg_path:
        p = Path(settings.ffmpeg_path)
        if p.is_file():
            return _real_exe(p)
    bundled = _bundled_exe("ffmpeg.exe")
    if bundled:
        return bundled
    if hint:
        sibling = hint.with_name("ffmpeg.exe")
        if sibling.is_file():
            return _real_exe(sibling)
    found = shutil.which("ffmpeg")
    if found:
        return _real_exe(Path(found))
    return None


def find_ffplay(settings: Settings) -> Path | None:
    return _resolve_ffmpeg(settings, None)


def _ffprobe_for(ffmpeg: Path) -> Path | None:
    sibling = ffmpeg.with_name("ffprobe.exe")
    if sibling.is_file():
        return sibling
    found = shutil.which("ffprobe")
    return Path(found) if found else None


def _probe_duration(ffprobe: Path, video: Path) -> float | None:
    key = str(video.resolve())
    if key in _duration_cache:
        return _duration_cache[key]
    try:
        result = subprocess.run(
            [
                str(ffprobe),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video),
            ],
            capture_output=True,
            text=True,
            timeout=8.0,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return None
        duration = float(result.stdout.strip())
        _duration_cache[key] = duration
        return duration
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return None


def warm_ffplay(ffplay: Path) -> None:
    ffmpeg = _resolve_ffmpeg(Settings(), ffplay) or ffplay
    try:
        subprocess.run(
            [str(ffmpeg), "-version"],
            capture_output=True,
            timeout=3,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass
    CLIP_DIR.mkdir(parents=True, exist_ok=True)


def _preview_width(max_width: int) -> int:
    width = max(160, max_width)
    if width % 2:
        width -= 1
    return width


def _clip_ready(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 1000
    except OSError:
        return False


def _segment_starts(duration: float | None, settings: Settings) -> list[float]:
    if not duration or duration <= 1:
        return [0.0]
    times: list[float] = []
    for ratio in segment_ratios(settings):
        at = duration * max(0.0, min(1.0, ratio))
        if at + 0.3 < duration:
            times.append(round(at, 2))
    if not times:
        first = max(0.0, min(0.9, settings.first_percent / 100.0))
        times.append(round(min(duration * first, max(0.0, duration - 0.5)), 2))
    return times


def _segment_length(duration: float | None, settings: Settings, start_at: float) -> float:
    if settings.continuous_mode:
        if duration and duration > start_at:
            remaining = max(0.5, duration - start_at)
            return min(remaining, max(3.0, settings.preview_duration_sec))
        return max(3.0, settings.preview_duration_sec)
    return max(0.5, settings.segment_duration_sec)


def _crossfade_sec(settings: Settings, segment_len: float) -> float:
    if settings.continuous_mode:
        return 0.0
    raw = max(0.18, settings.fade_ms / 1000.0)
    return min(raw, segment_len * 0.35, 0.45)


def _clip_cache_path(
    video: Path,
    starts: list[float],
    segment_len: float,
    cross: float,
    preview_w: int,
    *,
    with_audio: bool = False,
) -> Path:
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    audio_tag = "a1" if with_audio else "a0"
    try:
        st = video.stat()
        identity = (
            f"{video.resolve()}|{st.st_mtime_ns}|{st.st_size}|"
            f"{starts}|{segment_len:.3f}|{cross:.3f}|{preview_w}|{audio_tag}"
        )
    except OSError:
        identity = f"{video}|{starts}|{segment_len:.3f}|{cross:.3f}|{preview_w}|{audio_tag}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:20]
    return CLIP_DIR / f"{digest}.mp4"


def _file_has_audio(ffprobe: Path | None, path: Path) -> bool:
    if not ffprobe or not path.is_file():
        return False
    try:
        result = subprocess.run(
            [
                str(ffprobe),
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=5.0,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return "audio" in (result.stdout or "").lower()


def _ffplay_bin(settings: Settings, ffmpeg: Path | None = None) -> Path | None:
    if settings.ffplay_path:
        p = Path(settings.ffplay_path)
        if p.is_file():
            return _real_exe(p)
    if ffmpeg:
        sibling = ffmpeg.with_name("ffplay.exe")
        if sibling.is_file():
            return _real_exe(sibling)
    bundled = _bundled_exe("ffplay.exe")
    if bundled:
        return bundled
    found = shutil.which("ffplay")
    return _real_exe(Path(found)) if found else None


def _segments_filter_complex(
    count: int,
    segment_len: float,
    edge_fade: float,
    preview_w: int,
    *,
    with_audio: bool,
) -> str:
    parts: list[str] = []
    fade = max(0.12, min(edge_fade, segment_len * 0.25)) if edge_fade > 0 else 0.0
    for i in range(count):
        chain = (
            f"[{i}:v]scale={preview_w}:-2,"
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            f"setsar=1,fps=30,format=yuv420p"
        )
        if count > 1 and fade > 0 and i > 0:
            chain += f",fade=t=in:st=0:d={fade:.3f}"
        if count > 1 and fade > 0 and i < count - 1:
            chain += f",fade=t=out:st={max(0.05, segment_len - fade):.3f}:d={fade:.3f}"
        parts.append(f"{chain}[v{i}]")
    if count == 1:
        parts.append("[v0]format=yuv420p[outv]")
    else:
        labels = "".join(f"[v{i}]" for i in range(count))
        parts.append(f"{labels}concat=n={count}:v=1:a=0[outv]")

    if with_audio and count > 1:
        for i in range(count):
            parts.append(
                f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
                f"atrim=0:{max(0.35, segment_len):.3f},asetpts=PTS-STARTPTS[a{i}]"
            )
        alabels = "".join(f"[a{i}]" for i in range(count))
        parts.append(f"{alabels}concat=n={count}:v=0:a=1[outa]")
    return ";".join(parts)


def _unlink_quiet(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _kill_process(proc: subprocess.Popen | None, *, force: bool = False) -> None:
    if not proc or proc.poll() is not None:
        return
    if force:
        proc.kill()
    else:
        proc.terminate()
        try:
            proc.wait(timeout=0.35)
        except subprocess.TimeoutExpired:
            proc.kill()


def _build_seamless_clip(
    ffmpeg: Path,
    video: Path,
    starts: list[float],
    segment_len: float,
    cross: float,
    preview_w: int,
    out_path: Path,
    stop_event: threading.Event,
    *,
    register_global: bool = True,
    with_audio: bool = False,
) -> bool:
    if _clip_ready(out_path):
        return True

    ffmpeg = _real_exe(ffmpeg)
    tmp = out_path.with_suffix(".partial.mp4")
    _unlink_quiet(tmp)

    count = len(starts)

    def _make_cmd(audio: bool) -> list[str]:
        cmd: list[str] = [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
        ]
        for at in starts:
            cmd += [
                "-ss", f"{max(0.0, at):.3f}",
                "-t", f"{max(0.35, segment_len):.3f}",
                "-i", str(video),
            ]
        cmd += [
            "-filter_complex",
            _segments_filter_complex(
                count, segment_len, cross, preview_w, with_audio=audio and count > 1
            ),
            "-map", "[outv]",
        ]
        if audio:
            if count == 1:
                cmd += ["-map", "0:a?"]
            else:
                cmd += ["-map", "[outa]"]
            cmd += ["-c:a", "aac", "-ac", "2", "-b:a", "96k", "-shortest"]
        else:
            cmd += ["-an"]
        cmd += [
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(tmp),
        ]
        return cmd

    def _run(cmd: list[str]) -> tuple[int, str]:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as exc:
            _log(f"clip build spawn fail: {exc}")
            return 1, str(exc)

        global _ffmpeg_proc
        if register_global:
            _ffmpeg_proc = proc
        while proc.poll() is None:
            if stop_event.is_set():
                _kill_process(proc, force=True)
                if register_global:
                    _ffmpeg_proc = None
                _unlink_quiet(tmp)
                return -1, "stopped"
            time.sleep(0.03)

        if register_global:
            _ffmpeg_proc = None
        err = ""
        try:
            if proc.stderr is not None:
                err = proc.stderr.read().decode("utf-8", errors="replace")[:400]
        except OSError:
            pass
        return int(proc.returncode or 0), err

    code, err = _run(_make_cmd(with_audio))
    if code == -1:
        return False
    if code != 0 and with_audio:
        _log(f"clip audio build fail, retry silent: {err!r}")
        _unlink_quiet(tmp)
        _unlink_quiet(out_path)
        return False

    if code != 0 or not _clip_ready(tmp):
        _log(f"clip build fail code={code} err={err!r} starts={starts}")
        _unlink_quiet(tmp)
        return False

    try:
        _unlink_quiet(out_path)
        tmp.replace(out_path)
    except OSError:
        try:
            shutil.move(str(tmp), str(out_path))
        except OSError as exc:
            _log(f"clip move fail: {exc}")
            _unlink_quiet(tmp)
            return False
    ok = _clip_ready(out_path)
    if ok:
        _log(
            f"clip ok segments={len(starts)} starts={starts} "
            f"size={out_path.stat().st_size} audio={with_audio}"
        )
    return ok


def is_preview_active() -> bool:
    if is_clip_playing():
        return True
    thread = _segment_thread
    return bool(thread and thread.is_alive() and not _segment_stop.is_set())


def prefetch_preview_clip(video: Path, settings: Settings, ffplay: Path) -> None:
    global _prefetch_thread, _prefetch_video

    with _lock:
        if _prefetch_video == video and _prefetch_thread and _prefetch_thread.is_alive():
            return
        _prefetch_video = video

    _prefetch_stop.clear()

    def _worker() -> None:
        ffmpeg = _resolve_ffmpeg(settings, ffplay)
        if not ffmpeg:
            return
        ffprobe = _ffprobe_for(ffmpeg)
        duration = _probe_duration(ffprobe, video) if ffprobe else None
        starts = _segment_starts(duration, settings) or [0.0]
        segment_len = _segment_length(duration, settings, starts[0] if starts else 0.0)
        cross = _crossfade_sec(settings, segment_len)
        preview_w = _preview_width(settings.max_width)
        with_audio = bool(settings.sound_enabled)
        clip = _clip_cache_path(
            video, starts, segment_len, cross, preview_w, with_audio=with_audio
        )
        if _clip_ready(clip):
            return
        _build_seamless_clip(
            ffmpeg,
            video,
            starts,
            segment_len,
            cross,
            preview_w,
            clip,
            _prefetch_stop,
            register_global=False,
            with_audio=with_audio,
        )

    old = _prefetch_thread
    if old and old.is_alive():
        _prefetch_stop.set()
        old.join(timeout=0.05)
        _prefetch_stop.clear()

    _prefetch_thread = threading.Thread(target=_worker, name="clip-prefetch", daemon=True)
    _prefetch_thread.start()


def _run_seamless(
    video: Path,
    settings: Settings,
    ffmpeg: Path,
    starts: list[float],
    duration: float | None,
) -> None:
    start0 = starts[0] if starts else 0.0
    segment_len = _segment_length(duration, settings, start0)
    if duration is not None:
        adjusted: list[float] = []
        for at in starts:
            play_for = min(segment_len, max(0.35, duration - at))
            if play_for >= 0.35:
                adjusted.append(at)
        starts = adjusted or starts[:1] or [0.0]

    # В покадровом режиме при одном старте пересчитаем точки (короткий ролик и т.п.).
    if (
        not settings.continuous_mode
        and len(starts) < 2
        and duration
        and duration > segment_len * 2
        and settings.segment_count > 1
    ):
        starts = _segment_starts(duration, settings)
        start0 = starts[0] if starts else 0.0
        segment_len = _segment_length(duration, settings, start0)

    cross = _crossfade_sec(settings, segment_len)
    preview_w = _preview_width(settings.max_width)
    with_audio = bool(settings.sound_enabled)
    mode = "continuous" if settings.continuous_mode else f"segments={len(starts)}"
    _log(
        f"preview start file={video.name} mode={mode} duration={duration} "
        f"starts={starts} seg_len={segment_len:.2f} sound={with_audio}"
    )

    clip = _clip_cache_path(
        video, starts, segment_len, cross, preview_w, with_audio=with_audio
    )
    ffprobe = _ffprobe_for(ffmpeg)
    if _clip_ready(clip):
        if with_audio and not _file_has_audio(ffprobe, clip):
            _log(f"cache without audio, rebuild {clip.name}")
            _unlink_quiet(clip)
        else:
            _log(f"cache hit {clip.name}")
    if not _clip_ready(clip):
        ok = _build_seamless_clip(
            ffmpeg,
            video,
            starts,
            segment_len,
            cross,
            preview_w,
            clip,
            _segment_stop,
            with_audio=with_audio,
        )
        if _segment_stop.is_set() or not ok:
            if with_audio:
                clip = _clip_cache_path(
                    video, starts, segment_len, cross, preview_w, with_audio=False
                )
                if not _clip_ready(clip):
                    ok = _build_seamless_clip(
                        ffmpeg,
                        video,
                        starts,
                        segment_len,
                        cross,
                        preview_w,
                        clip,
                        _segment_stop,
                        with_audio=False,
                    )
                else:
                    ok = True
            if _segment_stop.is_set() or not ok:
                _log("clip unavailable")
                return

    if _segment_stop.is_set():
        return

    play_audio = bool(with_audio and _file_has_audio(ffprobe, clip))
    ffplay_audio = _ffplay_bin(settings, ffmpeg) if play_audio else None
    started = start_clip_playback(
        clip,
        ffmpeg,
        max_width=settings.max_width,
        ffprobe=ffprobe,
        sound_enabled=play_audio,
        volume=settings.volume,
        ffplay=ffplay_audio,
    )
    _log(f"playback start ok={started} audio={play_audio}")

    # Ждём, пока поток реально начнёт кадры (иначе while сразу выходит).
    for _ in range(20):
        if _segment_stop.is_set() or is_clip_playing():
            break
        time.sleep(0.02)

    while not _segment_stop.is_set() and is_clip_playing():
        time.sleep(0.04)


def stop_preview(*, force: bool = False) -> None:
    global _current_video, _segment_thread, _ffmpeg_proc

    from .native_player import force_stop_all_players

    _segment_stop.set()
    _prefetch_stop.set()
    stop_clip_playback()

    ffmpeg_proc = _ffmpeg_proc
    _ffmpeg_proc = None
    _kill_process(ffmpeg_proc, force=True)

    with _lock:
        _current_video = None

    thread = _segment_thread
    _segment_thread = None
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=0.25)

    # На случай гонки: поток клипа успел поднять новый ffmpeg/ffplay
    force_stop_all_players(deep=False, scan=True)


def play_video_preview(video: Path, settings: Settings, ffplay: Path) -> bool:
    global _current_video, _segment_thread

    with _lock:
        if _current_video == video and (
            is_clip_playing()
            or (_segment_thread and _segment_thread.is_alive())
        ):
            return True

    stop_preview(force=True)

    ffmpeg = _resolve_ffmpeg(settings, ffplay)
    if not ffmpeg:
        _log("ffmpeg не найден")
        return False

    ffprobe = _ffprobe_for(ffmpeg)
    duration = _probe_duration(ffprobe, video) if ffprobe else None
    starts = _segment_starts(duration, settings) or [0.0]

    segment_len = _segment_length(duration, settings, starts[0] if starts else 0.0)
    cross = _crossfade_sec(settings, segment_len)
    preview_w = _preview_width(settings.max_width)
    with_audio = bool(settings.sound_enabled)
    clip = _clip_cache_path(
        video, starts, segment_len, cross, preview_w, with_audio=with_audio
    )
    if not _clip_ready(clip):
        if _prefetch_video == video and _prefetch_thread and _prefetch_thread.is_alive():
            _prefetch_thread.join(timeout=0.4)

    _log(f"play request name={video.name} duration={duration} starts={starts}")

    _segment_stop.clear()
    with _lock:
        _current_video = video

    _segment_thread = threading.Thread(
        target=_run_seamless,
        args=(video, settings, ffmpeg, starts, duration),
        name="clip-seamless",
        daemon=True,
    )
    _segment_thread.start()
    return True
