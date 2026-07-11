# 10-2 飛控板 FC-H7(半自研)

> rev 2 · 2026-07(M2 凍結版基礎)。rev 1 選型結論(STM32H753 FMU + STM32F103 IO、三冗餘 IMU、FMUv6X 參照、rev A/B/C 節奏)全數保留;本版加入關鍵 IC 料號表(§3)、電源架構細化(§4)、核心板↔載板連接器定義(§5)、IO 協處理器安全行為規格(§6)與 rev A bring-up 檢核清單(§8)。所有新估數均為 rev A 實測前設計值,標注更新條件;版本紀錄見 §11。
> 章節重排說明:rev 1 §3/§4/§5 依序移至 §7/§9/§10,他文件引用不受影響(既有引用皆為檔級)。

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

## 3. 關鍵 IC 料號表

主料照 §2 選型;替代料以「雙 footprint 或腳位相容」為原則,異構備援**凍結待 rev A 驗證**後定案。感測冗餘拓撲(三 IMU / 雙氣壓投票)與 [03-safety FMEA 感測列](../03-safety-analysis.md)、REQ-SAF-01 口徑一致。

| 料號 | 功能 | 封裝 | 替代料(雙 footprint 註記) | 供貨風險 | NDAA |
|------|------|------|-----------------------------|----------|------|
| STM32H753IIK6 | FMU 主控 | UFBGA-176 | STM32H743IIK6(腳位相容,無加密引擎) | 低(ST 10 年供貨承諾) | ✓ |
| STM32F103C8T6 | IO 協處理器 | LQFP-48 | STM32F103CBT6(同腳位加大 Flash) | 低 | ✓ |
| ICM-45686 ×2 | 主 IMU(低噪聲,兩級隔震) | LGA-14 | 與 BMI088 雙 footprint(rev 1 既定,device tree 切換) | 中(單一來源件) | ✓ |
| BMI088 ×1 | 第三 IMU(異廠牌抗共模,耐震動飽和) | LGA-16 | 同上雙 footprint 互為備援 | 中 | ✓ |
| BMP581 ×2 | 氣壓計(獨立氣路) | LGA-10 | 預留 ICP-20100 異廠 footprint(凍結待 rev A 驗證) | 中 | ✓ |
| RM3100 | 磁力計(外置於 GNSS 模組,非核心板) | 模組 | PNI 單一來源;備援 = 雙天線 RTK 定向降低羅盤依賴 | 中 | ✓(美系) |
| FM25V02A | FRAM 參數斷電保存 | SOIC-8 | Fujitsu MB85RS 系列(腳位相容) | 低 | ✓ |
| W25N01GV | 128 MB QSPI Flash 日誌備援 | WSON-8 | Macronix MX35 系列(台系;陸系 NAND 不列) | 低 | ✓(台系) |
| microSD 工業級 | ULog 黑盒主儲存 | socket | SanDisk Industrial / ATP | 低 | ✓ |
| TCAN1042HGV ×2 | CAN-FD 收發器 | SOIC-8 | MCP2562FD(同腳位) | 低 | ✓ |
| LAN8742A | 乙太網 100M PHY(RMII) | QFN-24 | KSZ8081RNA(需 rev A 併驗 layout 相容) | 低 | ✓ |
| TPS3823-33 | 電壓監控 + 外部獨立看門狗 | SOT-23-5 | STM6824(同功能級) | 低 | ✓ |
| LTC4415 | 5V 雙路理想二極體 ORing | MSOP-16 | TPS2121(電源多工器,需改 layout) | 低 | ✓ |

- 全表 IC 納入 NDAA/出口管制檢核表(`hardware/docs/` 維護;檢核時點制度見 [50-project/supply-chain.md §3](../50-project/supply-chain.md))
- ADIS16470(戰術級 IMU)列為認證階段(Phase 3)升級候選,以 IMU 子板外掛評估,不動核心板 layout

## 4. 電源架構

輸入:載板 5V 雙路(Phase 0/EVT 過渡 = PM03D;量產 = 自研 PMU 的 5V/6A Buck ×2,冗餘拓撲見 [system-architecture §2](system-architecture.md))→ 核心板 **LTC4415 理想二極體 ORing** 後分軌,任一路故障不斷電(03-safety FMEA 電源列)。

### 4.1 功耗預算表(rev A 實測後更新)

