"""CLI エントリポイント:  python3 -m minimax_ads <command>"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import assemble, audio, images, storyboard, talk, video
from .api import MinimaxClient, MinimaxError
from .config import (
    BASE_URLS,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TALK_MODEL,
    DEFAULT_TTS_MODEL,
    DEFAULT_VIDEO_MODEL,
    IMAGE_ASPECT_RATIOS,
    VIDEO_MODEL_LIMITS,
    load_settings,
)
from .presets import PRESETS, get as get_preset


def make_client(args) -> MinimaxClient:
    s = load_settings()
    if getattr(args, "out", None):
        s.out_dir = Path(args.out)
    return MinimaxClient(s, dry_run=getattr(args, "dry_run", False), verbose=getattr(args, "verbose", False))


# ---------------- commands ----------------

def cmd_doctor(args) -> int:
    s = load_settings()
    print("■ 設定")
    print(f"  region        : {s.region}  ({'既知' if s.region in BASE_URLS else '不明なリージョン'})")
    print(f"  base_url      : {s.base_url}")
    print(f"  MINIMAX_API_KEY : {'設定済み (' + s.api_key[:6] + '…' + s.api_key[-4:] + ')' if s.has_key else '❌ 未設定'}")
    print(f"  MINIMAX_GROUP_ID: {s.group_id or '❌ 未設定（動画DL・音声合成で必要）'}")
    print(f"  out_dir       : {s.out_dir}")
    print("\n■ ローカル依存")
    print(f"  python        : {sys.version.split()[0]}")
    print(f"  ffmpeg/ffprobe: {'OK' if assemble.ffmpeg_available() else '❌ 未インストール（編集機能が使えません）'}")
    fonts = assemble.ja_fonts()
    print(f"  日本語フォント  : {assemble.pick_font() + f' ほか{len(fonts)}件' if fonts else '❌ なし（字幕が空白になります）'}")

    if not s.has_key:
        print("\n→ .env.example をコピーして .env を作り、APIキーを設定してください。")
        return 1

    print("\n■ 疎通確認（image_generation に最小リクエスト）")
    client = MinimaxClient(s)
    try:
        urls = images.generate_images(client, "a plain white background, product photography", n=1, aspect_ratio="1:1")
        print(f"  OK: {urls[0][:80]}…")
        return 0
    except MinimaxError as e:
        print(f"  ❌ {e}")
        return 1


def cmd_presets(args) -> int:
    for p in PRESETS.values():
        print(f"\n● {p.key}\n  {p.label} — {p.placements}")
        print(f"  出力       : {p.width}x{p.height} / 画像 {p.image_aspect} / 動画 {p.video_resolution}")
        print(f"  推奨尺     : {p.default_seconds}s（上限 {p.max_seconds}s）")
        if p.notes:
            print(f"  メモ       : {p.notes}")
    return 0


def cmd_image(args) -> int:
    client = make_client(args)
    aspect = args.aspect
    if args.preset:
        aspect = get_preset(args.preset).image_aspect
    out_dir = Path(args.out) if args.out else client.s.out_dir / "images"
    paths = images.generate_and_save(
        client, args.prompt, out_dir,
        stem=args.name,
        aspect_ratio=aspect, n=args.n, model=args.model,
        prompt_optimizer=not args.no_optimize,
        subject_reference=args.reference,
        response_format=args.response_format,
        force=args.force,
    )
    for p in paths:
        print(p)
    return 0


def cmd_video(args) -> int:
    client = make_client(args)
    resolution = args.resolution
    if args.preset and not args.resolution:
        resolution = get_preset(args.preset).video_resolution
    dest = Path(args.out) if args.out else client.s.out_dir / "videos" / f"{args.name}.mp4"

    if args.no_wait:
        task_id = video.submit(
            client, args.prompt, model=args.model, duration=args.duration,
            resolution=resolution or "1080P", first_frame=args.first_frame,
            prompt_optimizer=not args.no_optimize, force=args.force,
        )
        print(task_id)
        print(f"→ 進捗確認: python3 -m minimax_ads task {task_id}")
        return 0

    path = video.generate_and_save(
        client, args.prompt, dest,
        model=args.model, duration=args.duration,
        resolution=resolution or "1080P", first_frame=args.first_frame,
        prompt_optimizer=not args.no_optimize, force=args.force,
        interval=args.interval,
    )
    if args.trim:
        raw = path.with_name(f"{path.stem}_raw{path.suffix}")
        path.replace(raw)
        path = assemble.trim(raw, dest, args.trim)
        print(f"  {args.trim}s にトリム（生成元 {args.duration}s: {raw}）")
    print(path)
    return 0


def cmd_talk(args) -> int:
    """アバター画像 + 原稿 → 口が同期した話者動画（MiniMax-H3 / v2 API）。"""
    client = make_client(args)
    out_root = Path(args.out) if args.out else client.s.out_dir / "talk"
    out_root.mkdir(parents=True, exist_ok=True)

    # 1) ナレーション音声（--audio で既存ファイルを使い回せる）
    if args.audio:
        voice_path = Path(args.audio)
        if not voice_path.exists():
            raise MinimaxError(f"音声が見つかりません: {voice_path}")
        print(f"■ 音声: 既存を使用 {voice_path}")
    else:
        script = Path(args.script_file).read_text(encoding="utf-8").strip() if args.script_file else args.script
        if not script:
            raise MinimaxError("--script か --script-file か --audio のいずれかが必要です")
        voice_path = out_root / f"{args.name}_voice.mp3"
        print("■ ナレーション生成中…")
        audio.synthesize(
            client, script, voice_path,
            voice_id=audio.JA_VOICES.get(args.voice, args.voice),
            speed=args.speed, emotion=args.emotion,
        )
        print(f"  {voice_path}")

    # 2) 尺は音声に合わせる（H3 は 4〜15 秒）
    duration = args.duration
    if duration is None:
        duration = talk.duration_for_audio(voice_path) if not client.dry_run else 6
        print(f"■ 尺: 音声に合わせて {duration}s")

    # 3) H3 に投げる
    print(f"■ 動画生成中…（{args.model} / {duration}s / {args.resolution}）")
    task_id = talk.submit(
        client, args.prompt,
        model=args.model, duration=duration, resolution=args.resolution,
        ratio=args.ratio, reference_image=args.image,
        reference_audio=str(voice_path), force=args.force,
    )
    if args.no_wait:
        print(task_id)
        return 0

    url = talk.wait_for(client, task_id, interval=args.interval)
    raw = out_root / f"{args.name}_raw.mp4"
    client.download(url, raw)
    print(f"  {raw}")

    # 4) 配信面のサイズにそろえる
    dest = out_root / f"{args.name}.mp4"
    if args.preset and not client.dry_run:
        preset = get_preset(args.preset)
        assemble.run([
            "ffmpeg", "-y", "-i", str(raw),
            "-vf", f"scale={preset.width}:{preset.height}:force_original_aspect_ratio=increase,"
                   f"crop={preset.width}:{preset.height},fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest),
        ])
        print(f"■ {preset.label} にリサイズ")
    else:
        raw.replace(dest) if not client.dry_run else dest.write_bytes(b"")
    print(dest)
    return 0


def cmd_task(args) -> int:
    client = make_client(args)
    if args.wait:
        file_id = video.wait_for(client, args.task_id, interval=args.interval,
                                 on_tick=lambda s, e: print(f"  [{e:>4}s] {s}"))
        dest = Path(args.out) if args.out else client.s.out_dir / "videos" / f"{args.task_id}.mp4"
        print(client.download(client.file_download_url(file_id), dest))
        return 0
    print(json.dumps(video.query(client, args.task_id), ensure_ascii=False, indent=2))
    return 0


def cmd_fetch(args) -> int:
    client = make_client(args)
    url = client.file_download_url(args.file_id)
    dest = Path(args.out) if args.out else client.s.out_dir / "videos" / f"{args.file_id}.mp4"
    print(client.download(url, dest))
    return 0


def cmd_voice(args) -> int:
    client = make_client(args)
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    if not text:
        raise MinimaxError("--text または --file でナレーション原稿を指定してください")
    dest = Path(args.out) if args.out else client.s.out_dir / "audio" / f"{args.name}.mp3"
    path = audio.synthesize(
        client, text, dest,
        voice_id=audio.JA_VOICES.get(args.voice, args.voice),
        model=args.model, speed=args.speed, emotion=args.emotion,
    )
    print(path)
    return 0


def cmd_voices(args) -> int:
    print("よく使う日本語ボイス（--voice に別名かIDを指定）:")
    for alias, vid in audio.JA_VOICES.items():
        print(f"  {alias:<16} {vid}")
    print("\n※ 利用可能なボイスIDはアカウントとリージョンで異なります。")
    print("  MiniMax コンソールの Voice 一覧で確認し minimax_ads/audio.py の JA_VOICES に追記してください。")
    return 0


def cmd_storyboard(args) -> int:
    client = make_client(args)
    brief = storyboard.load_brief(Path(args.brief))
    warnings = storyboard.validate_brief(brief)

    print(f"■ {brief.name} / {brief.preset.label}")
    print(f"  カット数 {len(brief.shots)} / 合計 {brief.total_seconds:.0f}s")
    for s in brief.shots:
        print(f"   - {s.id}: {s.seconds:>4.1f}s (生成 {s.gen_seconds}s)  {s.caption or s.motion_prompt[:40]}")
    est_img = sum(1 for s in brief.shots if s.use_keyframe and not s.keyframe)
    est_vid_s = sum(s.gen_seconds for s in brief.shots)
    print(f"  API呼び出し見込み: 画像 {est_img}枚 / 動画 {len(brief.shots)}本 計{est_vid_s}秒"
          + (" / ナレーション 1本" if brief.voiceover.get("enabled") else ""))
    for w in warnings:
        print(f"  ⚠ {w}")
    if args.check:
        return 1 if warnings else 0
    if warnings and not args.force:
        print("\n警告があります。--force で強行、または brief を修正してください。")
        return 1

    out_root = Path(args.out) if args.out else client.s.out_dir
    storyboard.run_storyboard(
        client, brief, out_root,
        resume=args.resume, skip_video=args.skip_video,
        skip_assemble=args.skip_assemble, poll_interval=args.interval,
        force=args.force,
    )
    return 0


def cmd_assemble(args) -> int:
    """既存の run ディレクトリ（または任意のクリップ群）から編集だけやり直す。"""
    brief = storyboard.load_brief(Path(args.brief))
    run_dir = Path(args.run_dir)
    clips = []
    for shot in brief.shots:
        p = run_dir / "clips" / f"{shot.id}.mp4"
        if not p.exists():
            raise MinimaxError(f"クリップがありません: {p}")
        clips.append(assemble.ShotClip(p, shot.seconds, shot.caption))

    vo = run_dir / "audio" / "voiceover.mp3"
    final = storyboard.edit_final(
        brief, clips, run_dir, voiceover=vo if vo.exists() else None
    )
    print(final)
    return 0


def cmd_models(args) -> int:
    print(f"画像既定モデル: {DEFAULT_IMAGE_MODEL}  (aspect_ratio: {', '.join(IMAGE_ASPECT_RATIOS)})")
    print(f"音声既定モデル: {DEFAULT_TTS_MODEL}")
    print(f"動画既定モデル: {DEFAULT_VIDEO_MODEL}\n")
    for name, lim in VIDEO_MODEL_LIMITS.items():
        bad = "".join(f" / 非対応: {d}s+{r}" for d, r in lim["invalid_combos"])
        print(f"  {name:<20} duration={lim['durations']} resolution={lim['resolutions']}"
              f" first_frame={'○' if lim['supports_first_frame'] else '×'}{bad}")
    return 0


# ---------------- parser ----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m minimax_ads",
        description="MiniMax API で Meta / YouTube 広告用の静止画・動画を作る",
    )
    p.add_argument("--dry-run", action="store_true", help="APIを呼ばずリクエスト内容だけ表示")
    p.add_argument("--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("doctor", help="設定と疎通を確認")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("presets", help="広告フォーマットのプリセット一覧")
    sp.set_defaults(func=cmd_presets)

    sp = sub.add_parser("models", help="モデルと制約の一覧")
    sp.set_defaults(func=cmd_models)

    sp = sub.add_parser("image", help="静止画を生成")
    sp.add_argument("prompt")
    sp.add_argument("--preset", choices=list(PRESETS), help="指定するとアスペクト比を自動設定")
    sp.add_argument("--aspect", default="9:16", choices=IMAGE_ASPECT_RATIOS)
    sp.add_argument("-n", type=int, default=1, help="生成枚数 1-9")
    sp.add_argument("--name", default="image", help="ファイル名のベース")
    sp.add_argument("--reference", help="人物の一貫性を保つ参照画像（パス or URL）")
    sp.add_argument("--model", default=DEFAULT_IMAGE_MODEL)
    sp.add_argument(
        "--format", dest="response_format", default="url", choices=["url", "base64"],
        help="base64 にすると生成物CDNを経由せずAPI応答から直接保存する",
    )
    sp.add_argument("--no-optimize", action="store_true", help="prompt_optimizer を無効化")
    sp.add_argument("--out", help="出力先ディレクトリ")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_image)

    sp = sub.add_parser("video", help="動画を生成")
    sp.add_argument("prompt")
    sp.add_argument("--first-frame", help="起点となる画像（縦型はこれで比率が決まる）")
    sp.add_argument("--preset", choices=list(PRESETS))
    sp.add_argument("--duration", type=int, default=6, choices=[6, 10], help="生成尺（API の最短は6秒）")
    sp.add_argument("--trim", type=float, help="生成後に先頭から指定秒で切り出す（例: 3）")
    sp.add_argument("--resolution", choices=["512P", "720P", "768P", "1080P"])
    sp.add_argument("--model", default=DEFAULT_VIDEO_MODEL)
    sp.add_argument("--name", default="video")
    sp.add_argument("--no-optimize", action="store_true")
    sp.add_argument("--no-wait", action="store_true", help="task_id だけ返して終了")
    sp.add_argument("--interval", type=int, default=10, help="ポーリング間隔(秒)")
    sp.add_argument("--out", help="出力ファイルパス")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_video)

    sp = sub.add_parser("talk", help="アバター画像+原稿から口が同期した話者動画（H3）")
    sp.add_argument("--image", required=True, help="話者の参照画像（256〜5760px, 比0.4〜2.5）")
    sp.add_argument("--script", help="ナレーション原稿（日本語）")
    sp.add_argument("--script-file", help="原稿をファイルから読む")
    sp.add_argument("--audio", help="既存のナレーション音声を使う（TTSをスキップ）")
    sp.add_argument("--prompt", default=(
        "A person speaks directly to the camera in a calm, friendly manner, "
        "natural lip movement synchronized to the speech, subtle head motion and blinking, "
        "static background, no text, no lettering, no watermark, no logo"),
        help="H3 への映像指示（英語）。H3 はテキスト必須")
    sp.add_argument("--voice", default="male_calm", help="ボイス別名かID（./bin/mmx voices）")
    sp.add_argument("--speed", type=float, default=1.0)
    sp.add_argument("--emotion", default=None)
    sp.add_argument("--duration", type=int, default=None, help="4〜15秒。既定は音声尺に自動追従")
    sp.add_argument("--resolution", default="768P", choices=["480P", "768P", "2K"])
    sp.add_argument("--ratio", default="adaptive", help="既定 adaptive（参照画像の比率に従う）")
    sp.add_argument("--preset", choices=list(PRESETS), help="最終的に合わせる配信面サイズ")
    sp.add_argument("--model", default=DEFAULT_TALK_MODEL)
    sp.add_argument("--name", default="talk")
    sp.add_argument("--no-wait", action="store_true")
    sp.add_argument("--interval", type=int, default=10)
    sp.add_argument("--out", help="出力ディレクトリ")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_talk)

    sp = sub.add_parser("task", help="動画タスクの状態確認 / 完了待ち")
    sp.add_argument("task_id")
    sp.add_argument("--wait", action="store_true")
    sp.add_argument("--interval", type=int, default=10)
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_task)

    sp = sub.add_parser("fetch", help="file_id から動画をダウンロード")
    sp.add_argument("file_id")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("voice", help="ナレーション音声を生成")
    sp.add_argument("--text")
    sp.add_argument("--file", help="原稿テキストファイル")
    sp.add_argument("--voice", default="female_calm")
    sp.add_argument("--model", default=DEFAULT_TTS_MODEL)
    sp.add_argument("--speed", type=float, default=1.0)
    sp.add_argument("--emotion", help="happy / sad / neutral など")
    sp.add_argument("--name", default="voiceover")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_voice)

    sp = sub.add_parser("voices", help="日本語ボイスの別名一覧")
    sp.set_defaults(func=cmd_voices)

    sp = sub.add_parser("storyboard", help="brief JSON から広告動画を一気通貫で生成")
    sp.add_argument("brief")
    sp.add_argument("--check", action="store_true", help="内容の検証のみ（API を呼ばない）")
    sp.add_argument("--resume", action="store_true", help="直近の run を再開")
    sp.add_argument("--skip-video", action="store_true", help="キーフレームだけ作る（絵の確認用）")
    sp.add_argument("--skip-assemble", action="store_true", help="素材生成のみ、編集しない")
    sp.add_argument("--interval", type=int, default=10)
    sp.add_argument("--out", help="出力ルート（既定: out/）")
    sp.add_argument("--force", action="store_true", help="警告を無視して実行")
    sp.set_defaults(func=cmd_storyboard)

    sp = sub.add_parser("assemble", help="生成済み素材から編集だけやり直す")
    sp.add_argument("brief")
    sp.add_argument("run_dir")
    sp.set_defaults(func=cmd_assemble)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (MinimaxError, assemble.FFmpegMissing, KeyError, RuntimeError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n中断しました。--resume で再開できます。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
