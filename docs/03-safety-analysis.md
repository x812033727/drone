# 03 安全分析(危害清單 / FMEA / 失效保護矩陣)

> rev 1 · 2026-07。本文件是全案的系統安全分析:危害清單(Hazard Log)、功能 FMEA、與**失效保護矩陣**——後者是 [firmware.md §2](20-software/firmware.md) 失效保護客製項的規格輸入,行為驗證由 [02-V&V](02-verification-validation.md) 的 VT-NAV-04 承載(Phase 0 載體 = F09–F12,見 [flight-test-plan.md](50-project/phase0/flight-test-plan.md))。需求引用一律用 [01-requirements.md](01-requirements.md) 的 REQ ID。

## 1. 風險分級方法

嚴重度 × 可能性矩陣(工程用簡表,認證階段再對齊各區官方準則):

- **嚴重度**:I 災難(死亡/重傷/全機損毀)、II 危險(輕傷/重大財損/機體大修)、III 中度(輕微財損/任務中止)、IV 輕微(觀感/輕微損傷)
- **可能性**:A 頻繁 / B 常見 / C 偶發 / D 稀少 / E 極少
- **殘餘風險**:高(I×A–C、II×A–B)不可放飛;中(I×D–E、II×C–D、III×A–B)需管理措施並追蹤;低(其餘)可接受

## 2. 危害清單(Hazard Log)

| 危害 | 嚴重度×可能性(緩解前) | 現有緩解 | 殘餘風險 |
|------|------------------------|----------|----------|
| 撞人(飛行中撞及第三方) | I × C | 不飛越人群(§7)、GeoFence(REQ-NAV-04)、失效保護矩陣(§4)、避障感測([system-architecture §1](10-hardware/system-architecture.md))、PB-1 降落傘(§5) | 中 |
| 撞障礙/建物 | II × C | 避障(雙目/ToF/毫米波)、RTL 返航高度(`RTL_RETURN_ALT`)、禁航區圖層([certification-roadmap §4](40-regulatory/certification-roadmap.md)) | 低 |
| 失控墜落(控制/導航失效) | I × C | 三冗餘 IMU(REQ-SAF-01)、GNSS 降級鏈(REQ-NAV-02)、PB-1 動力冗餘(REQ-NAV-05)、飛控/Jetson 隔離(§3)、SITL 失效保護回歸(02-V&V L1) | 中 |
| 電池熱失控——飛行中 | I × D | BMS 電芯監控(REQ-SAF-03)、熱失控傳播隔離 pack 設計(§6) | 中 |
| 電池熱失控——充電中 | II × C | 智慧充電監視、充電不離人、儲存電壓管理(§6,引 phase0 SOP) | 低 |
| 電池熱失控——運輸中 | II × D | UN38.3 認證前置 + 運輸標籤(§6) | 低 |
| 藥液暴露(PB-1 農噴,人員/環境) | III × B | IP55 + 耐化學接觸件(REQ-AGR-06)、流量閉環防過噴(REQ-AGR-03)、加藥 SOP 防護具(Phase 2 作業手冊) | 低 |
| 螺旋槳傷害(地勤) | II × C | Kill switch 必配、未裝槳完成馬達序/點動測試、上電與飛行前檢查表([build-and-first-flight §2/§7](50-project/phase0/build-and-first-flight.md)) | 低 |

## 3. 功能 FMEA(子系統級)

