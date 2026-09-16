"""話者動画（talking head）生成。MiniMax-H3 / v2 API。

Hailuo-02 系（v1）の I2V は「動く」だけで、ナレーションと口は同期しない。
H3 は映像と音声を同一の潜在表現から生成するため、`reference_audio` を渡すと
口の動きがその音声に同期する。プロトコルが v1 と別物なので独立モジュールにしてある。

    POST {api_root}/v2/video_generation
    GET  {api_root}/v2/query/video_generation/{task_id}
"""

from __future__ import annotations

import base64
import math
import mimetypes
import time
from pathlib import Path

from .api import MinimaxClient, MinimaxError
from .config import (
    DEFAULT_TALK_MODEL,
    EP_V2_VIDEO,
    EP_V2_VIDEO_QUERY,
    H3_IMAGE_MAX_PX,
    H3_IMAGE_MAX_RATIO,
    H3_IMAGE_MIN_PX,
    H3_IMAGE_MIN_RATIO,
    VIDEO_MODEL_LIMITS,
)

# v2 は "succeeded" / "failed" を返す（v1 の "Success" / "Fail" とは別表記）。
# 表記ゆれで無限待ちにならないよう、小文字化して比較する。
TERMINAL_OK = {"success", "succeeded"}
TERMINAL_NG = {"fail", "failed", "failure", "error"}

# H3 の尺は 4〜15 秒の整数
MIN_DURATION = 4
MAX_DURATION = 15


# API は data URI の MIME から拡張子を復元して検証する。
# mimetypes は .mp3 -> "audio/mpeg" を返すが、H3 は ".mpeg" を弾く（status_code 2013）ため、
# 拡張子とサブタイプが一致する形に明示的に寄せる。
EXPLICIT_MIME = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/m4a",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}


def media_ref(value: str, *, fallback_mime: str) -> str:
    """URL ならそのまま、ローカルパスなら data URI に変換する。"""
    if value.startswith(("http://", "https://", "data:")):
        return value
    p = Path(value)
    if not p.exists():
        raise MinimaxError(f"ファイルが見つかりません: {value}")
    mime = EXPLICIT_MIME.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or fallback_mime
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def validate_image(path: Path) -> None:
    """H3 の参照画像要件（256〜5760px / 比 0.4〜2.5）を送信前に確認する。"""
    from .assemble import probe_size  # 循環 import を避けるため遅延

    w, h = probe_size(path)
    for side, px in (("幅", w), ("高さ", h)):
        if not (H3_IMAGE_MIN_PX <= px <= H3_IMAGE_MAX_PX):
            raise MinimaxError(
                f"参照画像の{side} {px}px が H3 の範囲外です"
                f"（{H3_IMAGE_MIN_PX}〜{H3_IMAGE_MAX_PX}px）: {path}"
            )
    ratio = w / h
    if not (H3_IMAGE_MIN_RATIO <= ratio <= H3_IMAGE_MAX_RATIO):
        raise MinimaxError(
            f"参照画像のアスペクト比 {ratio:.2f} が H3 の範囲外です"
            f"（{H3_IMAGE_MIN_RATIO}〜{H3_IMAGE_MAX_RATIO}）: {path}"
        )


def duration_for_audio(audio: Path, *, headroom: float = 0.4) -> int:
    """音声尺に合わせて H3 の duration（整数秒）を決める。"""
    from .assemble import probe_duration

    secs = probe_duration(audio) + headroom
    return max(MIN_DURATION, min(MAX_DURATION, math.ceil(secs)))


def validate(model: str, duration: int, resolution: str) -> None:
    limits = VIDEO_MODEL_LIMITS.get(model)
    if not limits:
        return  # 未知のモデルはそのまま送る
    if duration not in limits["durations"]:
        raise MinimaxError(
            f"{model} の duration は {limits['durations'][0]}〜{limits['durations'][-1]} 秒です（指定: {duration}）"
        )
    if resolution not in limits["resolutions"]:
        raise MinimaxError(
            f"{model} の resolution は {limits['resolutions']} のみ対応です（指定: {resolution}）"
        )


