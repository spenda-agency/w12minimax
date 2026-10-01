#!/bin/bash
# assets/brand/avatar.png から「喋っている」3秒動画を作る。
#
#   ./scripts/make_avatar_talk.sh
#   DRY_RUN=1 ./scripts/make_avatar_talk.sh   # API を呼ばず内容だけ確認（課金なし）
#
# なぜ storyboard / brief JSON ではないか:
#   storyboard は Hailuo-02 (video) しか扱えず、音声は後乗せミックスになる。
#   口は同期しない。話者動画は必ず talk (MiniMax-H3) を使うこと。CLAUDE.md 参照。
#
# なぜ 4 秒生成してから切るのか:
#   H3 の duration は最小 4 秒 (minimax_ads/talk.py: MIN_DURATION)。
#   3 秒ちょうどは API では作れないため、4 秒生成 → ffmpeg で先頭 3 秒を切り出す。
#   課金は 4 秒分。
set -euo pipefail

cd "$(dirname "$0")/.."

SCRIPT_TEXT="${SCRIPT_TEXT:-こんにちは、スペンダです。}"
IMAGE="${IMAGE:-assets/brand/avatar.png}"
GEN_SECONDS="${GEN_SECONDS:-4}"     # H3 に投げる尺（最小 4）
FINAL_SECONDS="${FINAL_SECONDS:-3}" # 仕上げの尺
NAME="${NAME:-avatar_talk}"
OUT_DIR="${OUT_DIR:-out/talk}"

# 画は英語、字は焼かせない（CLAUDE.md）
PROMPT="${PROMPT:-A person speaking directly to camera, natural lip movement, subtle head motion, soft studio lighting, no text, no lettering, no watermark, no logo}"

# DRY_RUN=1 なら API を呼ばずリクエスト内容だけ表示する
MMX_FLAGS=()
[ "${DRY_RUN:-}" = "1" ] && MMX_FLAGS+=(--dry-run)

RAW="$OUT_DIR/$NAME.mp4"
FINAL="$OUT_DIR/${NAME}_${FINAL_SECONDS}s.mp4"

echo "■ 生成 ${GEN_SECONDS}s → 仕上げ ${FINAL_SECONDS}s（課金は ${GEN_SECONDS} 秒分）"
./bin/mmx "${MMX_FLAGS[@]}" talk \
  --image "$IMAGE" \
  --script "$SCRIPT_TEXT" \
  --prompt "$PROMPT" \
  --duration "$GEN_SECONDS" \
  --name "$NAME" \
  --out "$OUT_DIR"

if [ "${DRY_RUN:-}" = "1" ]; then
  echo
  echo "[dry-run] ここで ffmpeg -i $RAW -t $FINAL_SECONDS → $FINAL"
  echo "[dry-run] API は呼んでいません。課金なし。"
  exit 0
fi

echo "■ 先頭 ${FINAL_SECONDS} 秒を切り出し"
ffmpeg -y -loglevel error -i "$RAW" -t "$FINAL_SECONDS" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart "$FINAL"

echo
echo "生成元 (${GEN_SECONDS}s): $RAW"
echo "納品   (${FINAL_SECONDS}s): $FINAL"
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$FINAL" \
  | awk '{printf "実尺: %.2fs\n", $1}'
echo
echo "※ セリフが ${FINAL_SECONDS} 秒に収まらない場合は末尾が切れます。"
echo "   FINAL_SECONDS=4 で切らずに出すか、SCRIPT_TEXT を短くしてください。"
