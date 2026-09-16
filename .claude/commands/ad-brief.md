---
description: 広告の要件をヒアリングして brief JSON を作る
---

ユーザーの依頼「$ARGUMENTS」から、`briefs/` に配置する広告 brief JSON を作成してください。

手順:
1. 不足している情報（配信面、尺、訴求内容、ターゲット、CTA、トーン）を確認する。
   ユーザーが既に指定している項目は聞き直さない。
2. `briefs/SCHEMA.md` と `docs/prompting.md` に従って brief を書く。
   - `image_prompt` / `motion_prompt` は英語、`caption` と `voiceover.script` は日本語
   - 全プロンプトに `no text, no lettering, no watermark, no logo` を含める
   - 各カットは 5〜6 秒で設計する（課金単位が 6 秒のため）
   - `caption` は 20 文字以内、音を消しても意味が通る内容にする
3. `./bin/mmx storyboard briefs/<file>.json --check` を実行し、警告があれば直す。
4. 検証結果（カット数・合計尺・API 呼び出し見込み）を提示し、生成に進んでよいか確認する。
   **確認なしに動画生成（課金）を実行しない。**
