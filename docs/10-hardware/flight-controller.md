# 10-2 飛控板 FC-H7(半自研)

## 1. 策略

自研飛控**硬體板**,但完全遵循 **Pixhawk FMUv6X 開放標準**(Pixhawk Standards: DS-012)與 PX4 生態:

- **為什麼自研硬體**:掌握供應鏈與成本(量產時現成 Pixhawk 模組單價高)、整合我們的 PMU/載板減少線束、可依認證需求增改(冗餘、看門狗、conformal coating)、建立 NDAA compliant 供應鏈履歷
- **為什麼不自研韌體核心**:PX4 的 EKF2、控制器、失效保護經過百萬飛行小時驗證,自研演算法是 2 年以上等級的投入且無商業差異化;我們的價值在上層
- **風險控制**:FC-H7 rev A 完成前,所有開發用現成 **Holybro Pixhawk 6X**(同為 FMUv6X 標準),軟體 100% 相容,硬體延期不阻塞軟體團隊

## 2. 規格

| 項目 | 選型 | 理由 |
|------|------|------|
| FMU 主控 | STM32H753IIK6(480 MHz, 2 MB Flash, 1 MB RAM) | FMUv6X 標準件,PX4 一級支援 |
| IO 協處理器 | STM32F103(獨立電源域) | FMU 當機時維持 RC 直通與馬達安全輸出 |
| IMU ×3 | ICM-45686 ×2(不同震動隔離等級)+ BMI088 ×1 | 三冗餘 + 異廠牌避免共模故障;45686 低噪聲,BMI088 抗震動飽和 |
| 氣壓計 ×2 | BMP581 ×2(獨立氣路) | 雙冗餘 |
| 磁力計 | RM3100(外置於 GNSS 模組) | 遠離動力電流;機內不放磁力計 |
| FRAM | FM25V02A 256 Kb | 參數斷電保存 |
| 日誌 | microSD(工業級)+ 128 MB QSPI Flash 備援 | 黑盒子 |
| 看門狗 | 外部獨立 WDT + 電源監控 | 認證前置 |
| 介面 | Ethernet(100M)、CAN-FD ×2(DroneCAN)、UART ×6、SMBus、PWM ×16(經 IO) | FMUv6X superset |
| 震動隔離 | IMU 子板灌膠 + 機械隔震座 | 兩級隔震設計 |
| 尺寸 | 50 × 50 mm 核心板 + 載板(平台各自設計) | 核心板兩平台共用 |
| 工作溫度 | -20°C ~ +60°C,全板 conformal coating | 戶外商用 |

### 核心板 + 載板架構

- **核心板(共用)**:MCU、IMU、氣壓、FRAM、電源監控——這是需要嚴謹 layout 與長期不變的部分
- **載板(平台客製)**:連接器配置、PMU 整合、平台專屬介面。PA-1 載板走輕量小型化;PB-1 載板整合接觸器控制與降落傘觸發

## 3. PCB 開發計畫

| 版本 | 內容 | 時間(Phase 1 內) |
|------|------|------|
| rev A | 原理圖 + layout + 首件 5 pcs,點亮、PX4 board bring-up | M1–M3 |
| rev B | 修正 rev A 問題、EMC 預掃、震動測試、環測(-20~60°C) | M4–M6 |
| rev C(DVT) | 量產設計(DFM/DFT)、治具、小批 50 pcs | M7–M9 |

Bring-up 檢核:感測器全通、EKF2 收斂、HITL/實機懸停、24h 燒機、斷電/看門狗注錯測試。

### 工具鏈與產出物

- EDA:KiCad 8(開放格式利於外包協作)或 Altium(若團隊已有授權)
- 版控:硬體設計檔與 BOM 進 git(本 repo 未來加 `hardware/` 目錄),每版 rev 打 tag
- 產出:原理圖 PDF、Gerber、BOM(含替代料)、裝配圖、測試報告

## 4. PX4 板級支援

- 新增 board target:`boards/<vendor>/fc-h7/`,從 `px4_fmu-v6x` fork 起步(相同 MCU 與感測器拓撲,工作量主要在 pin mapping 與 dts)
- sensor rotation、電源監控參數、預設 airframe config 隨板出廠
- 詳見 [20-software/firmware.md](../20-software/firmware.md)

## 5. 供應鏈備註

- STM32H753 有長期供貨承諾(ST 10-year longevity),但仍鎖第二來源封裝相容方案
- IMU 為單一來源風險件 → 核心板預留 BMI088 與 ICM-45686 雙 footprint,韌體以 device tree 切換
- 所有關鍵 IC 建立 NDAA/出口管制檢核表(美國市場前置)
