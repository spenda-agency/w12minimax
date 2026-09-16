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
