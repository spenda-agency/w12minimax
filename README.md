# w12minimax — MiniMax で広告クリエイティブを作る

MiniMax API（画像 `image-01` / 動画 `MiniMax-Hailuo-02` / 音声 `speech-02`）を使って、
**Meta 広告・YouTube 広告向けの 15〜30 秒プロモーション**の静止画と動画を生成するツールキットです。

Claude Code のセッションから自然文で指示 → 内部でこの CLI が走る、という使い方を想定しています。

```
brief.json ──┬─ ① キーフレーム静止画   (image-01)
             ├─ ② 各カットを動画化     (Hailuo-02 / I2V)
             ├─ ③ ナレーション音声     (speech-02)
             └─ ④ ffmpeg で 尺調整→連結→字幕焼込→音声ミックス→入稿用書き出し
```

---

## 1. セットアップ

### 1.1 API キー

```bash
cp .env.example .env
# .env を編集して MINIMAX_API_KEY と MINIMAX_GROUP_ID を設定
```

- キーの発行: <https://platform.minimax.io/> （中国本土アカウントは <https://platform.minimaxi.com/>）
- `MINIMAX_GROUP_ID` は動画ファイルのダウンロードと音声合成で必要です（コンソールのアカウント情報に表示）。
- **キーは発行したリージョンでしか使えません。** 認証エラー（status_code 1004）が出たら `MINIMAX_REGION` を `global` / `cn` で切り替えてください。
- `.env` は `.gitignore` 済みです。キーを直接コードやコミットに書かないでください。

### 1.2 ローカル依存

| 依存 | 用途 | インストール |
|---|---|---|
| Python 3.10+ | CLI 本体（**外部パッケージ不要**） | — |
| ffmpeg / ffprobe | 連結・字幕・音声ミックス | `brew install ffmpeg` / `sudo apt-get install -y ffmpeg` |
| 日本語フォント | 字幕の焼き込み | macOS は標準 / `sudo apt-get install -y fonts-noto-cjk` |

日本語フォントが無いと **字幕が空白のまま書き出されます**（検知してエラーにしています）。

### 1.3 確認

```bash
./bin/mmx doctor     # 設定・ffmpeg・フォント・API 疎通をチェック
```

---

## 2. 使い方

### 2.1 静止画 1 枚（Meta フィード用バナー素材など）

```bash
./bin/mmx image "modern Japanese office, data dashboard on a large screen, soft morning light, photorealistic, no text" \
  --preset meta_feed_1x1 -n 4 --name bi_hero
# → out/images/bi_hero_01.jpg 〜 _04.jpg
```

### 2.2 動画 1 カット

```bash
# 縦型はキーフレームで比率が決まるので、まず静止画を作ってから動かす
./bin/mmx image "..." --preset meta_reels_9x16 --name kf1
./bin/mmx video "the camera slowly pushes in, data charts animate upward" \
  --first-frame out/images/kf1.jpg --preset meta_reels_9x16 --duration 6 --name cut1
```

生成には数分かかります。`--no-wait` で `task_id` だけ受け取り、あとから
`./bin/mmx task <task_id> --wait` で回収することもできます。

### 2.3 15〜30 秒の広告を一気通貫で作る（推奨）

```bash
./bin/mmx storyboard briefs/meta_reels_15s_sample.json --check   # 検証のみ、課金なし
./bin/mmx storyboard briefs/meta_reels_15s_sample.json           # 実行
```

出力: `out/<name>-<日時>/`

```
keyframes/   各カットのキーフレーム静止画
clips/       各カットの生成動画（6s or 10s）
audio/       ナレーション
work/        中間ファイル（ASS 字幕・連結・ミックス）
final/       ★ 納品物 mp4 と .srt（配信面へのキャプション入稿用）
run.json     進捗状態（--resume で途中から再開）
```

途中で失敗・中断しても `--resume` で **生成済みのカットを課金し直さずに** 続行できます。
編集だけやり直す場合は `./bin/mmx assemble <brief.json> <run_dir>`。

---

## 3. コマンド一覧

| コマンド | 内容 |
|---|---|
| `doctor` | 設定・依存・API 疎通の確認 |
| `presets` | 広告フォーマットのプリセット一覧 |
| `models` | モデルと尺・解像度の制約一覧 |
| `image <prompt>` | 静止画生成 |
| `video <prompt>` | 動画生成（`--first-frame` で I2V） |
| `task <task_id>` | 動画タスクの状態確認 / `--wait` で完了待ち＆DL |
| `fetch <file_id>` | file_id から動画をダウンロード |
| `voice --text ...` | ナレーション音声生成 |
| `voices` | 日本語ボイスの別名一覧 |
| `storyboard <brief>` | brief から広告を一気通貫生成 |
| `assemble <brief> <run_dir>` | 既存素材から編集だけやり直す |

共通オプション: `--dry-run`（API を呼ばずリクエスト内容だけ表示）、`--verbose`。

---

## 4. プリセット

| key | 用途 | 出力 |
|---|---|---|
| `meta_reels_9x16` | Meta Reels / Stories | 1080x1920 |
| `meta_feed_4x5` | Meta フィード（縦） | 1080x1350 |
| `meta_feed_1x1` | Meta フィード（正方形） | 1080x1080 |
| `youtube_instream_16x9` | YouTube インストリーム | 1920x1080 |
| `youtube_shorts_9x16` | YouTube ショート | 1080x1920 |
| `youtube_bumper_16x9` | YouTube バンパー（6秒） | 1920x1080 |

詳細と安全マージンは [`docs/ad-specs.md`](docs/ad-specs.md)。

---

## 5. ドキュメント

- [`docs/minimax-api.md`](docs/minimax-api.md) — API エンドポイント・パラメータ・エラーコード、仕様変更時の直し方
- [`docs/ad-specs.md`](docs/ad-specs.md) — Meta / YouTube の入稿要件と構成の型
- [`docs/prompting.md`](docs/prompting.md) — 広告映像向けプロンプト設計
- [`briefs/SCHEMA.md`](briefs/SCHEMA.md) — brief JSON の書き方
- [`CLAUDE.md`](CLAUDE.md) — Claude Code から指示を出すときの前提

---

## 6. 注意

- **動画生成は 1 本ずつ課金されます。** まず `--check` と `--skip-video`（キーフレームだけ生成）で画の方向性を固めてから動画化してください。
- 生成物には**画面内に日本語テキストを描かせない**でください（AI 画像の日本語は崩れます）。文字は字幕・テロップとして ffmpeg 側で載せます。
- 実在の人物・ブランド・ロゴを想起させるプロンプトは使わないでください。広告審査と権利の両面でリスクになります。
- 生成物（`out/`）と `.env` は Git 管理外です。納品物は別途保管してください。
