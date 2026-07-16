# gcs — 地面站

> 規劃依據:[docs/20-software/ground-station.md](../docs/20-software/ground-station.md);
> QGC 客製深度決策:[docs/20-software/gcs-qgc-evaluation.md §5](../docs/20-software/gcs-qgc-evaluation.md)(2026-07,S16)

## 階段策略(對齊 S16 決策)

| 階段 | 內容 | 本目錄對應 |
|------|------|-----------|
| Phase 0 | **選項 A:stock QGC + 預設檔**(不 build、零 CI):官方安裝檔 + 參數預設檔(.params)+ 任務範本(.plan)+ 台灣圖源設定說明 | `qgc-profiles/` |
| Phase 1 | **選項 B:官方 custom-build overlay**(GPLv3 + 開源 Qt):upstream submodule + `custom/` overlay(branding、鎖機型、簡化 UI、預載台灣圖資),無自有 fork 碼 | `qgc-custom/`(Phase 1 立項時建立) |
| Phase 2+ | 自研 GCS:遙控器 Android App + Web 指揮中心 | `gcs-core/`、`app-android/`、`web-console/` |

**不做深 fork**(選項 C):Phase 1 功能無一項需要,且為 Phase 2 即棄資產——理由與決策記錄見評估文件 §5。

## 現況

- `web-console/`:Phase 0 已落地的 Web 主控台(機隊地圖/任務派遣/告警/OTA/計費 UI,OIDC SSO)。
- `qgc-profiles/`:選項 A 交付物(QGC 版本 pin、PA-1 參數預設檔、任務範本、台灣圖源設定)。
- `qgc-custom/`:未建立;Phase 1 立項(EVT/試點交付需要 branding 時)再開,啟動前先完成評估文件 §2.2 三項「需查證最新版」確認。

## 注意

- QGC 授權為 Apache 2.0 / GPLv3 雙軌;已決策走 **GPLv3 + 開源 Qt**(客製層無機密可開源,零授權費),分析見評估文件 §3
- QGC 的客製使用官方 custom build 機制(`custom/` overlay),不散改 upstream 原始碼,
  便於跟版升級