| 軌 | 負載 | 典型(mA) | 峰值(mA) |
|----|------|-----------|-----------|
| FMU 3.3V(Buck) | STM32H753 @ 480 MHz | 280 | 450 |
| IO 3.3V(獨立 LDO/電源域) | STM32F103 + RC 接收機供電 | 40 | 60 |
| 感測 3.3V(低噪聲 LDO) | IMU ×3 + 氣壓 ×2 + FRAM | 20 | 35 |
| 儲存 3.3V | microSD + QSPI Flash | 60 | 250(寫入突波) |
| 通訊 3.3V | 乙太網 PHY + CAN 收發 ×2 | 120 | 180 |
| 5V 直供 | 蜂鳴器/LED/安全開關 | 30 | 120 |
| 5V 加熱 | IMU 恆溫加熱片(低溫場景才啟用) | 0 | 500 |
| **5V 輸入合計(Buck η≈90%)** | | **~0.5 A ≈ 2.5 W** | 常溫 ~0.9 A ≈ 4.5 W;低溫加熱 ~1.4 A ≈ 7 W |

系統級口徑:FC-H7 取 **~5 W**(峰值均攤)——[system-architecture §2](system-architecture.md) 系統功耗表與 [propulsion §4](propulsion.md)「飛控/感測 ~10 W」(= 本板 ~5 W + 避障感測模組 ~5 W)皆同源於本表。

### 4.2 掉電保持(REQ-SAF-02 的硬體面)

- 斷電偵測:5V 輸入跌破 4.5 V 觸發 NMI → 停止新寫入、flush SD 快取並關檔(≤ 20 ms)
- 保持電容估算:0.9 A × 20 ms ÷ 可用 ΔV 1 V ≈ 18 mF → 取 **10 mF 固態電容 ×2**(rev A 以 VT-SAF-02 斷電注錯 ×20 實測定值)
- 參數走 FRAM(寫入本質斷電安全),不依賴保持電容;備援電池軌(黑盒/RID)由載板供給

## 5. 核心板 ↔ 載板連接器

| pin 群組 | 內容 | pin 數 |
|----------|------|--------|
| 電源 | 5V-A ×3、5V-B ×3、VBACKUP ×2、3.3V_SENS 對外 ×2 | 10 |
| 接地 | GND(高速/類比訊號兩側交錯屏蔽) | ~40 |
| PWM/DShot | MAIN ×8(經 IO)+ AUX ×8(FMU 直出),合計 16(對 §2 PWM ×16) | 16 |
| UART ×5 | GPS1/GPS2 各 2、TELEM1/TELEM2 各 4(含流控)、DEBUG 2;第 6 路 UART 為 FMU↔IO 內部鏈路不出連接器 | 14 |
| CAN ×2 | CAN1/CAN2 各 H+L | 4 |
| SPI/I2C | 外擴 SPI ×1(6)、I2C ×2(GNSS 羅盤/外擴)、SMBus 電池 ×1 | 12 |
| 乙太網 | RMII PHY 在核心板 → MDI 2 對差分 + 屏蔽(載板放磁性件/RJ45 或 M8) | 5 |
| USB | D± + VBUS 偵測 | 3 |
| ADC | 電壓/電流感測 ×4 + 備用 ×2 | 6 |
| GPIO/雜項 | 安全開關、蜂鳴器、LED、SBUS 輸入、nRST/BOOT | 12 |
| **合計** | | **~122** |

選型:**Hirose DF40C-100DS-0.4V ×2**(0.4 mm 節距、雙排 100 pin,合計 200 pin,餘裕 ~39% 供 rev B 增訊號;嵌合高度 1.5–4.0 mm 依載板疊構定)。兩顆分擔「電源+低速」與「高速+類比」,降低串擾;100M/RMII 已定(rev 1 §2),不升 RGMII。

## 6. IO 協處理器安全行為規格

與 [03-safety 失效保護矩陣](../03-safety-analysis.md) 的分工邊界:**Jetson 失聯**由 FMU(PX4)依矩陣列處理,IO 完全不涉入;**IO 介入僅限 FMU 本身當機**——兩者是不同層的失效,不可混談。

