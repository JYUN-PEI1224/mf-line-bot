#!/bin/bash
# MF勤怠 LINE Bot 起動スクリプト

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# .env ファイルが存在する場合は読み込む
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
    echo "✅ .env ファイルを読み込みました"
fi

# 必須環境変数チェック
if [ -z "$LINE_CHANNEL_SECRET" ]; then
    echo "❌ LINE_CHANNEL_SECRET が設定されていません"
    echo "   .env ファイルを作成するか、環境変数を設定してください"
    exit 1
fi

if [ -z "$LINE_CHANNEL_ACCESS_TOKEN" ]; then
    echo "❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません"
    echo "   .env ファイルを作成するか、環境変数を設定してください"
    exit 1
fi

PORT="${PORT:-8000}"

echo "🚀 MF勤怠 LINE Bot を起動します..."
echo "   ポート: $PORT"
echo "   Webhook URL: http://your-server:$PORT/webhook"
echo ""

# uvicorn でサーバーを起動
uvicorn app:app --host 0.0.0.0 --port "$PORT" --log-level info
