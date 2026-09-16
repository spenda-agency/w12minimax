"""環境設定の読み込みと、モデル/エンドポイントの一元定義。

MiniMax の API はモデル名・パラメータが更新されることがあるため、
仕様依存の値はこのファイルに集約する。仕様変更時はここだけを直す。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# リージョン別 API ルート / ベースURL
API_ROOTS = {
    "global": "https://api.minimax.io",
    "cn": "https://api.minimax.chat",
}
BASE_URLS = {region: root + "/v1" for region, root in API_ROOTS.items()}

# エンドポイント（ベースURLからの相対パス）
EP_IMAGE = "/image_generation"
EP_VIDEO = "/video_generation"
EP_VIDEO_QUERY = "/query/video_generation"
EP_FILE_RETRIEVE = "/files/retrieve"
EP_T2A = "/t2a_v2"

# v2 エンドポイント（MiniMax-H3 系）。base_url ではなく API ルートからの絶対パス。
EP_V2_VIDEO = "/v2/video_generation"
EP_V2_VIDEO_QUERY = "/v2/query/video_generation/{task_id}"

# 既定モデル
DEFAULT_IMAGE_MODEL = "image-01"
DEFAULT_VIDEO_MODEL = "MiniMax-Hailuo-02"
# 音声同期（リップシンク）付きの talking video 用。v2 API / content[] プロトコル。
DEFAULT_TALK_MODEL = "MiniMax-H3"
DEFAULT_TTS_MODEL = "speech-02-hd"

# 動画モデルごとの制約（送信前バリデーション用。--force で無視可）
VIDEO_MODEL_LIMITS = {
    "MiniMax-Hailuo-02": {
        "durations": [6, 10],
        "resolutions": ["512P", "768P", "1080P"],
        # 1080P は 6 秒のみ、512P は 6/10 秒（10秒は768P以下）
        "invalid_combos": [(10, "1080P")],
        "supports_first_frame": True,
    },
    "T2V-01-Director": {
        "durations": [6],
        "resolutions": ["720P"],
        "invalid_combos": [],
        "supports_first_frame": False,
    },
    "I2V-01-Director": {
        "durations": [6],
        "resolutions": ["720P"],
        "invalid_combos": [],
        "supports_first_frame": True,
    },
    "I2V-01-live": {
        "durations": [6],
        "resolutions": ["720P"],
        "invalid_combos": [],
        "supports_first_frame": True,
    },
    "S2V-01": {
        "durations": [6],
        "resolutions": ["720P"],
        "invalid_combos": [],
        "supports_first_frame": False,
    },
    # v2 API。ネイティブ音声つきで生成され、reference_audio を渡すと口が同期する。
    "MiniMax-H3": {
        "durations": list(range(4, 16)),
        "resolutions": ["768P", "2K"],
        "invalid_combos": [],
        "supports_first_frame": True,
    },
    "MiniMax-H3-Max": {
        "durations": list(range(5, 16)),
        "resolutions": ["480P", "768P"],
        "invalid_combos": [],
        "supports_first_frame": True,
    },
}

# v2 の content[] で扱えるメディア要件（送信前チェック用）
H3_IMAGE_MIN_PX = 256
H3_IMAGE_MAX_PX = 5760
H3_IMAGE_MIN_RATIO = 0.4
H3_IMAGE_MAX_RATIO = 2.5

# image-01 が受け付けるアスペクト比
IMAGE_ASPECT_RATIOS = ["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"]

# base_resp.status_code の代表的な意味（エラーメッセージの補足に使う）
STATUS_HINTS = {
    1000: "不明なエラー",
    1001: "タイムアウト",
    1002: "レート制限。リクエスト間隔を空けるか同時実行数を下げる",
    1004: "認証失敗。MINIMAX_API_KEY と MINIMAX_REGION の組み合わせを確認",
    1008: "残高不足。MiniMax コンソールでチャージが必要",
    1013: "内部サービスエラー",
    1026: "入力プロンプトがコンテンツポリシーに抵触",
    1027: "出力がコンテンツポリシーに抵触",
    1039: "トークンレート制限",
    2013: "パラメータ不正",
    2049: "API キーが無効",
}


def load_dotenv(path: Path | None = None) -> None:
    """依存パッケージなしの簡易 .env ローダ。既存の環境変数は上書きしない。"""
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Settings:
    api_key: str
    group_id: str
    region: str
    base_url: str
    timeout: int
    max_retries: int
    out_dir: Path

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    @property
    def api_root(self) -> str:
        """v2 エンドポイント用。base_url からバージョン接尾辞を外した URL。"""
        return re.sub(r"/v[12]/?$", "", self.base_url.rstrip("/"))


def load_settings() -> Settings:
    load_dotenv()
    region = os.environ.get("MINIMAX_REGION", "global").strip().lower()
    base_url = os.environ.get("MINIMAX_BASE_URL", "").strip() or BASE_URLS.get(
        region, BASE_URLS["global"]
    )
    out = os.environ.get("MINIMAX_OUT_DIR", "").strip()
    return Settings(
        api_key=os.environ.get("MINIMAX_API_KEY", "").strip(),
        group_id=os.environ.get("MINIMAX_GROUP_ID", "").strip(),
        region=region,
        base_url=base_url.rstrip("/"),
        timeout=int(os.environ.get("MINIMAX_TIMEOUT", "120")),
        max_retries=int(os.environ.get("MINIMAX_MAX_RETRIES", "4")),
        out_dir=Path(out) if out else REPO_ROOT / "out",
    )