| 子系統 | 失效模式 | 影響 | 偵測手段 | 緩解 / 相關需求 |
|--------|----------|------|----------|-----------------|
| 動力 | 單馬達/ESC 失效 | **PA-1 四軸:不可控墜落**;**PB-1 六軸:可控降落**(六軸幾何 + control allocation,[propulsion §3](10-hardware/propulsion.md)) | ESC DroneCAN 遙測(轉速/溫度)、姿態異常 | PA-1 以動力系統可靠度補償、PB-1 單馬達失效可控降落(REQ-NAV-05,VT-NAV-05 繫留關單軸驗證) |
| 感測 | 單 IMU 漂移/失效;單氣壓計失效 | 姿態/高度估算劣化 | 三 IMU / 雙氣壓投票與故障隔離 | 單感測器失效不影響飛行(REQ-SAF-01,VT-SAF-01 注錯驗證) |
| 導航 | RTK 丟失(降回單點) | 定位精度由 cm 級退到 m 級,測繪/精準降落成果失效,飛行本身仍受控 | RTK Fixed/Float 狀態、基準站鏈路心跳 | 降級為 GNSS 單點續飛(REQ-NAV-02);精度敏感任務(REQ-MAP-02、REQ-LOG-03)由 GCS 告警中止或重試 |
| 導航 | GPS 拒止/嚴重劣化 | 位置估算發散 → 漂移/失控 | EKF 新息檢核、衛星數/DOP 門檻 | 依序降級 GNSS 單點 → 光流/視覺 → 安全降落,全程傾角 ≤ 30°、無不可命令的位移發散(REQ-NAV-02,VT-NAV-02 = F12 遮蔽劣化) |
| 通訊 | RC 失聯(單獨) | 失去人工接管 | `COM_RC_LOSS_T` 逾時 | RTH(REQ-NAV-04);§4 矩陣列 1 |
| 通訊 | 數傳或 4G 單鏈路失效 | BVLOS 監控降級 | 鏈路心跳 | 雙鏈路 ≤ 3 s 切換、任務不中斷(REQ-COM-02) |
| 通訊 | 數傳 + 4G + RC 同時失聯 | 完全失聯 | 各鏈路逾時疊加 | RTH;§4 矩陣列 1/2 疊加(以 RC 失聯行為為準) |
| 電源 | PMU 單點失效(配電板故障) | 航電/動力同時斷電 → 墜落 | 母線電壓/電流監測 | 飛控 5V 雙 Buck ORing(任一 Buck 故障不斷電)、備援電池保黑盒子/RID;酬載電源獨立限流,酬載短路不影響飛行系統([system-architecture §2](10-hardware/system-architecture.md));PMU 本體為殘餘單點,以設計裕度 + L2 台架驗證管理 |
| 電源 | 母線電壓驟降(電芯劣化/內阻) | 動力餘裕不足、觸發低壓保護 | BMS 電芯電壓/內阻(REQ-SAF-03)、飛行前電壓內阻記錄 | 電壓驟降 > 0.5 V/cell 列為 Abort 準則([build-and-first-flight §5](50-project/phase0/build-and-first-flight.md));低電量三級行為見 §4 |
| 酬載 | 貨箱鎖固失效(PB-1 物流) | 貨物脫落傷人 | 鎖固偵測開關 + 重量異常偵測(firmware §2) | 未鎖妥禁止解鎖起飛(REQ-LOG-01);§4 矩陣列 9 |
| 機載電腦 | Jetson 當機 / Offboard 失聯 | 失去避障與任務轉譯,**不影響飛安** | uXRCE-DDS/MAVLink 心跳逾時 | 飛控與 Jetson 隔離,只接受經 PX4 驗證的指令;感知模組僅發速度限制/setpoint 修正,絕不發姿態級指令([onboard/README](../onboard/README.md) 安全邊界) |

## 4. 失效保護矩陣(firmware 客製規格輸入)

飛行狀態欄定義:**地面待命** = 已上電未解鎖(觸發行為多為拒絕解鎖,REQ-NAV-04 的預防面);**手動飛行** = Position/Altitude/Stabilized 操手在控;**自動任務** = Mission/Offboard;**返航中** = RTL 執行中;**降落中** = 最終下降段(此段原則上不再切換行為,避免低高度反覆改判)。

行為詞彙:**繼續**(不改變當前行為)/ **警告**(GCS 告警,不自動介入)/ **懸停** / **RTH**(返航)/ **就地降落** / **開傘**(PB-1)/ **拒絕解鎖**。標記:**†** = Phase 1+ 才實作(Phase 0 不啟用);**‡** = PB-1 構型專屬(農噴 Phase 2 / 物流降落傘 Phase 3,REQ-LOG-04)。

