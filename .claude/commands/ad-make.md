---
description: brief から広告動画を生成する（課金あり）
---

`$ARGUMENTS` で指定された brief から広告動画を生成してください。

手順:
1. `./bin/mmx doctor` で API キー・ffmpeg・日本語フォントが揃っているか確認する。
2. `./bin/mmx storyboard <brief> --check` で見積もりを出し、ユーザーに提示して実行の同意を得る。
3. 画の方向性が未確定なら、先に `--skip-video` でキーフレームだけ生成して確認してもらう。
4. 同意が取れたら `./bin/mmx storyboard <brief>` を実行する。数分〜十数分かかる。
5. 完成したら出力パスと尺を報告する。失敗した場合は作り直さず `--resume` で再開する。
