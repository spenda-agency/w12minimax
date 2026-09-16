# MiniMax API メモ

> ⚠️ **この文書は実装時点の理解にもとづく整理です。**
> 構築した環境から `platform.minimax.io` への通信が組織のプロキシポリシーで遮断されていたため、
> 公式ドキュメントとの突き合わせと実 API での動作確認ができていません。
> 初回実行時に `./bin/mmx doctor` で疎通を確認し、食い違いがあれば下記「仕様変更への対応」の手順で直してください。

## 共通

| 項目 | 値 |
|---|---|
| ベースURL（海外） | `https://api.minimax.io/v1` |
| ベースURL（中国本土） | `https://api.minimax.chat/v1` |
| 認証 | `Authorization: Bearer <MINIMAX_API_KEY>` |
| 形式 | JSON（`Content-Type: application/json`） |

- API キーは**発行したリージョンでのみ有効**。海外キーで中国本土エンドポイントを叩くと認証エラーになります。
- レスポンスは HTTP 200 でも `base_resp.status_code != 0` ならエラーです。本実装は必ずここを検査します。
- `GroupId` はアカウント単位の識別子。ファイル取得と音声合成でクエリパラメータとして要求されます。

### エラーコード

| code | 意味 | 対応 |
|---|---|---|
| 0 | 成功 | — |
| 1002 | レート制限 | 自動リトライ（指数バックオフ） |
| 1004 | 認証失敗 | キーとリージョンの組み合わせを確認 |
| 1008 | 残高不足 | コンソールでチャージ |
| 1026 / 1027 | 入力 / 出力がコンテンツポリシー抵触 | プロンプトを修正 |
| 2013 | パラメータ不正 | モデル別の制約を確認 |
| 2049 | 無効な API キー | キーを再発行 |

実装上の対応表は `minimax_ads/config.py` の `STATUS_HINTS`。

---

## 1. 画像生成 `POST /image_generation`

```json
{
  "model": "image-01",
  "prompt": "...",
  "aspect_ratio": "9:16",
  "response_format": "url",
  "n": 1,
  "prompt_optimizer": true
}
```

- `aspect_ratio`: `1:1` `16:9` `4:3` `3:2` `2:3` `3:4` `9:16` `21:9`
  （**4:5 は非対応**。`meta_feed_4x5` プリセットは 3:4 で生成し ffmpeg でクロップします）
- `n`: 1〜9
- `response_format`: `url`（既定・一定時間で失効するので即ダウンロード）/ `base64`
- `subject_reference`: 人物の一貫性を保ちたいときに参照画像を渡す
  `[{"type": "character", "image_file": "<URL または data URI>"}]`

レスポンス: `data.image_urls[]`

実装: `minimax_ads/images.py`

---

## 2. 動画生成 `POST /video_generation`（非同期）

```json
{
  "model": "MiniMax-Hailuo-02",
  "prompt": "...",
  "duration": 6,
  "resolution": "1080P",
  "first_frame_image": "<URL または data URI>",
  "prompt_optimizer": true
}
```

レスポンス: `task_id`

| モデル | duration | resolution | first_frame |
|---|---|---|---|
| `MiniMax-Hailuo-02` | 6 / 10 | 512P / 768P / 1080P | ○（10秒 + 1080P は不可） |
| `T2V-01-Director` | 6 | 720P | ×（カメラワーク指示に強い） |
| `I2V-01-Director` | 6 | 720P | ○ |
| `I2V-01-live` | 6 | 720P | ○（イラスト・アニメ調） |
| `S2V-01` | 6 | 720P | ×（被写体参照） |

**重要**: 出力のアスペクト比は `first_frame_image` の比率に従います。
縦型（9:16 / 4:5）広告では必ずキーフレーム画像を先に作ってから動画化してください。
T2V（画像なし）だと 16:9 で返ってきて、縦型に使うと大きくクロップされます。

制約テーブルは `minimax_ads/config.py` の `VIDEO_MODEL_LIMITS`。送信前に検証し、
新モデルなど未知の名前はそのまま通します（`--force` で検証を無効化可）。

### 2.1 状態確認 `GET /query/video_generation?task_id=...`

`status`: `Preparing` → `Queueing` → `Processing` → `Success` / `Fail`
`Success` のとき `file_id` が返ります。本実装は既定 10 秒間隔・最大 30 分でポーリングします。

### 2.2 ファイル取得 `GET /files/retrieve?file_id=...&GroupId=...`

`file.download_url` から mp4 をダウンロードします。URL には有効期限があるため、
取得したらすぐ保存してください。

実装: `minimax_ads/video.py`

---

## 3. 音声合成 `POST /t2a_v2?GroupId=...`

```json
{
  "model": "speech-02-hd",
  "text": "ナレーション原稿",
  "stream": false,
  "voice_setting": {"voice_id": "Japanese_CalmLady", "speed": 1.0, "vol": 1.0, "pitch": 0},
  "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1}
}
```

