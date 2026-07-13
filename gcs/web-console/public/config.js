// 執行期設定範例 / dev 預設。
// - dev(vite):本檔隨 public/ 由 root 提供;各欄留空即退回 build-time VITE_* 或內建預設,
//   故本地開發行為與過往一致。
// - 正式(容器):啟動時 entrypoint(docker-entrypoint.d/40-render-app-config.sh)依環境變數
//   重新產生本檔並覆寫,達成「一份映像多環境部署」免重 build。
// 空字串一律視為「未設定」,前端會依序退回 VITE_* / 內建預設。
window.__APP_CONFIG__ = {
  apiBase: "",
  oidcAuthUrl: "",
  oidcTokenUrl: "",
  oidcClientId: "",
  oidcRedirectUri: "",
  oidcScope: "",
  mapStyle: "",
};
