"""ffmpeg による最終編集（尺合わせ・連結・ナレーション/BGM ミックス・字幕焼き込み）。

MiniMax の動画は 1 カット 6 秒 or 10 秒。15〜30 秒の広告は複数カットを
ここで連結して尺を作る。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .presets import Preset


class FFmpegMissing(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _require_ffmpeg() -> None:
    if not ffmpeg_available():
        raise FFmpegMissing(
            "ffmpeg / ffprobe が見つかりません。\n"
            "  macOS: brew install ffmpeg\n"
            "  Ubuntu: sudo apt-get install -y ffmpeg"
        )


def run(cmd: list[str], *, quiet: bool = True) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失敗:\n{' '.join(cmd)}\n{proc.stderr[-2000:]}")
    if not quiet and proc.stderr:
        print(proc.stderr[-800:])


def probe_duration(path: Path) -> float:
    _require_ffmpeg()
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


@dataclass
class ShotClip:
    path: Path
    seconds: float
    caption: str = ""


def normalize_clip(src: Path, dest: Path, preset: Preset, seconds: float, fps: int = 30) -> Path:
    """カットを所定の尺・解像度・fps に揃える（映像のみ）。"""
    _require_ffmpeg()
    w, h = preset.width, preset.height
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},fps={fps},format=yuv420p"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-i", str(src),
        "-t", f"{seconds:.3f}", "-an",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        str(dest),
    ])
    return dest


def trim(src: Path, dest: Path, seconds: float) -> Path:
    """解像度はそのままに、先頭から指定秒だけ切り出す。

    MiniMax の最短生成尺は 6 秒。3 秒の素材が欲しい場合は 6 秒生成してここで切る
    （課金は 6 秒分かかる）。
    """
    _require_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(src), "-t", f"{seconds:.3f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "copy"] if has_audio(src) else ["-an"]
    cmd += ["-movflags", "+faststart", str(dest)]
    run(cmd)
    return dest


def concat(clips: list[Path], dest: Path, work_dir: Path) -> Path:
    _require_ffmpeg()
    work_dir.mkdir(parents=True, exist_ok=True)
    listfile = work_dir / "concat.txt"
    listfile.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in clips), encoding="utf-8"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(dest)])
    return dest


def write_srt(clips: list[ShotClip], dest: Path) -> Path:
    def ts(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    lines, t, idx = [], 0.0, 1
    for c in clips:
        if c.caption:
            lines.append(f"{idx}\n{ts(t)} --> {ts(t + c.seconds)}\n{c.caption}\n")
            idx += 1
        t += c.seconds
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def ja_fonts() -> list[str]:
    """日本語グリフを持つフォント名の一覧。空なら字幕が空白で焼き込まれてしまう。"""
    if not shutil.which("fc-list"):
        return []
    out = subprocess.run(["fc-list", ":lang=ja", "family"], capture_output=True, text=True)
    names: list[str] = []
    for line in out.stdout.splitlines():
        for name in line.split(","):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return names


def cjk_font_available() -> bool:
    return bool(ja_fonts())


def pick_font(preferred: str | None = None) -> str:
    """指定フォントが無ければ、入っている日本語フォントにフォールバックする。"""
    available = ja_fonts()
    if preferred and preferred in available:
        return preferred
    for candidate in ("Noto Sans CJK JP", "Hiragino Sans", "Yu Gothic", "Noto Serif CJK JP"):
        if candidate in available:
            return candidate
    return available[0] if available else (preferred or "sans-serif")


def _ass_time(sec: float) -> str:
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def write_ass(clips: list[ShotClip], dest: Path, preset: Preset, font: str | None = None) -> Path:
    """字幕を ASS で書き出す。

    SRT + force_style は PlayRes 基準でスケールされ、縦型では字幕が画面外に飛ぶ。
    PlayResX/Y を実解像度に固定した ASS を自前で作り、px 指定をそのまま効かせる。
    """
    font_name = pick_font(font)
    size = max(28, round(preset.height / 26))
    margin_v = int(preset.safe_area.get("bottom", 120))
    margin_h = int(preset.safe_area.get("left", 60))
    outline = max(2, round(size / 14))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {preset.width}
PlayResY: {preset.height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font_name},{size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},2,2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines, t = [], 0.0
    for c in clips:
        if c.caption:
            text = c.caption.replace("\n", r"\N").replace("{", "(").replace("}", ")")
            lines.append(
                f"Dialogue: 0,{_ass_time(t)},{_ass_time(t + c.seconds)},Caption,,0,0,0,,{text}"
            )
        t += c.seconds

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return dest


def burn_subtitles(src: Path, ass: Path, dest: Path) -> Path:
    """字幕を焼き込む。音声オフ視聴が主流の Meta / Shorts では実質必須。"""
    _require_ffmpeg()
    if not cjk_font_available() and not os.environ.get("MMX_ALLOW_MISSING_CJK_FONT"):
        raise RuntimeError(
            "日本語フォントが見つかりません。このまま焼き込むと字幕が空白で出力されます。\n"
            "  macOS: 標準で日本語フォントあり（無い場合は brew install --cask font-noto-sans-cjk-jp）\n"
            "  Ubuntu: sudo apt-get install -y fonts-noto-cjk\n"
            "  無視して続ける場合: MMX_ALLOW_MISSING_CJK_FONT=1"
        )
    esc = str(ass.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", f"ass='{esc}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
    ]
    cmd += ["-c:a", "copy"] if has_audio(src) else ["-an"]
    cmd += [str(dest)]
    run(cmd)
    return dest


def has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        return bool(json.loads(out.stdout or "{}").get("streams"))
    except json.JSONDecodeError:
        return False


def mux_audio(
    video: Path,
    dest: Path,
    *,
    voiceover: Path | None = None,
    bgm: Path | None = None,
    bgm_gain_db: float = -18.0,
    fade_out: float = 0.6,
) -> Path:
    """ナレーションと BGM をミックスして映像に合成する。"""
    _require_ffmpeg()
    dur = probe_duration(video)
    inputs = ["-i", str(video)]
    filters, labels = [], []
    idx = 1

    if voiceover:
        inputs += ["-i", str(voiceover)]
        filters.append(f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[vo]")
        labels.append("[vo]")
        idx += 1
    if bgm:
        # 尺が足りない BGM はループさせてから必要分だけ切り出す
        inputs += ["-stream_loop", "-1", "-i", str(bgm)]
        filters.append(
            f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"volume={bgm_gain_db}dB,atrim=0:{dur:.3f},"
            f"afade=t=out:st={max(0.0, dur - fade_out):.3f}:d={fade_out}[bgm]"
        )
        labels.append("[bgm]")
        idx += 1

    dest.parent.mkdir(parents=True, exist_ok=True)
    if not labels:
        shutil.copy(video, dest)
        return dest

    if len(labels) == 1:
        filters.append(f"{labels[0]}apad,atrim=0:{dur:.3f}[aout]")
    else:
        filters.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=0,"
            f"apad,atrim=0:{dur:.3f}[aout]"
        )

    run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-shortest",
        str(dest),
    ])
    return dest


def finalize(src: Path, dest: Path) -> Path:
    """配信用に faststart 付きで書き出す（Meta / YouTube 入稿用）。"""
    _require_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(src), "-c:v", "libx264", "-preset", "slow",
           "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1"]
    cmd += ["-c:a", "aac", "-b:a", "192k"] if has_audio(src) else ["-an"]
    cmd += ["-movflags", "+faststart", str(dest)]
    run(cmd)
    return dest
