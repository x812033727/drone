# 多階段:node 建置 → nginx 靜態服務 + /api 反代 fleetsvc。
# build context 為 repo 根(與其他服務一致)。
FROM node:26-slim AS build
WORKDIR /app
COPY gcs/web-console/package.json gcs/web-console/package-lock.json ./
RUN npm ci
# 只複製建置所需(避免帶入本機 node_modules/dist)
COPY gcs/web-console/index.html ./
COPY gcs/web-console/tsconfig.json gcs/web-console/tsconfig.app.json gcs/web-console/tsconfig.node.json ./
COPY gcs/web-console/vite.config.ts ./
COPY gcs/web-console/public ./public
COPY gcs/web-console/src ./src
RUN npm run build

FROM nginx:1.31-alpine
COPY gcs/web-console/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# 執行期環境注入:啟動時依環境變數(APP_API_BASE/APP_OIDC_*/APP_MAP_STYLE)重新產生
# /usr/share/nginx/html/config.js。由 nginx 官方 entrypoint 自動執行,故沿用預設 CMD/反代/SPA。
COPY gcs/web-console/docker-entrypoint.d/40-render-app-config.sh /docker-entrypoint.d/40-render-app-config.sh
RUN chmod +x /docker-entrypoint.d/40-render-app-config.sh
