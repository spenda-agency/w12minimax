"""広告配信面ごとの出力プリセット（Meta / YouTube）。

image-01 は 4:5 を直接サポートしないため、近いアスペクト比で生成し
ffmpeg 側で最終サイズにクロップして合わせる（crop_to）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    placements: str
    width: int
    height: int
    image_aspect: str          # image-01 に渡す aspect_ratio
    video_resolution: str      # video_generation に渡す resolution
    crop_to: bool              # 生成結果を width x height にクロップし直すか
    default_seconds: int
    max_seconds: int
    notes: str = ""
    safe_area: dict = field(default_factory=dict)  # 上下左右の安全余白(px)


PRESETS: dict[str, Preset] = {
    "meta_reels_9x16": Preset(
        key="meta_reels_9x16",
        label="Meta Reels / Stories (9:16)",
        placements="Facebook Reels, Instagram Reels, Stories",
        width=1080, height=1920, image_aspect="9:16", video_resolution="1080P",
        crop_to=False, default_seconds=15, max_seconds=30,
        notes="音声オフ視聴が多数。冒頭1秒でフックを置き、字幕を必ず焼き込む。",
        safe_area={"top": 250, "bottom": 420, "left": 60, "right": 60},
    ),
    "meta_feed_4x5": Preset(
        key="meta_feed_4x5",
        label="Meta Feed (4:5)",
        placements="Facebook Feed, Instagram Feed",
        width=1080, height=1350, image_aspect="3:4", video_resolution="1080P",
        crop_to=True, default_seconds=15, max_seconds=30,
        notes="3:4 で生成し 4:5 にセンタークロップ。テキスト占有は控えめに。",
        safe_area={"top": 120, "bottom": 180, "left": 60, "right": 60},
    ),
    "meta_feed_1x1": Preset(
        key="meta_feed_1x1",
        label="Meta Feed (1:1)",
        placements="Facebook / Instagram Feed, Audience Network",
        width=1080, height=1080, image_aspect="1:1", video_resolution="1080P",
        crop_to=False, default_seconds=15, max_seconds=30,
        safe_area={"top": 100, "bottom": 100, "left": 60, "right": 60},
    ),
    "youtube_instream_16x9": Preset(
        key="youtube_instream_16x9",
        label="YouTube インストリーム (16:9)",
        placements="YouTube スキップ可能/不可インストリーム, インフィード",
        width=1920, height=1080, image_aspect="16:9", video_resolution="1080P",
        crop_to=False, default_seconds=15, max_seconds=30,
        notes="スキップ可能は5秒でスキップ可。5秒以内にブランドと便益を提示する。",
        safe_area={"top": 60, "bottom": 120, "left": 90, "right": 90},
    ),
    "youtube_shorts_9x16": Preset(
        key="youtube_shorts_9x16",
        label="YouTube ショート (9:16)",
        placements="YouTube Shorts",
        width=1080, height=1920, image_aspect="9:16", video_resolution="1080P",
        crop_to=False, default_seconds=15, max_seconds=30,
        notes="下部にUI要素が重なるため、字幕は下から420px以上空ける。",
        safe_area={"top": 250, "bottom": 420, "left": 60, "right": 60},
    ),
    "youtube_bumper_16x9": Preset(
        key="youtube_bumper_16x9",
        label="YouTube バンパー (16:9 / 6秒)",
        placements="YouTube バンパー広告",
        width=1920, height=1080, image_aspect="16:9", video_resolution="1080P",
        crop_to=False, default_seconds=6, max_seconds=6,
        notes="6秒固定。1カット1メッセージに絞る。",
        safe_area={"top": 60, "bottom": 120, "left": 90, "right": 90},
    ),
}


def get(key: str) -> Preset:
    if key not in PRESETS:
        raise KeyError(f"未知のプリセット: {key}（利用可能: {', '.join(PRESETS)}）")
    return PRESETS[key]
