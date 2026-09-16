"""ナレーション音声生成（T2A v2 / speech-02）。広告のボイスオーバー用。"""

from __future__ import annotations

from pathlib import Path

from .api import MinimaxClient, MinimaxError
from .config import DEFAULT_TTS_MODEL, EP_T2A

# 日本語ナレーションで使いやすいプリセットボイス。
# 実際に使えるIDはアカウント/リージョンで異なるため、コンソールで確認して増やす。
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
