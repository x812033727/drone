import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 開發時把 /api 代理到本機服務:fleet-svc(FLEETSVC_PORT,預設 38091)+
// mission-svc 的 routes/missions 前綴(MISSIONSVC_PORT,預設 38092)。
// 更長前綴需先列(vite 依序比對,先命中者勝)。
// 正式部署由 nginx 代理(見 Dockerfile / nginx.conf)。
const MISSION_TARGET = process.env.VITE_DEV_MISSION_TARGET ?? "http://localhost:38092";
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api/v1/routes": { target: MISSION_TARGET, changeOrigin: true },
      "/api/v1/missions": { target: MISSION_TARGET, changeOrigin: true },
      "/api": {
        target: process.env.VITE_DEV_API_TARGET ?? "http://localhost:38091",
        changeOrigin: true,
      },
    },
  },
});
