# firmware — 飛控韌體(PX4 客製,as-built)

> 規劃依據:[docs/20-software/firmware.md](../docs/20-software/firmware.md)。
> 本目錄為韌體軌的**實作落地**:不 fork、不用 submodule——CI/本機以釘版 tag
> 現抓 upstream,客製以 patch series + out-of-tree 模組承載(理由見下)。

## 結構(as-built)

```
firmware/
├── px4.lock            # upstream 釘版(v1.15.4)——單一事實來源
├── Makefile            # 一鍵入口:make -C firmware help
├── tools/
│   ├── fetch_px4.sh    # shallow clone + NuttX tag 陷阱解法(冪等)
│   ├── apply_patches.sh# patch series 套用(git apply --3way,冪等)
│   ├── requirements-px4-build.txt  # 建置依賴(釘版)
│   ├── run_sitl_smoke.sh           # SIH 起機 + heartbeat 煙霧
│   └── smoke/          # pymavlink 斷言腳本
├── patches/            # 樹內小 patch(≤20 commit 預算的量尺;現況見該目錄)
├── ext/                # out-of-tree 模組(EXTERNAL_MODULES_LOCATION;後續 PR)
├── airframes/          # PA-1 / PB-1 參數包(後續 PR)
└── boards/fc-h7/       # 自研板(Phase 1 硬體,佔位)
```

## 為什麼不 fork / 不 submodule(決策記錄,2026-07)

- 客製量刻意極小(firmware.md §1:≤20 commits、不碰 EKF2/控制器/狀態機):
  樹內必改處只剩 dialect 選定、streams 註冊、ROMFS airframe 三類小 patch,
  其餘(自訂模組、uORB 訊息)全走 `ext/`(PX4 `EXTERNAL_MODULES_LOCATION`)。
- fork repo 的成本(雙 repo 權限、跟版紀律、~2 GB checkout)此階段零收益;
  `ls patches/*.patch | wc -l` 即預算量尺。
- submodule 會讓每次 clone 揹 2 GB,而只有 firmware 變更才需要 PX4
  → CI 以 shallow clone + ccache 取代。
- **升級決策點**:FC-H7 board bring-up 啟動(大量 boards/ 樹內檔案)或
  patch 數 > 10 時,升級為 fork repo。

## 快速開始

```bash
make -C firmware all     # fetch → deps → patch → build(px4_sitl_default)→ SIH 煙霧
make -C firmware smoke   # 已 build 過只重跑煙霧
```

Gazebo 場景(F05–F20 失效保護回歸)仍走現成 image
(`jonasvautherin/px4-gazebo-headless:1.15.4`,見
[docs/50-project/phase0/sitl-setup.md](../docs/50-project/phase0/sitl-setup.md));
本目錄的自建 SITL 用於驗證**我們的 patch/模組/dialect**(SIH,秒級就緒)。
⚠️ 已知缺口:nightly gazebo 場景跑的是 stock 韌體,不含本目錄 patch——
待 patch 承載實際行為變更後,評估把自建 SITL 打包供 nightly 消費。

## CI

`firmware-ci.yml`:path-gated(`firmware/**` + `interfaces/mavlink/**`),
shallow clone + ccache(冷建置 ~20 min、熱 ~5-7 min),build 後接 SIH 煙霧。
dialect XML 本身的守門(mavgen dry-run)在 `mavlink-ci.yml`,不在此重跑。

## 開發原則

- 只在 `patches/`、`ext/`、`airframes/`、`boards/` 增量;不直接改 upstream 核心
  (EKF2/控制器/commander 狀態機)
- 每 6–12 個月 rebase 一次 upstream stable(升 `px4.lock` + 重滾 patches)
- 失效保護場景(失聯/低電/GPS 拒止/GeoFence)全部寫成 SITL 回歸腳本,進 CI
