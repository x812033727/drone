#!/bin/sh
# 依環境變數產生執行期 config.js(前端讀 window.__APP_CONFIG__)。
# 由 nginx 官方 entrypoint 於啟動 nginx 前自動執行(掃描 /docker-entrypoint.d/*.sh)。
# 未提供的變數輸出空字串,前端會退回 build-time VITE_* 或內建預設。
# 目的:一份映像可用不同環境變數部署到不同環境(OIDC/API/地圖),免重 build。
set -eu

CONFIG_PATH="${APP_CONFIG_PATH:-/usr/share/nginx/html/config.js}"

# 將值轉為安全的 JS 字串內容:轉義反斜線與雙引號,並把換行折成空白,避免破壞語法。
js_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n\r' '  '
}

cat > "$CONFIG_PATH" <<EOF
// 由容器 entrypoint 依環境變數於啟動時產生(勿手動編輯)。
window.__APP_CONFIG__ = {
  apiBase: "$(js_escape "${APP_API_BASE:-}")",
  oidcAuthUrl: "$(js_escape "${APP_OIDC_AUTH_URL:-}")",
  oidcTokenUrl: "$(js_escape "${APP_OIDC_TOKEN_URL:-}")",
  oidcClientId: "$(js_escape "${APP_OIDC_CLIENT_ID:-}")",
  oidcRedirectUri: "$(js_escape "${APP_OIDC_REDIRECT_URI:-}")",
  oidcScope: "$(js_escape "${APP_OIDC_SCOPE:-}")",
  mapStyle: "$(js_escape "${APP_MAP_STYLE:-}")",
  videoBase: "$(js_escape "${APP_VIDEO_BASE:-}")",
  videoAuth: "$(js_escape "${APP_VIDEO_AUTH:-}")",
};
EOF

echo "web-console: 執行期 config.js 已寫入 $CONFIG_PATH"
