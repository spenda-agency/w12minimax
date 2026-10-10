#!/usr/bin/env python3
"""参考動画の構成を解析する（ローカル完結・API を呼ばないので課金なし）。

    python3 scripts/analyze_reference.py assets/reference/sample.mp4

尺・解像度・fps と、シーン変化によるカット割りを出し、各カットの代表フレームを
書き出す。出力された構成の「型」（何秒でどの役割か）を brief 設計の土台にする。

他社の広告を参照する場合、ここで取るのは尺とカット割りという構造情報だけにとどめ、
絵・コピー・ナレーションは転記しないこと。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCENE_THRESHOLD = 0.3


def ffprobe_format(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate,nb_frames",
         "-show_entries", "format=duration,size", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_name", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    return bool(json.loads(out.stdout or "{}").get("streams"))


def scene_cuts(path: Path, threshold: float) -> list[float]:
    """シーン変化の時刻（秒）を返す。"""
    proc = subprocess.run(
        ["ffmpeg", "-i", str(path), "-filter_complex",
         f"select='gt(scene,{threshold})',metadata=print:file=-",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    times = []
    for line in proc.stdout.splitlines():
        if line.startswith("frame:") and "pts_time:" in line:
            try:
                times.append(float(line.split("pts_time:")[1].split()[0]))
            except (IndexError, ValueError):
                continue
    return times


def build_shots(cuts: list[float], duration: float) -> list[tuple[float, float]]:
    bounds = [0.0] + [t for t in cuts if 0.0 < t < duration] + [duration]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def extract_frames(path: Path, shots: list[tuple[float, float]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, (start, end) in enumerate(shots, 1):
        at = start + (end - start) / 2
        dest = out_dir / f"shot{i:02d}_{at:06.2f}s.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{at:.3f}", "-i", str(path),
             "-frames:v", "1", "-q:v", "3", "-loglevel", "error", str(dest)],
            check=False,
        )
        if dest.exists():
            frames.append(dest)
    return frames


def main() -> int:
    ap = argparse.ArgumentParser(description="参考動画の構成を解析する")
    ap.add_argument("video")
    ap.add_argument("--out", help="フレームの出力先（既定: <動画名>_analysis/）")
    ap.add_argument("--threshold", type=float, default=SCENE_THRESHOLD,
                    help=f"シーン変化の閾値 0〜1（既定 {SCENE_THRESHOLD}。細かすぎるなら上げる）")
    ap.add_argument("--min-shot", type=float, default=0.8,
                    help="これより短いカットは直前のカットに統合する（秒）")
    args = ap.parse_args()

    path = Path(args.video)
    if not path.exists():
        print(f"動画が見つかりません: {path}", file=sys.stderr)
        return 1

    info = ffprobe_format(path)
    stream = (info.get("streams") or [{}])[0]
    duration = float(info.get("format", {}).get("duration", 0))
    w, h = stream.get("width"), stream.get("height")
    aspect = f"{w}x{h}"
    vertical = bool(w and h and h > w)

    print(f"■ {path.name}")
    print(f"  尺       : {duration:.2f}s")
    print(f"  解像度   : {aspect}  ({'縦型' if vertical else '横型'})")
    print(f"  fps      : {stream.get('avg_frame_rate')}")
    print(f"  音声     : {'あり' if has_audio(path) else 'なし'}")

    cuts = scene_cuts(path, args.threshold)
    shots = build_shots(cuts, duration)

    # 極端に短いカットは検出ノイズなので直前に統合する
    merged: list[tuple[float, float]] = []
    for start, end in shots:
        if merged and (end - start) < args.min_shot:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    print(f"\n■ カット割り（閾値 {args.threshold} / {len(merged)}カット）")
    for i, (start, end) in enumerate(merged, 1):
        print(f"  {i:>2}. {start:>6.2f}s → {end:>6.2f}s   ({end - start:>5.2f}s)")

    out_dir = Path(args.out) if args.out else path.with_name(path.stem + "_analysis")
    frames = extract_frames(path, merged, out_dir)
    print(f"\n■ 代表フレーム {len(frames)}枚 → {out_dir}")

    summary = {
        "source": str(path),
        "duration": round(duration, 2),
        "resolution": aspect,
        "vertical": vertical,
        "has_audio": has_audio(path),
        "shots": [
            {"index": i, "start": round(s, 2), "end": round(e, 2), "seconds": round(e - s, 2)}
            for i, (s, e) in enumerate(merged, 1)
        ],
    }
    summary_path = out_dir / "structure.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"■ 構成サマリ → {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
