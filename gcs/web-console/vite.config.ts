import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 開發時把 /api 代理到本機 fleet-svc(make dev 的 FLEETSVC_PORT,預設 38091)。
// 正式部署由 nginx 代理 /api → fleetsvc(見 Dockerfile / nginx.conf)。
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_API_TARGET ?? "http://localhost:38091",
        changeOrigin: true,
      },
    },
  },
});
