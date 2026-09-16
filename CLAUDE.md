# CLAUDE.md

このリポジトリは **MiniMax API で Meta / YouTube 広告用の静止画・動画を作る**ためのものです。
ユーザーは Claude Code から自然文で制作を依頼します。

## 依頼への対応方針

1. **brief JSON を作る → `--check` → 実行**、が基本フロー。
   単発の画像・動画依頼以外は `briefs/` に brief を作ってから `storyboard` を回す。
2. **課金が発生する操作の前に必ず見積もりを提示して確認を取る。**
   動画生成は 1 カットずつ課金される。`--check` の出力（カット数・生成秒数）を見せてから実行する。
3. 画の方向性が未確定なら、まず `--skip-video` でキーフレームだけ生成してユーザーに確認してもらう。
4. 失敗・中断時は作り直さず `--resume`。編集のやり直しだけなら `assemble`。

## コマンド

```bash
./bin/mmx doctor                          # 設定・依存・疎通の確認（まずこれ）
./bin/mmx presets                         # 配信面プリセット一覧
./bin/mmx image "<prompt>" --preset <k>   # 静止画
./bin/mmx video "<prompt>" --first-frame <img> --preset <k>
./bin/mmx talk --image <画像> --script "<原稿>" --preset <k>   # 話者動画(リップシンク)
./bin/mmx storyboard briefs/x.json --check
./bin/mmx storyboard briefs/x.json [--skip-video|--resume]
./bin/mmx assemble briefs/x.json out/<run_dir>
```

`--dry-run` を付けると API を呼ばずリクエスト内容だけ表示する。実装の確認にはこれを使う。

## 制作時に必ず守ること

- **「しゃべる動画」は `talk`（MiniMax-H3）を使う。** `video`（Hailuo-02）は映像しか生成せず、
  音声を後乗せしても口は同期しない。話者動画で `video` を使ってはいけない。
- **画像・動画の中に日本語テキストを生成させない。** プロンプトに `no text, no lettering, no watermark, no logo` を必ず入れる。文字は `caption` として ffmpeg で焼き込む。
- **縦型（9:16 / 4:5）は必ずキーフレーム経由。** 動画の比率は `first_frame_image` で決まる。T2V にすると 16:9 になる。
- **image_prompt / motion_prompt は英語**、`caption` と `voiceover.script` は日本語。
- 実在の人物・企業・ブランド・ロゴを想起させるプロンプトは使わない。
- 字幕はセーフエリア外に出さない（`presets.py` の `safe_area` で自動計算済み）。

## 秘密情報

- API キーは `.env`（gitignore 済み）。**キーの値をコード・コミット・ログ・PR 本文に出さない。**
- `out/` の生成物はコミットしない。

## 実装の構造

| ファイル | 役割 |
|---|---|
| `minimax_ads/config.py` | エンドポイント・モデル・制約の一元定義。**仕様変更はここから直す** |
| `minimax_ads/api.py` | HTTP レイヤ（リトライ、`base_resp` 検査、ダウンロード） |
| `minimax_ads/images.py` / `video.py` / `audio.py` | 各 API のラッパ（v1） |
| `minimax_ads/talk.py` | MiniMax-H3 / v2 API。音声同期つき話者動画 |
| `minimax_ads/presets.py` | 配信面プリセット（解像度・アスペクト比・セーフエリア） |
| `minimax_ads/storyboard.py` | brief 実行パイプライン（`run.json` で再開可能） |
| `minimax_ads/assemble.py` | ffmpeg 編集（尺調整・連結・ASS 字幕・音声ミックス） |
| `minimax_ads/cli.py` | CLI |

外部 Python パッケージには依存しない方針（標準ライブラリのみ）。ffmpeg は外部コマンドとして使う。

## 既知の未検証事項

**実 API でのレスポンス検証は未実施**（API キー未入手のため）。
v2/H3 まわりで特に怪しいのは data URI の可否・`ratio` の扱い・応答の入れ子。
詳細は `docs/minimax-api.md` の「MiniMax-H3（v2 API）」末尾を参照。
初回実行で食い違いが出たら `docs/minimax-api.md` の「仕様変更への対応」に従って直す。
ffmpeg の編集パイプライン（連結・字幕焼き込み・音声ミックス・書き出し）は実ファイルで動作確認済み。
