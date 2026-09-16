# brief JSON の書き方

`./bin/mmx storyboard <brief.json>` に渡す絵コンテ定義です。
サンプル: [`meta_reels_15s_sample.json`](meta_reels_15s_sample.json) / [`youtube_instream_30s_sample.json`](youtube_instream_30s_sample.json)

## トップレベル

| キー | 必須 | 既定 | 説明 |
|---|---|---|---|
| `name` | ○ | ファイル名 | 出力ディレクトリと納品ファイル名に使われる |
| `preset` | ○ | `meta_reels_9x16` | 配信面プリセット（`./bin/mmx presets` で一覧） |
| `shots` | ○ | — | カット定義の配列 |
| `style` | | `""` | 全カット共通の画のトーン。`image_prompt` の後ろに連結される |
| `video_model` | | `MiniMax-Hailuo-02` | 動画モデル |
| `image_model` | | `image-01` | 画像モデル |
| `resolution` | | プリセット値 | 動画解像度の上書き（`512P`/`768P`/`1080P`） |
| `subtitles` | | `true` | 字幕を焼き込むか |
| `font` | | 自動選択 | 字幕フォント名。無い場合は入っている日本語フォントに自動フォールバック |
| `voiceover` | | なし | ナレーション設定（下記） |
| `bgm` | | なし | BGM 設定（下記） |

### `voiceover`

```json
{
  "enabled": true,
  "voice_id": "Japanese_CalmLady",
  "speed": 1.05,
  "volume": 1.0,
  "emotion": "neutral",
  "script": "ナレーション原稿。15秒なら55〜65文字が目安。"
}
```

`voice_id` は `./bin/mmx voices` の一覧か、MiniMax コンソールで確認した ID を指定します。

### `bgm`

```json
{ "path": "assets/bgm/corporate_uplift.mp3", "gain_db": -20 }
```

- BGM は**自前で用意**してください（MiniMax の音楽生成は本ツール未対応）。ライセンスを確認のこと。
- 尺が足りなければ自動ループ、最後 0.6 秒はフェードアウトします。
- ナレーションがある場合は `-18` 〜 `-22` dB が目安です。

## `shots[]`

| キー | 必須 | 既定 | 説明 |
|---|---|---|---|
| `id` | | `s1`, `s2`… | カットID。出力ファイル名と `--resume` の識別に使う |
| `seconds` | ○ | `5` | 完成尺での長さ。6 を超えると 10 秒生成になる |
| `image_prompt` | ○※ | `""` | キーフレームの画（英語推奨） |
| `motion_prompt` | ○ | `""` | 動き・カメラワークの指示 |
| `caption` | | `""` | 焼き込む字幕。空なら字幕なし |
| `keyframe` | | なし | 既存画像を使う場合のパス or URL（`image_prompt` より優先） |
| `use_keyframe` | | `true` | `false` にすると画像を挟まず T2V。**縦型では非推奨** |

※ `keyframe` を指定する場合は `image_prompt` 不要。

### 尺と課金の関係

`seconds` は完成尺です。生成は 6 秒単位なので:

| `seconds` | 生成 | 課金 |
|---|---|---|
| 4 | 6秒 | 6秒分 |
| 6 | 6秒 | 6秒分 |
| 8 | 10秒 | 10秒分（解像度は 768P まで） |

無駄を避けるなら **各カット 5〜6 秒**で設計してください。

## 検証

```bash
./bin/mmx storyboard briefs/xxx.json --check
```

合計尺・カット数・API 呼び出し見込みを表示し、以下を警告します（API は呼びません）。

- 合計尺がプリセット上限超過 / 広告尺として不自然
- 1 カットが 10 秒超
- `image_prompt` も `keyframe` も無い
- `motion_prompt` が空
