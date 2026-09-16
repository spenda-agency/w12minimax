# 広告映像向けプロンプト設計

MiniMax は **画（image_prompt）** と **動き（motion_prompt）** を分けて考えると安定します。
本ツールは「① 静止画で画を確定 → ② その画を起点に動かす」という二段構えです。
画が気に入らないまま動画化すると課金が無駄になるので、まず `--skip-video` で画だけ作って確認してください。

```bash
./bin/mmx storyboard briefs/xxx.json --skip-video   # キーフレームだけ生成
```

## 1. image_prompt（キーフレーム）

**英語で書く。** 日本語プロンプトも通りますが、英語のほうが構図・ライティングの制御が効きます。

構成要素を順に並べます。

```
[被写体と状況] + [構図/カメラ] + [ライティング] + [質感/レンズ] + [色調] + [禁止事項]
```

例:
```
close-up over-the-shoulder shot of a tired Japanese businesswoman in her 30s at a dark desk late at night,
surrounded by stacks of printed spreadsheets, blue monitor glow on her face,
shallow depth of field, 35mm look, cool blue color grade, vertical composition,
photorealistic, no text, no lettering, no watermark, no logo
```

必ず入れる:

| 要素 | 理由 |
|---|---|
| `no text, no lettering, no watermark, no logo` | AI が描く日本語は崩れる。文字は字幕で載せる |
| `vertical composition` / `wide cinematic shot` | プリセットの縦横に合った構図にする |
| 人物の属性（`Japanese`, 年代など） | 日本向け広告で意図しない人物像になるのを防ぐ |
| ライティング指定 | 「広告っぽさ」はほぼ光で決まる |

brief の `style` に共通の質感（色調・レンズ・雰囲気）をまとめて書くと、全カットのトーンが揃います。

**避けるもの**: 実在企業名・ブランドロゴ・著名人・既存作品のスタイル指定（"in the style of 〇〇"）。

## 2. motion_prompt（動き）

キーフレームがある前提なので、**画の説明ではなく「何が動くか」だけ**を書きます。

```
the camera slowly pushes in toward her face as she sighs and rubs her eyes,
subtle handheld movement, paper stacks slightly out of focus in the foreground
```

効きやすい指示:

| 種類 | 例 |
|---|---|
| カメラワーク | `slow dolly-in`, `camera slowly orbits to the right`, `slow pull-back reveal`, `handheld-style shot` |
| 被写体の動作 | `she nods and smiles`, `he crosses his arms` |
| 環境の動き | `data particles flow in from the edges`, `light gently shifts across the wall` |
| 速度 | `slow`, `subtle`, `gradual`（広告では速い動きは破綻しやすい） |

避けるもの:

- 1 カットに複数のアクションを詰める（6 秒では破綻します。1 カット 1 動き）
- シーンの切り替わりを指示する（カットは分けて生成し、ffmpeg で連結）
- 手の細かい動作、文字を書く動作、大人数の同時アクション

`T2V-01-Director` / `I2V-01-Director` はカメラ指示の追従性が高いモデルです。
`[Push in]`、`[Pan left]` のようなディレクター記法が使えます（Hailuo-02 では自然文で指示）。

## 3. 一貫性を保つ

同じ人物を複数カットに登場させたい場合:

```bash
./bin/mmx image "..." --reference out/images/person_ref.jpg
```

`subject_reference` に参照画像を渡します（人物のみ対応）。
ただし完全な同一性は保証されません。実務では **人物を跨がせず、カットごとに別の切り口**
（手元 → 画面 → チーム）で構成するほうが安定します。

## 4. ナレーション原稿

- **15 秒 ≒ 日本語 55〜65 文字、30 秒 ≒ 120〜140 文字** が目安（`speed: 1.0` 基準）。
- 尺に入らないときは原稿を削るのが先。`speed` を 1.2 以上に上げると聞き取りにくくなります。
- 数字・英字は読み間違いが起きます（例: 「BI」→「ビーアイ」と書く）。
- 句読点で間を作れます。「、」は短い間、「。」は明確な区切りです。

## 5. 字幕（caption）

- **1 カット 1 メッセージ、20 文字以内**。縦型では 15 文字程度で折り返しが起きません。
- ナレーションの丸写しではなく、**音を消しても意味が通る要約**にします。
- 改行したい位置には `\n` を入れてください（ASS の `\N` に変換されます）。
