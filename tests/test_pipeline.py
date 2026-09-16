"""オフラインの自己診断テスト（API を呼ばない）。

    python3 -m unittest discover -s tests -v

ffmpeg で合成した映像を素材に、編集パイプラインが実際に
「指定解像度・指定尺・字幕入り・音声付き」の mp4 を吐けるかを検証する。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minimax_ads import assemble, storyboard  # noqa: E402
from minimax_ads.api import MinimaxClient  # noqa: E402
from minimax_ads.config import Settings  # noqa: E402
from minimax_ads.presets import get as get_preset  # noqa: E402

HAS_FFMPEG = assemble.ffmpeg_available()


def make_clip(path: Path, size: str, seconds: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", str(path)],
        check=True,
    )


def make_audio(path: Path, seconds: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libmp3lame", "-loglevel", "error", str(path)],
        check=True,
    )


BRIEF = {
    "name": "selftest",
    "preset": "meta_reels_9x16",
    "style": "test",
    "subtitles": True,
    "shots": [
        {"id": "s1", "seconds": 4, "image_prompt": "a", "motion_prompt": "b", "caption": "テスト字幕１"},
        {"id": "s2", "seconds": 6, "image_prompt": "a", "motion_prompt": "b", "caption": "テスト字幕２"},
        {"id": "s3", "seconds": 5, "image_prompt": "a", "motion_prompt": "b", "caption": "テスト字幕３"},
    ],
}


class TestBrief(unittest.TestCase):
    def test_sample_briefs_are_valid(self):
        for p in (Path(__file__).parent.parent / "briefs").glob("*.json"):
            with self.subTest(brief=p.name):
                brief = storyboard.load_brief(p)
                self.assertEqual([], storyboard.validate_brief(brief), f"{p.name} に警告があります")

    def test_gen_seconds_rounds_up_to_api_units(self):
        brief = storyboard.Brief(name="x", preset=get_preset("meta_reels_9x16"), shots=[])
        self.assertEqual(6, storyboard.Shot("s", 4).gen_seconds)
        self.assertEqual(6, storyboard.Shot("s", 6).gen_seconds)
        self.assertEqual(10, storyboard.Shot("s", 7).gen_seconds)
        self.assertIsNotNone(brief)


class TestDryRun(unittest.TestCase):
    """API キー無しでもリクエスト組み立てが通ることを確認する。"""

    def test_storyboard_dry_run_generates_material(self):
        settings = Settings(api_key="", group_id="", region="global",
                            base_url="https://api.minimax.io/v1", timeout=10,
                            max_retries=0, out_dir=Path("out"))
        client = MinimaxClient(settings, dry_run=True)
        with tempfile.TemporaryDirectory() as td:
            brief_path = Path(td) / "b.json"
            brief_path.write_text(json.dumps(BRIEF, ensure_ascii=False), encoding="utf-8")
            brief = storyboard.load_brief(brief_path)
            run_dir = storyboard.run_storyboard(
                client, brief, Path(td) / "out", skip_assemble=True
            )
            self.assertTrue((run_dir / "run.json").exists())
            self.assertEqual(3, len(list((run_dir / "clips").glob("*.mp4"))))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg 未インストール")
class TestAssemble(unittest.TestCase):
    def test_final_matches_preset_and_duration(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            brief_path = Path(td) / "b.json"
            brief_path.write_text(json.dumps(BRIEF, ensure_ascii=False), encoding="utf-8")
            brief = storyboard.load_brief(brief_path)

            clips = []
            for shot in brief.shots:
                p = run_dir / "clips" / f"{shot.id}.mp4"
                make_clip(p, "1280x720", 6)
                clips.append(assemble.ShotClip(p, shot.seconds, shot.caption))
            vo = run_dir / "audio" / "voiceover.mp3"
            make_audio(vo, 12)

            if not assemble.cjk_font_available():
                self.skipTest("日本語フォント未インストール")

            final = storyboard.edit_final(brief, clips, run_dir, voiceover=vo)
            self.assertTrue(final.exists())
            self.assertAlmostEqual(15.0, assemble.probe_duration(final), delta=0.2)
            self.assertTrue(assemble.has_audio(final))

            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "json", str(final)],
                capture_output=True, text=True,
            )
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual((1080, 1920), (stream["width"], stream["height"]))
            self.assertTrue((run_dir / "final" / "selftest.srt").exists())

    def test_ass_places_captions_inside_safe_area(self):
        preset = get_preset("meta_reels_9x16")
        clips = [assemble.ShotClip(Path("x.mp4"), 4, "テスト")]
        with tempfile.TemporaryDirectory() as td:
            ass = assemble.write_ass(clips, Path(td) / "c.ass", preset)
            body = ass.read_text(encoding="utf-8")
            self.assertIn(f"PlayResY: {preset.height}", body)
            self.assertIn(f",{preset.safe_area['bottom']},1", body)  # MarginV


if __name__ == "__main__":
    unittest.main()
