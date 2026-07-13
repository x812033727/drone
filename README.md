# 商用無人機專案(Drone Project)

從零開始打造可商用的多旋翼無人機平台。本 repo 目前為**專案規劃藍圖**,涵蓋硬體、軟體、結構、法規與專案管理,作為後續開發的依據。

## 產品策略一句話

**一套共用航電核心(AC-1)+ 兩個機體平台(PA-1 / PB-1)**,覆蓋四大商用場景:

| 平台 | 構型 | MTOW | 酬載 | 場景 |
|------|------|------|------|------|
| **PA-1** | 摺疊四軸(軸距 680mm) | 6.0 kg | 1.5 kg | 空拍/測繪、安防巡邏 |
| **PB-1** | 摺疊六軸(軸距 1650mm) | 48 kg | 農噴 20L / 物流 10kg | 農業、物流配送 |

- 飛控採**半自研**路線:自行設計飛控硬體板(STM32H753,參考 Pixhawk FMUv6X 開放標準),運行客製化 PX4 韌體
- 上層應用(機載 AI、地面站、雲端機隊管理)完全自研
- 先做原型驗證市場,認證(台灣 CAA/NCC、美國 FAA、歐盟 EASA)於 Phase 3 進行,但設計階段即預留合規項目

## 文件導覽

### 總覽與需求
- [00 產品總覽與平台策略](docs/00-overview.md)
- [01 需求規格(四場景)](docs/01-requirements.md)
- [02 測試與驗證總計畫(V&V)](docs/02-verification-validation.md)
- [03 安全分析(危害/FMEA/失效保護矩陣)](docs/03-safety-analysis.md)

### 10 硬體
- [系統架構(方塊圖、電源樹、資料流)](docs/10-hardware/system-architecture.md)
- [飛控板(半自研 FC-H7)](docs/10-hardware/flight-controller.md)
- [動力系統(馬達/電變/槳/電池)](docs/10-hardware/propulsion.md)
- [感測器與酬載](docs/10-hardware/sensors-and-payload.md)
- [通訊鏈路(RC/數傳/4G5G/Remote ID)](docs/10-hardware/communication.md)
- [EMC/RF 設計(天線佈局/接地屏蔽/預掃計畫)](docs/10-hardware/emc-rf.md)
- [BOM 與成本估算](docs/10-hardware/bom.md)

### 20 軟體
- [軟體整體架構](docs/20-software/architecture.md)
- [飛控韌體(PX4 客製)](docs/20-software/firmware.md)
- [機載電腦(ROS 2 / AI)](docs/20-software/companion-computer.md)
- [地面站(GCS)](docs/20-software/ground-station.md)
- [QGC 客製評估與 Phase 1 GCS 決策](docs/20-software/gcs-qgc-evaluation.md)
- [雲端機隊管理](docs/20-software/cloud-fleet.md)
- [資安架構](docs/20-software/security.md)

### 30 結構
- [機體結構設計](docs/30-structure/airframe-design.md)
- [材料與製程](docs/30-structure/materials.md)
- [模組化酬載介面](docs/30-structure/payload-interface.md)

### 40 法規
- [認證路線圖(台/美/歐)](docs/40-regulatory/certification-roadmap.md)

### 50 專案管理
- [開發時程與里程碑(Phase 0–3)](docs/50-project/roadmap.md)
- [風險登錄表(Top-8 活登錄)](docs/50-project/risk-register.md)
- [預算估算](docs/50-project/budget.md)
- [團隊組成](docs/50-project/team.md)
- [供應鏈與製造策略](docs/50-project/supply-chain.md)
- [Phase 0 詳細執行計畫](docs/50-project/phase0/README.md)
- [軟體平台商用化路線圖(Phase 0→1 軟體)](docs/50-project/phase1/commercialization-roadmap.md)
- [Phase 0 採購計畫](docs/50-project/phase0/procurement.md)
- [Phase 0 開發機組裝與首飛檢查表](docs/50-project/phase0/build-and-first-flight.md)
- [Phase 0 飛行測試計畫(F01–F20)](docs/50-project/phase0/flight-test-plan.md)
- [Phase 0 SITL 環境建置指南](docs/50-project/phase0/sitl-setup.md)
- [營運/售後服務](docs/50-project/operations-support.md)

## Repo 結構

| 目錄 | 內容 | 狀態 |
|------|------|------|
| [`docs/`](docs/00-overview.md) | 完整規劃文件(本階段主要產出) | 持續修訂,rev 見各檔檔頭 |
| [`firmware/`](firmware/README.md) | PX4 客製韌體、FC-H7 板級支援 | 骨架 + SITL 指引 |
| [`onboard/`](onboard/README.md) | Jetson / ROS 2 機載軟體、drone-agent | 骨架 |
| [`gcs/`](gcs/README.md) | 地面站(QGC 客製 → 自研) | 骨架 |
| [`cloud/`](cloud/README.md) | 雲端機隊管理平台 | 骨架 |
| [`interfaces/`](interfaces/README.md) | 跨端介面契約(MAVLink dialect / Protobuf) | 骨架 |
| [`hardware/`](hardware/README.md) | 電子硬體設計(KiCad) | 骨架 |
| [`structure/`](structure/README.md) | 機體結構 CAD / FEA | 骨架 |
| [`tools/`](tools/README.md) | Phase 0 工具:遙測監看、ULog 分析 | ✅ 可用 |

## 開發階段速覽

| 階段 | 期間 | 目標 |
|------|------|------|
| Phase 0 | 2026 Q3(3 個月) | 現成 Pixhawk + 開源件組裝 POC,驗證任務流程 |
| Phase 1 | 2026 Q4 – 2027 Q2 | 自研飛控板 FC-H7 + PA-1 原型機 3 台 |
| Phase 2 | 2027 Q3 – 2028 Q2 | PA-1 小量產與試點客戶;PB-1 原型 |
| Phase 3 | 2028 H2 起 | 認證(台/美/歐)與量產 |