| 情境 | IO 行為 |
|------|---------|
| 正常運作 | FMU 經內部 UART(px4io 協議)每週期下發輸出值 + 預存 failsafe 值;IO 疊加 RC 輸入 |
| FMU 心跳逾時(~100 ms 級,rev A 定值)且 RC 在手 | **RC 直通**:手動姿態通道直達輸出混控,操手維持人工控制返場 |
| FMU 心跳逾時且 RC 失聯 | 輸出**預存 failsafe PWM**(預設馬達停轉;具體值隨 phase0 失效保護參數表 v1 管理) |
| 外部 WDT 復位 FMU | IO 維持當前輸出無 glitch,FMU 重啟後重新接管 |
| IO 自身失效 | FMU 保留直接 PWM 旁路腳位(rev A bring-up 驗證項) |

## 7. PCB 開發計畫

| 版本 | 內容 | 時間(Phase 1 內) |
|------|------|------|
| rev A | 原理圖 + layout + 首件 5 pcs,點亮、PX4 board bring-up(檢核清單見 §8) | M1–M3 |
| rev B | 修正 rev A 問題、EMC 預掃、震動測試、環測(-20~60°C) | M4–M6 |
| rev C(DVT) | 量產設計(DFM/DFT)、治具、小批 50 pcs | M7–M9 |

### 工具鏈與產出物

- EDA:KiCad 8(開放格式利於外包協作)或 Altium(若團隊已有授權)
- 版控:硬體設計檔與 BOM 進 git([hardware/](../../hardware/README.md) 目錄),每版 rev 打 tag
- 產出:原理圖 PDF、Gerber、BOM(含替代料)、裝配圖、測試報告

## 8. rev A PX4 bring-up 檢核清單

對 [hardware/README](../../hardware/README.md) 驗收規則「點亮 → PX4 bring-up → 感測全通 → 24h 燒機」的可勾稽展開;證據依 [02-V&V §8](../02-verification-validation.md) 歸檔:

- [ ] 1. 上電前目檢 + 電源網短路測試
- [ ] 2. 電源軌量測:ORing 切換無縫(單路拔除)、3 組 3.3V 軌紋波 < 30 mVpp(對 §4.1 預算逐軌記錄)
- [ ] 3. JTAG/SWD 連通,FMU 與 IO 各自燒錄 PX4 bootloader
- [ ] 4. NuttX console(DEBUG UART)開機訊息,`ver` 確認 fc-h7 board target
- [ ] 5. 感測逐顆 probe:IMU ×3 / 氣壓 ×2 / FRAM / 外接 RM3100 的 WHO_AM_I/ID 讀取全通
- [ ] 6. PWM ×16 示波:頻率/占空正確 + DShot 時序驗證(MAIN 經 IO、AUX 直出各抽測)
- [ ] 7. CAN ×2 loopback、乙太網 loopback + ping、USB 列舉
- [ ] 8. SD 寫入 + ULog 落盤;斷電注錯 ×20 零丟失(VT-SAF-02 前置,§4.2 電容定值依據)
- [ ] 9. EKF2 收斂(靜置 + 手持搖擺無 fault)、三 IMU/雙氣壓投票注錯抽測(VT-SAF-01 前置)
- [ ] 10. 24h 燒機(全感測 + 日誌全程),期間執行 §6 的 FMU 當機注錯 ×3(IO 行為逐格核對)

## 9. PX4 板級支援

- 新增 board target:`boards/<vendor>/fc-h7/`,從 `px4_fmu-v6x` fork 起步(相同 MCU 與感測器拓撲,工作量主要在 pin mapping 與 dts)
- sensor rotation、電源監控參數、預設 airframe config 隨板出廠
- 詳見 [20-software/firmware.md](../20-software/firmware.md)

## 10. 供應鏈備註

- STM32H753 有長期供貨承諾(ST 10-year longevity),但仍鎖第二來源封裝相容方案(§3 替代料欄)
- IMU 為單一來源風險件 → 核心板預留 BMI088 與 ICM-45686 雙 footprint,韌體以 device tree 切換
- 所有關鍵 IC 建立 NDAA/出口管制檢核表(美國市場前置);全案供應鏈風險總表見 [50-project/supply-chain.md §2](../50-project/supply-chain.md)

## 11. 版本紀錄

| rev | 日期 | 變更 |
|-----|------|------|
| 1 | 2026-07 | 初版:策略、規格選型、PCB 三版節奏、PX4 板級支援、供應鏈備註 |
| 2 | 2026-07 | 加關鍵 IC 料號表(§3)、電源架構與功耗預算/掉電保持(§4)、B2B 連接器定義(§5)、IO 安全行為規格(§6)、rev A bring-up 檢核清單(§8);rev 1 全部選型結論不變;作為 M2 規格凍結的飛控側輸入 |
