"""ナレーション音声生成（T2A v2 / speech-02）。広告のボイスオーバー用。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import assemble
from .api import MinimaxClient, MinimaxError
from .config import DEFAULT_TTS_MODEL, EP_T2A

# 日本語ナレーションで使いやすいプリセットボイス。
# 実際に使えるIDはアカウント/リージョンで異なるため、コンソールで確認して増やす。
# 多言語モデルのため、漢字のみの短いフレーズは中国語として読まれることがある。
# 日本語であることを明示して防ぐ（実 API で "Japanese" が受理されることを確認済み）。
DEFAULT_LANGUAGE_BOOST = "Japanese"

JA_VOICES = {
    "female_calm": "Japanese_CalmLady",
    "female_bright": "Japanese_KindLady",
    "male_calm": "Japanese_IntellectualSenior",
    "male_strong": "Japanese_DecisivePrincess",
}


def synthesize(
    client: MinimaxClient,
    text: str,
    dest: Path,
    *,
    voice_id: str = JA_VOICES["female_calm"],
    model: str = DEFAULT_TTS_MODEL,
    speed: float = 1.0,
    volume: float = 1.0,
    pitch: int = 0,
    emotion: str | None = None,
    language_boost: str | None = DEFAULT_LANGUAGE_BOOST,
    audio_format: str = "mp3",
    sample_rate: int = 32000,
    bitrate: int = 128000,
) -> Path:
    """テキストから音声を生成してファイルに保存する。"""
    voice_setting: dict = {
        "voice_id": voice_id,
        "speed": speed,
        "vol": volume,
        "pitch": pitch,
    }
    if emotion:
        voice_setting["emotion"] = emotion

    body = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": voice_setting,
        "audio_setting": {
            "sample_rate": sample_rate,
            "bitrate": bitrate,
            "format": audio_format,
            "channel": 1,
        },
    }
    if language_boost:
        # 漢字だけの短いテキストは中国語と判定されることがある。明示して防ぐ。
        body["language_boost"] = language_boost

    payload = client.request("POST", EP_T2A, body=body, with_group_id=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if payload.get("_dry_run"):
        dest.write_bytes(b"")
        return dest

    hex_audio = (payload.get("data") or {}).get("audio")
    if not hex_audio:
        raise MinimaxError(f"音声データが返りませんでした: {payload}")
    dest.write_bytes(bytes.fromhex(hex_audio))
    return dest


@dataclass
class Segment:
    """フレーズ単位の読み上げ指定。

    t2a_v2 の pitch / speed は文章全体にしか効かないため、
    一部のフレーズだけ音程や速度を変えたいときはフレーズを分けて合成する。
    """

    text: str
    pitch: int = 0                # このフレーズだけの音程
    speed: float | None = None    # None なら全体の speed を使う
    pause_after: float = 0.0      # このフレーズの後ろに入れる無音（秒）


def synthesize_segments(
    client: MinimaxClient,
    segments: list[Segment],
    dest: Path,
    *,
    voice_id: str = JA_VOICES["female_calm"],
    model: str = DEFAULT_TTS_MODEL,
    speed: float = 1.0,
    volume: float = 1.0,
    emotion: str | None = None,
    language_boost: str | None = DEFAULT_LANGUAGE_BOOST,
    work_dir: Path | None = None,
) -> Path:
    """フレーズごとに合成し、無音を挟んで連結する。

    「この語だけ低く」「ここで切る」といった、文章全体への指定では表現できない
    読み方を作るためのもの。

    **限界**: フレーズを別録りして繋ぐため、一息で読んだときの句間の
    イントネーションの連続性は失われる。切れ目を意図的に作りたい箇所にだけ使うこと。
    全体を自然に読ませたいなら `synthesize()` を使う。

    **注意**: 漢字だけの短いセグメント（例「集客支援、」）は言語判定の手がかりが無く、
    中国語として読まれることがある。`language_boost` で防いでいるが、
    各セグメントに仮名を含めておくとより確実。
    """
    if not segments:
        raise MinimaxError("segments が空です")

    with tempfile.TemporaryDirectory() as td:
        work = work_dir or Path(td)
        work.mkdir(parents=True, exist_ok=True)
        parts: list[Path] = []
        for i, seg in enumerate(segments, 1):
            raw = work / f"seg{i:02d}_raw.mp3"
            synthesize(
                client, seg.text, raw,
                voice_id=voice_id, model=model,
                speed=seg.speed if seg.speed is not None else speed,
                volume=volume, pitch=seg.pitch, emotion=emotion,
                language_boost=language_boost,
            )
            if client.dry_run:
                parts.append(raw)
                continue
            parts.append(assemble.strip_silence(raw, work / f"seg{i:02d}.mp3"))

        if client.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"")
            return dest

        return assemble.concat_audio(parts, dest, [s.pause_after for s in segments])


def segments_from_json(data: list[dict]) -> list[Segment]:
    """JSON（辞書のリスト）を Segment に変換する。"""
    out = []
    for i, d in enumerate(data, 1):
        if "text" not in d:
            raise MinimaxError(f"segments[{i - 1}] に text がありません")
        out.append(Segment(
            text=d["text"],
            pitch=int(d.get("pitch", 0)),
            speed=float(d["speed"]) if d.get("speed") is not None else None,
            pause_after=float(d.get("pause_after", 0.0)),
        ))
    return out
