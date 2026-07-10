# gcs — 地面站

> 規劃依據:[docs/20-software/ground-station.md](../docs/20-software/ground-station.md)

## 兩階段策略

| 階段 | 內容 | 本目錄對應 |
|------|------|-----------|
| Phase 0–1 | QGroundControl 客製 fork(branding、鎖機型、簡化 UI) | `qgc/`(fork submodule)+ `qgc-custom/`(客製層) |
| Phase 2+ | 自研 GCS:遙控器 Android App + Web 指揮中心 | `gcs-core/`、`app-android/`、`web-console/` |

## 注意

- QGC 授權為 Apache 2.0 / GPLv3 雙軌;fork 時確認引用範圍與合規(見規劃文件)
- QGC 的客製使用官方 custom build 機制(`custom/` overlay),不散改 upstream 原始碼,
  便於跟版升級