| 觸發事件 | 地面待命 | 手動飛行 | 自動任務 | 返航中 | 降落中 |
|----------|----------|----------|----------|--------|--------|
| RC 失聯 | 拒絕解鎖 | RTH | RTH(Phase 1+ 雙鏈路在線可設繼續任務†) | 繼續 | 繼續(完成降落) |
| 數傳 + 4G 全失聯(RC 在線) | 拒絕解鎖(BVLOS 任務) | 警告 | 警告;BVLOS 場景 RTH† | 繼續 | 繼續 |
| 低電量 Low | 拒絕解鎖 | 警告 | 警告(GCS 建議返航) | 繼續 | 繼續 |
| 低電量 Critical | 拒絕解鎖 | RTH | RTH | 繼續 | 繼續 |
| 低電量 Emergency | 拒絕解鎖 | 就地降落 | 就地降落 | 就地降落 | 繼續 |
| GPS 劣化 | 自動任務拒絕解鎖;手動僅警告 | 警告(依 REQ-NAV-02 降級) | 懸停 → RTH(單點精度足夠時);再劣化 → 安全降落 | 繼續(降級鏈保底安全降落) | 繼續 |
| GeoFence 越界 | 拒絕解鎖(起飛點在圍欄外) | RTH | RTH | 繼續 | 繼續 |
| 藥量盡(AGR)‡ | 拒絕解鎖(藥量不足額定航段) | 警告 | 記斷點 → RTH(REQ-AGR-05) | 繼續 | 繼續 |
| 鎖固異常(LOG)‡ | 拒絕解鎖(REQ-LOG-01) | 警告 + 就近降落(操手判定) | 懸停 + 緊急告警;無人介入逾時 → 就地降落 | 繼續 | 繼續 |
| Jetson 失聯 | 警告(可解鎖,不影響飛安) | 繼續(警告) | Offboard 段:交還操手(RC 在手);RC 不在 → RTH | 繼續 | 繼續 |

補充規則:
- 姿態失控(傾角超限持續且動力冗餘無法恢復)於 PB-1 物流構型任何飛行狀態觸發**開傘†‡**(觸發邏輯見 §5);PA-1 無傘,依賴上表預防性行為。
- 多重觸發同時發生時,取行為嚴重度較高者(就地降落/開傘 > RTH > 懸停 > 警告)。

### 4.1 與 Phase 0 失效保護參數表 v1 的對照

上表的 Phase 0 子集必須與 [build-and-first-flight §3](50-project/phase0/build-and-first-flight.md) 參數表 v1 逐格一致;參數表改版時本表同步重審(§8)。行為驗證載體 = F09–F12([flight-test-plan.md](50-project/phase0/flight-test-plan.md)),對應 VT-NAV-04。

| 矩陣列 | Phase 0 參數(v1) | 承載架次 |
|--------|-------------------|----------|
| RC 失聯 | `NAV_RCL_ACT=2`(RTL)、`COM_RC_LOSS_T=0.5 s` | F09 |
| 數傳 + 4G 全失聯 | `NAV_DLL_ACT=0`(Phase 0 以 RC 為主鏈路,僅警告不動作,與本表「警告」格一致;BVLOS 格為 †) | —(Phase 1 起) |
| 低電量 Low/Critical/Emergency | `COM_LOW_BAT_ACT=3`(Critical 返航、Emergency 降落;v1.15 的 2=Land mode,SITL 實測修正)+ 門檻 0.20 / 0.10 / 0.05 | F10 |
| GPS 劣化 | 無專屬參數(EKF 降級行為),Phase 0 僅遮蔽劣化不做全拒止 | F12 |
| GeoFence 越界 | `GF_ACTION=3`(RTL)、圍欄 500 m / 100 m | F11 |
| Jetson 失聯 | `COM_OBL_RC_ACT=0`(Offboard 失聯且 RC 在手 → 交還 Position) | —(W8 起 DEV-02 驗證) |
| 藥量盡 / 鎖固異常 / 開傘 | 非 Phase 0 範圍(PB-1 構型,‡) | — |

## 5. PB-1 特有安全機制

