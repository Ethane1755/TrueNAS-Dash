#!/bin/bash

# ==========================================
# TrueNAS Dashboard 自動部署腳本
# ==========================================

# 1. 載入並檢查 .env
if [ -f .env ]; then
    echo "📄 Loading environment variables from .env..."
    # 使用 set -a 自動 export 所有變數
    set -a
    source .env
    set +a
else
    echo "❌ Error: .env file not found."
    exit 1
fi

# 2. 設定與檢查必要變數
IMAGE_NAME="eh8090/truenas-dash"
APP_NAME="truenas-dash"
PLATFORM="linux/amd64"

# 檢查 API Key 是否存在
if [ -z "$TRUENAS_API_KEY" ]; then
    echo "❌ Error: TRUENAS_API_KEY is not set in .env"
    exit 1
fi

# 檢查 Host 是否存在
if [ -z "$TRUENAS_HOST" ]; then
    echo "❌ Error: TRUENAS_HOST is not set in .env"
    exit 1
fi

TRUENAS_URL="${TRUENAS_SCHEME}://${TRUENAS_HOST}:${TRUENAS_PORT:-443}"
# 移除可能重複的 port (如果 TRUENAS_SCHEME 已經包含 port 或是不需要)
# 簡易處理：如果 TRUENAS_PORT 沒設，預設 HTTPS 443; 如果 SCHEME 是 http，預設 80
if [ -z "$TRUENAS_PORT" ]; then
    if [ "$TRUENAS_SCHEME" = "http" ]; then
        TRUENAS_URL="${TRUENAS_SCHEME}://${TRUENAS_HOST}"
    else
        TRUENAS_URL="${TRUENAS_SCHEME}://${TRUENAS_HOST}"
    fi
else
     TRUENAS_URL="${TRUENAS_SCHEME}://${TRUENAS_HOST}:${TRUENAS_PORT}"
fi

# 3. 顯示資訊
echo "=========================================="
echo "🎯 Target:  $TRUENAS_URL"
echo "📦 App:     $APP_NAME"
echo "🐳 Image:   $IMAGE_NAME"
echo "🖥️  Platform: $PLATFORM"
echo "=========================================="

echo ""
echo "🚀 Step 1: Building Docker Image..."
docker build --platform $PLATFORM -t $IMAGE_NAME:latest .
if [ $? -ne 0 ]; then
    echo "❌ Build Failed!"
    exit 1
fi

echo ""
echo "🚀 Step 2: Pushing to Docker Hub..."
docker push $IMAGE_NAME:latest
if [ $? -ne 0 ]; then
    echo "❌ Push Failed!"
    exit 1
fi

echo ""
echo "🚀 Step 3: Triggering TrueNAS Redeploy..."

# 呼叫 TrueNAS API
# 使用 -k (insecure) 以防自簽憑證問題，根據您的 .env 設定決定是否要驗證 SSL
CURL_OPTS="-s -o /dev/null -w %{http_code}"
if [ "$TRUENAS_VERIFY_SSL" = "false" ]; then
    CURL_OPTS="$CURL_OPTS -k"
fi

RESPONSE=$(curl $CURL_OPTS -X POST "$TRUENAS_URL/api/v2.0/chart/release/redeploy" \
  -H "Authorization: Bearer $TRUENAS_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"release_name\": \"$APP_NAME\"}")

echo "📡 API Response Code: $RESPONSE"

if [ "$RESPONSE" -eq 200 ]; then
    echo "✅ Success! Redeploy triggered."
    echo "   Dashboard is restarting with the new version."
else
    echo "❌ Failed! TrueNAS API returned error."
    echo "   Please check:"
    echo "   1. TRUENAS_API_KEY is correct?"
    echo "   2. App Name '$APP_NAME' matches exactly in TrueNAS?"
    echo "   3. Network connectivity to $TRUENAS_URL?"
fi