def build_content(
    prompt: str,
    *,
    reference_image: str | None = None,
    reference_audio: str | None = None,
    first_frame: str | None = None,
) -> list[dict]:
    """v2 の content[] を組み立てる。

    `first_frame`（フレーム条件づけ）と `reference_*`（参照生成）は
    API 側で排他なので、混ぜて渡された場合はここで弾く。
    """
    if first_frame and (reference_image or reference_audio):
        raise MinimaxError(
            "first_frame と reference_image/reference_audio は同時に使えません"
            "（API 側で排他。リップシンクしたい場合は reference 系を使う）"
        )
    if not prompt.strip():
        raise MinimaxError("H3 はテキスト指示が必須です（prompt が空）")

    content: list[dict] = [{"type": "text", "text": prompt}]
    if first_frame:
        content.append({
            "type": "image_url",
            "image_url": {"url": media_ref(first_frame, fallback_mime="image/jpeg")},
            "role": "first_frame",
        })
    if reference_image:
        content.append({
            "type": "image_url",
            "image_url": {"url": media_ref(reference_image, fallback_mime="image/jpeg")},
            "role": "reference_image",
        })
    if reference_audio:
        content.append({
            "type": "audio_url",
            "audio_url": {"url": media_ref(reference_audio, fallback_mime="audio/mp3")},
            "role": "reference_audio",
        })
    return content


def submit(
    client: MinimaxClient,
    prompt: str,
    *,
    model: str = DEFAULT_TALK_MODEL,
    duration: int = 6,
    resolution: str = "768P",
    ratio: str = "adaptive",
    reference_image: str | None = None,
    reference_audio: str | None = None,
    first_frame: str | None = None,
    force: bool = False,
) -> str:
    if not force:
        validate(model, duration, resolution)
        for ref in (reference_image, first_frame):
            if ref and not ref.startswith(("http://", "https://", "data:")):
                validate_image(Path(ref))

    body = {
        "model": model,
        "content": build_content(
            prompt,
            reference_image=reference_image,
            reference_audio=reference_audio,
            first_frame=first_frame,
        ),
        "duration": duration,
        "resolution": resolution,
        "ratio": ratio,
    }
    payload = client.request("POST", EP_V2_VIDEO, body=body)
    if payload.get("_dry_run"):
        return "dry-run-task-id"
    task_id = payload.get("task_id") or (payload.get("task") or {}).get("id")
    if not task_id:
        raise MinimaxError(f"task_id が返りませんでした: {payload}")
    return task_id


def query(client: MinimaxClient, task_id: str) -> dict:
    payload = client.request("GET", EP_V2_VIDEO_QUERY.format(task_id=task_id))
    if payload.get("_dry_run"):
        return {"task": {"status": "Success", "content": {"url": "https://example.invalid/dry-run.mp4"}}}
    return payload


def wait_for(
    client: MinimaxClient,
    task_id: str,
    *,
    interval: int = 10,
    timeout: int = 1800,
    verbose: bool = True,
) -> str:
    """完了まで待ち、動画の URL を返す。"""
    waited = 0
    while True:
        payload = query(client, task_id)
        task = payload.get("task") or payload
        status = str(task.get("status", "")).lower()
        if status in TERMINAL_OK:
            url = ((task.get("content") or {}).get("url")) or task.get("video_url")
            if not url:
                raise MinimaxError(f"完了しましたが URL がありません: {payload}")
            return url
        if status in TERMINAL_NG:
            raise MinimaxError(f"生成に失敗しました: {payload}")
        if waited >= timeout:
            raise MinimaxError(f"タイムアウト（{timeout}s）。task_id={task_id} は後から query 可能です")
        if verbose:
            print(f"  status={status or '(未報告)'} … {waited}s")
        time.sleep(interval)
        waited += interval