- **降落傘(物流構型,REQ-LOG-04)**:三種觸發——(1) 手動:GCS/遙控器專用開關(不可逆操作,二次確認);(2) 姿態:傾角超限持續且無法由動力冗餘恢復時自動觸發;(3) 高度下限:低於開傘有效高度(依傘廠數據於 Phase 2 定值)時**抑制自動開傘**(開傘無效反增風險),僅保留手動。開傘同時切斷動力(經急停接觸器)。
- **急停接觸器**:PMU 內建接觸器 + 預充電路([system-architecture §2](10-hardware/system-architecture.md)),地面急停與開傘斷電共用。
- **SORA 減緩措施對照**([certification-roadmap §4](40-regulatory/certification-roadmap.md) 設計即合規清單):降落傘 → 地面風險減緩;急停 + 鎖固偵測(REQ-LOG-01)→ 墜落物/地面人員防護;GeoFence + 失效保護矩陣(§4)→ 操作範圍遏制;ULog 全程紀錄(REQ-SAF-02)→ 事故調查佐證。歐盟 Specific 類客戶的 SORA 技術資料包以本文件 §2–§5 為素材。

## 6. 電池安全

- **認證前置**:UN38.3(REQ-SAF-03);過充/過放/短路/針刺濫用測試委外執行([propulsion §9](10-hardware/propulsion.md) 電池濫用列)。
- **熱失控傳播隔離(pack 設計要求,交付 pack 廠)**:電芯間隔熱、洩壓路徑避開相鄰電芯與航電艙、單電芯熱失控不得引燃相鄰電芯;BMS 全程監控電芯溫度並於異常時觸發 GCS 緊急告警。
- **充電/儲運規範**(引 phase0 SOP,[build-and-first-flight §2/§7](50-project/phase0/build-and-first-flight.md)):上電前電壓與外觀(膨脹)檢查;飛行後放電至儲存電壓(3.80–3.85 V/cell);充電不離人、遠離可燃物;運輸依 UN38.3 + 標籤([certification-roadmap §4](40-regulatory/certification-roadmap.md))。

## 7. 操作安全邊界

- **風限**:Phase 0 首飛 ≤ 5 m/s、例行架次 ≤ 8 m/s(地面實測,[build-and-first-flight §5](50-project/phase0/build-and-first-flight.md));REQ-ENV-02 的 12/10 m/s 是機體包線,不是日常操作上限——操作手冊以留裕度的作業風限為準。
- **人群距離**:不飛越人群;人群上方/夜間/BVLOS 屬專案申請事項([certification-roadmap §1](40-regulatory/certification-roadmap.md))。Phase 0 場地半徑 100 m 淨空、僅必要人員。
- **夜航前置**:防撞燈 + 熱像導航輔助(REQ-SEC-06)完成驗證前不排夜航。
- **GCS 告警對應**([ground-station §4](20-software/ground-station.md) 三級告警):§4 矩陣的「警告」→ GCS 提示/警告級;「懸停 / RTH / 就地降落 / 開傘」→ 緊急級(全螢幕 + 語音 + 建議動作按鈕);開傘與強制降落屬不可逆操作,手動路徑需二次確認。

## 8. 安全審查節奏

- **每 Phase 出口**:FMEA(§3)與失效保護矩陣(§4)全面重審,隨 [02-V&V §4](02-verification-validation.md) 階段關卡與 RTM 更新同步歸檔。
- **事件觸發強制重審**:任何事故、或 S1/S2 缺陷(分級見 [02-V&V §7](02-verification-validation.md))結案前,必須重審對應的 FMEA 列與矩陣格,並向下層(L1 SITL)補一個可重現案例。
- **變更觸發**:新酬載/新構型導入、失效保護參數表改版(phase0 起走差異記錄)時,重審受影響列。

## 9. 版本紀錄

| rev | 日期 | 變更 |
|-----|------|------|
| 1 | 2026-07 | 初版:危害清單、功能 FMEA、失效保護矩陣(對接參數表 v1 與 VT-NAV-04) |
| 2 | (Phase 0 出口) | 依 F09–F12 實測結果與參數表差異記錄重審定版 |
