---
description: 広告用の静止画バリエーションを生成する
---

「$ARGUMENTS」の静止画を生成してください。

1. 配信面が不明なら `./bin/mmx presets` の中から確認する。
2. プロンプトは英語で、`docs/prompting.md` の構成（被写体+構図+ライティング+質感+色調）に従う。
   `no text, no lettering, no watermark, no logo` を必ず含める。
3. `./bin/mmx image "<prompt>" --preset <key> -n 4 --name <名前>` で複数案を生成する。
4. 生成したファイルパスを一覧で報告する。
