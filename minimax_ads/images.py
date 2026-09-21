"""静止画生成（image-01）。"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from .api import MinimaxClient, MinimaxError
from .config import DEFAULT_IMAGE_MODEL, EP_IMAGE, IMAGE_ASPECT_RATIOS


def to_data_uri(path: Path) -> str:
    """ローカル画像を data URI にする（参照画像の受け渡し用）。"""
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def as_image_ref(value: str) -> str:
    """URL ならそのまま、ローカルパスなら data URI に変換。"""
    if value.startswith(("http://", "https://", "data:")):
        return value
    p = Path(value)
    if not p.exists():
        raise MinimaxError(f"画像が見つかりません: {value}")
    return to_data_uri(p)


def generate_images(
    client: MinimaxClient,
    prompt: str,
    *,
    aspect_ratio: str = "9:16",
    n: int = 1,
    model: str = DEFAULT_IMAGE_MODEL,
    prompt_optimizer: bool = True,
    subject_reference: str | None = None,
    response_format: str = "url",
    force: bool = False,
) -> list[str]:
    """画像を生成し、画像URL（response_format=base64 なら base64 文字列）のリストを返す。"""
    if not force and aspect_ratio not in IMAGE_ASPECT_RATIOS:
        raise MinimaxError(
            f"aspect_ratio={aspect_ratio} は image-01 非対応です。"
            f"利用可能: {', '.join(IMAGE_ASPECT_RATIOS)}（--force で送信は可能）"
        )
    if not force and not 1 <= n <= 9:
        raise MinimaxError("n は 1〜9 の範囲で指定してください")

    body: dict = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": response_format,
        "n": n,
        "prompt_optimizer": prompt_optimizer,
    }
    if subject_reference:
        # 人物・キャラクターの一貫性を保つための参照画像
        body["subject_reference"] = [
            {"type": "character", "image_file": as_image_ref(subject_reference)}
        ]

    payload = client.request("POST", EP_IMAGE, body=body)
    if payload.get("_dry_run"):
        if response_format == "base64":
            return ["" for _ in range(n)]
        return [f"https://example.invalid/dry-run-{i + 1}.jpg" for i in range(n)]

    data = payload.get("data") or {}
    if response_format == "base64":
        # 生成物 CDN を経由せず API 応答から直接受け取る経路。
        # 応答のフィールド名は実 API 未検証のため、候補を順に見る。
        for key in ("image_base64", "image_base64s", "images"):
            blobs = data.get(key) or []
            if blobs:
                return blobs
        raise MinimaxError(f"画像の base64 が返りませんでした: {payload}")

    urls = data.get("image_urls") or []
    if not urls:
        raise MinimaxError(f"画像URLが返りませんでした: {payload}")
    return urls


def decode_image_blob(blob: str) -> bytes:
    """base64 応答を bytes にする。data URI 形式で返ってきても剥がす。"""
    if blob.startswith("data:"):
        blob = blob.split(",", 1)[-1]
    return base64.b64decode(blob)


def generate_and_save(
    client: MinimaxClient,
    prompt: str,
    out_dir: Path,
    *,
    stem: str = "image",
    response_format: str = "url",
    **kwargs,
) -> list[Path]:
    refs = generate_images(client, prompt, response_format=response_format, **kwargs)
    saved = []
    for i, ref in enumerate(refs, 1):
        dest = out_dir / (f"{stem}.jpg" if len(refs) == 1 else f"{stem}_{i:02d}.jpg")
        if response_format == "base64":
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(decode_image_blob(ref))
            saved.append(dest)
        else:
            saved.append(client.download(ref, dest))
    return saved
