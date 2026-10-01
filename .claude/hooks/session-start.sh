#!/bin/bash
# Claude Code on the web 用のセットアップ。
# 本リポジトリの Python は標準ライブラリのみで動くため、外部依存は ffmpeg だけ。
# ffmpeg が無いと assemble（連結・字幕焼き込み・音声ミックス）と talk が動かない。
set -euo pipefail

# ローカル環境では何もしない（各自の環境を壊さないため）
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# 冪等性: 既に入っていれば何もしない
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg/ffprobe は導入済み: $(ffmpeg -version | head -1)"
  exit 0
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 && SUDO="sudo"
fi

export DEBIAN_FRONTEND=noninteractive

# apt のインデックスが古いままだと個別パッケージが 404 になるため、update は必須
$SUDO apt-get update -qq
$SUDO apt-get install -y --no-install-recommends ffmpeg

ffmpeg -version | head -1
ffprobe -version | head -1
