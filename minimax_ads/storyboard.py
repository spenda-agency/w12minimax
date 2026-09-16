"""絵コンテ(brief JSON) から 15〜30秒の広告動画を一気通貫で生成するパイプライン。

  brief.json
    └─ shot ごとに  ①キーフレーム静止画(image-01)
                    ②その画像を起点に動画生成(I2V / Hailuo-02)
    └─ ナレーション音声(T2A)
    └─ ffmpeg で 尺調整 → 連結 → 字幕焼き込み → 音声ミックス → 入稿用書き出し

途中で失敗しても run.json に状態を残すので --resume で続きから再開できる
（動画生成は課金が発生するため、作り直しを避ける設計）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import assemble, audio, images, video
from .api import MinimaxClient, MinimaxError
from .config import DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL
from .presets import Preset, get as get_preset

# MiniMax の動画は 6 秒 / 10 秒単位。必要尺以上を生成して ffmpeg で切る。
ALLOWED_CLIP_SECONDS = [6, 10]


@dataclass
class Shot:
    id: str
    seconds: float
    image_prompt: str = ""
    motion_prompt: str = ""
    caption: str = ""
    keyframe: str | None = None      # 既存画像(パス/URL)を使う場合
    use_keyframe: bool = True        # False なら T2V（画像を挟まない）
    raw: dict = field(default_factory=dict)

    @property
    def gen_seconds(self) -> int:
        for s in ALLOWED_CLIP_SECONDS:
            if s >= self.seconds:
                return s
        return ALLOWED_CLIP_SECONDS[-1]


@dataclass
class Brief:
    name: str
    preset: Preset
    shots: list[Shot]
    style: str = ""
    image_model: str = DEFAULT_IMAGE_MODEL
    video_model: str = DEFAULT_VIDEO_MODEL
    resolution: str | None = None
    voiceover: dict = field(default_factory=dict)
    bgm: dict = field(default_factory=dict)
    subtitles: bool = True
    font: str | None = None
    source: Path | None = None

    @property
    def total_seconds(self) -> float:
        return sum(s.seconds for s in self.shots)


def load_brief(path: Path) -> Brief:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    shots = [
        Shot(
            id=s.get("id") or f"s{i + 1}",
            seconds=float(s.get("seconds", 5)),
            image_prompt=s.get("image_prompt", ""),
            motion_prompt=s.get("motion_prompt", ""),
            caption=s.get("caption", ""),
            keyframe=s.get("keyframe"),
            use_keyframe=bool(s.get("use_keyframe", True)),
            raw=s,
        )
        for i, s in enumerate(data.get("shots", []))
    ]
    if not shots:
        raise MinimaxError(f"shots が空です: {path}")

    brief = Brief(
        name=data.get("name") or Path(path).stem,
        preset=get_preset(data.get("preset", "meta_reels_9x16")),
        shots=shots,
        style=data.get("style", ""),
        image_model=data.get("image_model", DEFAULT_IMAGE_MODEL),
        video_model=data.get("video_model", DEFAULT_VIDEO_MODEL),
        resolution=data.get("resolution"),
        voiceover=data.get("voiceover") or {},
        bgm=data.get("bgm") or {},
        subtitles=bool(data.get("subtitles", True)),
        font=data.get("font"),
        source=Path(path),
    )
    return brief


def validate_brief(brief: Brief) -> list[str]:
    warnings = []
    total = brief.total_seconds
    if total > brief.preset.max_seconds:
        warnings.append(
            f"合計 {total:.0f}s はプリセット上限 {brief.preset.max_seconds}s を超えています"
        )
    if not 6 <= total <= 60:
        warnings.append(f"合計 {total:.0f}s は広告尺として想定外です（推奨 15〜30s）")
    for s in brief.shots:
        if s.seconds > 10:
            warnings.append(f"shot {s.id}: 1カット {s.seconds}s は生成上限(10s)超。分割してください")
        if s.use_keyframe and not (s.image_prompt or s.keyframe):
            warnings.append(f"shot {s.id}: image_prompt も keyframe もありません")
        if not s.motion_prompt:
            warnings.append(f"shot {s.id}: motion_prompt が空です")
    return warnings


class Run:
    """出力ディレクトリと進捗状態の管理。"""

    def __init__(self, root: Path):
        self.root = root
        self.state_path = root / "run.json"
        self.state: dict = {}
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def shot(self, shot_id: str) -> dict:
        return self.state.setdefault("shots", {}).setdefault(shot_id, {})


def build_image_prompt(brief: Brief, shot: Shot) -> str:
    parts = [shot.image_prompt.strip(), brief.style.strip()]
    return ". ".join(p for p in parts if p)


def build_motion_prompt(brief: Brief, shot: Shot) -> str:
    parts = [shot.motion_prompt.strip()]
    if not shot.use_keyframe:
        # T2V の場合は画の情報もプロンプトに含める必要がある
        parts.insert(0, shot.image_prompt.strip())
        parts.append(brief.style.strip())
    return ". ".join(p for p in parts if p)


def run_storyboard(
    client: MinimaxClient,
    brief: Brief,
    out_root: Path,
    *,
    resume: bool = False,
    skip_video: bool = False,
    skip_assemble: bool = False,
    poll_interval: int = 10,
    force: bool = False,
) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if resume:
        candidates = sorted(out_root.glob(f"{brief.name}-*"))
        run_dir = candidates[-1] if candidates else out_root / f"{brief.name}-{stamp}"
    else:
        run_dir = out_root / f"{brief.name}-{stamp}"

    run = Run(run_dir)
    run.state.setdefault("brief", str(brief.source) if brief.source else None)
    run.state.setdefault("preset", brief.preset.key)
    run.state.setdefault("created_at", stamp)
    run.save()
    print(f"■ 出力先: {run_dir}")

    resolution = brief.resolution or brief.preset.video_resolution
    clips: list[assemble.ShotClip] = []

    for i, shot in enumerate(brief.shots, 1):
        st = run.shot(shot.id)
        print(f"\n[{i}/{len(brief.shots)}] shot {shot.id}  ({shot.seconds}s)")

        # ① キーフレーム
        keyframe_ref: str | None = None
        if shot.use_keyframe:
            if shot.keyframe:
                keyframe_ref = shot.keyframe
            elif st.get("keyframe") and Path(st["keyframe"]).exists():
                keyframe_ref = st["keyframe"]
                print(f"  keyframe: 既存を再利用 {keyframe_ref}")
            else:
                print("  keyframe 生成中…")
                paths = images.generate_and_save(
                    client,
                    build_image_prompt(brief, shot),
                    run_dir / "keyframes",
                    stem=shot.id,
                    aspect_ratio=brief.preset.image_aspect,
                    n=1,
                    model=brief.image_model,
                    force=force,
                )
                keyframe_ref = str(paths[0])
                st["keyframe"] = keyframe_ref
                run.save()
                print(f"  keyframe: {keyframe_ref}")

        # ② 動画
        clip_path = run_dir / "clips" / f"{shot.id}.mp4"
        if skip_video:
            print("  video: --skip-video のためスキップ")
        elif st.get("clip") and Path(st["clip"]).exists() and Path(st["clip"]).stat().st_size > 0:
            clip_path = Path(st["clip"])
            print(f"  video: 既存を再利用 {clip_path}")
        else:
            print("  video 生成中…（数分かかります）")
            video.generate_and_save(
                client,
                build_motion_prompt(brief, shot),
                clip_path,
                model=brief.video_model,
                duration=shot.gen_seconds,
                resolution=resolution,
                first_frame=keyframe_ref,
                interval=poll_interval,
                force=force,
            )
            st["clip"] = str(clip_path)
            run.save()
            print(f"  video: {clip_path}")

        clips.append(assemble.ShotClip(clip_path, shot.seconds, shot.caption))

    # ③ ナレーション
    vo_path = None
    if brief.voiceover.get("enabled") and brief.voiceover.get("script"):
        vo_path = run_dir / "audio" / "voiceover.mp3"
        if vo_path.exists() and vo_path.stat().st_size > 0:
            print(f"\n■ ナレーション: 既存を再利用 {vo_path}")
        else:
            print("\n■ ナレーション生成中…")
            audio.synthesize(
                client,
                brief.voiceover["script"],
                vo_path,
                voice_id=brief.voiceover.get("voice_id", audio.JA_VOICES["female_calm"]),
                speed=float(brief.voiceover.get("speed", 1.0)),
                volume=float(brief.voiceover.get("volume", 1.0)),
                emotion=brief.voiceover.get("emotion"),
            )
            print(f"  {vo_path}")

    if skip_assemble or skip_video:
        print("\n■ 編集はスキップしました。素材は上記ディレクトリにあります。")
        run.save()
        return run_dir

    # ④ 編集
    final = edit_final(brief, clips, run_dir, voiceover=vo_path)
    run.state["final"] = str(final)
    run.save()
    print(f"\n✅ 完成: {final}  ({assemble.probe_duration(final):.1f}s)")
    return run_dir


def edit_final(
    brief: Brief,
    clips: list[assemble.ShotClip],
    run_dir: Path,
    *,
    voiceover: Path | None = None,
) -> Path:
    """尺調整 → 連結 → 字幕 → 音声ミックス → 入稿用書き出し。"""
    print("\n■ ffmpeg で編集中…")
    work = run_dir / "work"
    normalized = [
        assemble.normalize_clip(c.path, work / f"n{i:02d}.mp4", brief.preset, c.seconds)
        for i, c in enumerate(clips, 1)
    ]
    merged = assemble.concat(normalized, work / "merged.mp4", work)

    if brief.subtitles and any(c.caption for c in clips):
        # .srt は配信面へのキャプション入稿用に残し、焼き込みは .ass で行う
        assemble.write_srt(clips, run_dir / "final" / f"{brief.name}.srt")
        ass = assemble.write_ass(clips, work / "captions.ass", brief.preset, font=brief.font)
        merged = assemble.burn_subtitles(merged, ass, work / "subbed.mp4")

    bgm_path = None
    if brief.bgm.get("path"):
        p = Path(brief.bgm["path"])
        bgm_path = p if p.exists() else None
        if not bgm_path:
            print(f"  ⚠ BGM が見つかりません: {p}")

    mixed = assemble.mux_audio(
        merged,
        work / "mixed.mp4",
        voiceover=voiceover,
        bgm=bgm_path,
        bgm_gain_db=float(brief.bgm.get("gain_db", -18)),
    )
    return assemble.finalize(
        mixed, run_dir / "final" / f"{brief.name}_{brief.preset.key}.mp4"
    )