- レスポンスの `data.audio` は **16進文字列**。バイト列に戻して保存します。
- `speed` は 0.5〜2.0 程度。15秒尺に収めたいときは 1.05〜1.15 が扱いやすいです。
- 使える `voice_id` はアカウントとリージョンで異なります。コンソールで確認し、
  よく使うものを `minimax_ads/audio.py` の `JA_VOICES` に別名登録してください。

実装: `minimax_ads/audio.py`

---

## 仕様変更への対応

MiniMax はモデル名とパラメータが更新されます。ズレたときの直す場所:

| 症状 | 直す場所 |
|---|---|
| モデル名が変わった | `config.py` の `DEFAULT_*_MODEL`, `VIDEO_MODEL_LIMITS` |
| 尺・解像度の組み合わせが増減した | `config.py` の `VIDEO_MODEL_LIMITS` |
| アスペクト比が増えた | `config.py` の `IMAGE_ASPECT_RATIOS` |
| エンドポイントのパスが変わった | `config.py` の `EP_*` |
| レスポンス構造が変わった | `images.py` / `video.py` / `audio.py` の該当箇所 |

まず `--dry-run` で送信内容を確認し、`curl` で 1 本通してから本実装を直すのが安全です。

```bash
./bin/mmx --dry-run video "test" --first-frame out/images/kf1.jpg
```


---

## MiniMax-H3（v2 API）— 音声同期つき話者動画

Hailuo-02 系（v1）の I2V は**映像だけ**を生成するため、ナレーションを後乗せしても
口の動きは一致しない。H3 は映像と音声を同一の潜在表現から生成するので、
`reference_audio` を渡すと**口がその音声に同期する**。

プロトコルが v1 と別系統（`content[]` 配列）なので、実装は `minimax_ads/talk.py` に分離してある。

### エンドポイント

| 用途 | メソッド | パス |
|---|---|---|
| タスク作成 | POST | `{api_root}/v2/video_generation` |
| 状態確認 | GET | `{api_root}/v2/query/video_generation/{task_id}` |

`api_root` は `base_url` からバージョン接尾辞を外したもの（`Settings.api_root`）。
v1 と v2 でパスの生え方が違うため、`api.py` は `/v2/` 始まりを別扱いにしている。

### リクエスト

```json
{
  "model": "MiniMax-H3",
  "content": [
    { "type": "text", "text": "英語の映像指示（必須・空不可）" },
    { "type": "image_url", "image_url": {"url": "..."}, "role": "reference_image" },
    { "type": "audio_url", "audio_url": {"url": "..."}, "role": "reference_audio" }
  ],
  "duration": 6,
  "resolution": "768P",
  "ratio": "adaptive"
}
```

| パラメータ | 値 |
|---|---|
| `model` | `MiniMax-H3`（768P/2K・4〜15秒） / `MiniMax-H3-Max`（480P/768P・5〜15秒） |
| `duration` | 4〜15 の整数 |
| `resolution` | `768P` / `2K` |
| `ratio` | 既定 `adaptive`（参照画像の比率に従う）。T2V では明示が必要 |

`content[]` の `role`:

| role | type | 備考 |
|---|---|---|
| `first_frame` / `last_frame` | `image_url` | フレーム条件づけ |
| `reference_image` | `image_url` | 参照生成。人物の同一性を保つ |
| `reference_video` | `video_url` | MP4/MOV、H.264/H.265、2〜15秒、≤50MB、合計15秒まで |
| `reference_audio` | `audio_url` | **これを渡すとリップシンクする** |

**フレーム条件づけ（`first_frame`/`last_frame`）と参照生成（`reference_*`）は排他。**
混ぜて送るとエラーになるため `talk.build_content()` が送信前に弾く。

### 参照画像の要件

- 1辺 256〜5760px
- アスペクト比 0.4〜2.5
- ≤30MB、JPG / PNG / WEBP / HEIC / HEIF

`talk.validate_image()` が送信前に検査する。

### 応答

完了時に `task.content.url` から動画を直接ダウンロードする
（v1 のような `file_id` → `/files/retrieve` の2段構えではない）。
ポーリング間隔は 10 秒が推奨。

### 未検証の点

実 API キーでの疎通はまだ取れていない。初回実行で食い違いが出やすいのは以下:

1. `image_url` / `audio_url` が **data URI を受けるか**。弾かれる場合は公開 URL への
   アップロードが必要になる（`talk.media_ref()` は URL をそのまま通すので、
   URL を渡せば実装変更なしで動く）。
2. `ratio` を `adaptive` にしたとき、参照生成で出力比が参照画像に従うか。
3. 応答の入れ子（`task.status` / `task.content.url`）。`talk.wait_for()` は
   トップレベル直置きの形も拾うようにしてある。
