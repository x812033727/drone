# 02 測試與驗證總計畫(V&V)

> rev 1 · 2026-07。本文件定義全案的驗證方法、測試 ID 體系與需求追溯矩陣(RTM),銜接 [01-requirements.md](01-requirements.md)(rev 2 起全需求編 ID)與各階段退出條件([50-project/roadmap.md](50-project/roadmap.md))。子系統既有測試表(韌體 [firmware.md §4](20-software/firmware.md)、動力 [propulsion.md §9](10-hardware/propulsion.md))收編為本體系的測試項,細節仍在原文件維護。

## 1. V&V 策略金字塔

由下而上,每層通過才進上層;上層發現的問題盡量往下層補一個可重現案例:

| 層 | 內容 | 節奏 | 主要證據 |
|----|------|------|----------|
| L1 SITL 回歸 | 任務流程與失效保護場景腳本(見 phase0/sitl-setup.md 場景表),Phase 1 起進 CI nightly | 每 PR / nightly | CI 紀錄 |
| L2 HITL / 台架 | 實體飛控迴圈、推力台、振動台架(propulsion §9 測試項) | 每硬體 rev | 台架報告 |
| L3 繫留 / 場地受限 | 新機型、新失效保護場景第一次實機化 | 進實飛前 | 繫留紀錄 + ULog |
| L4 實飛包線 | 架次制飛測(Phase 0 = F01–F20,見 [flight-test-plan.md](50-project/phase0/flight-test-plan.md);Phase 1 起為 EVT 架次) | 每飛行日 | ULog + ulog_report + 架次紀錄 |
| L5 耐久與統計 | 飛行小時累積、MTBF 統計、DVT/HALT | Phase 1–2 | 可靠度報告 |

## 2. 測試 ID 命名

`VT-<域>-<序號>`,域沿用需求 ID 的域(NAV/COM/SAF/OPS/MAP/SEC/AGR/LOG/ENV)。一個測試可覆蓋多需求、一個需求可需多測試。Phase 0 的 F01–F20 架次是 VT 的**執行載體**:RTM 中以 `F<nn>` 註記承載架次。

## 3. 需求追溯矩陣(RTM)

只列 [M]/[S] 需求;[C] 於進入開發時補列。**驗證階段**:0 = Phase 0 行為驗證(開發機)、1 = PA-1 EVT、2 = DVT/統計、3 = 認證。

### 共通(NAV/COM/SAF/OPS)

| 需求 | 測試 | 方法(層) | 階段 | 通過準則要點 |
|------|------|-----------|------|--------------|
| REQ-NAV-01 | VT-NAV-01 | L4:RTK 實飛對測量標記(Phase 0 粗驗 = F15) | 0→1 | 水平 ±10 cm(Phase 1 用全站儀級基準) |
| REQ-NAV-02 | VT-NAV-02 | L1 場景 + L3 繫留 + L4(遮蔽劣化 = F12) | 0→1 | 降級順序正確、傾角 ≤ 30° |
| REQ-NAV-03 | VT-NAV-03 | L1(F05/F06/F07 SITL 場景已入 nightly,`tools/sitl_scenarios`)+ L4(F01/F05/F06/F07) | 0 | 續飛點誤差 ≤ 5 m |
| REQ-NAV-04 | VT-NAV-04 | L1 全場景(F08–F12 SITL 場景已入 nightly,`tools/sitl_scenarios`)+ L4(F08–F11) | 0 | 各觸發行為與 [03-safety 失效保護矩陣](03-safety-analysis.md) 一致 |
| REQ-NAV-05 | VT-NAV-05 | L3 繫留關單軸 + L4 開闊場(propulsion §9) | 2 | 姿態峰值 < 30° 受控落地 |
| REQ-NAV-06 | VT-NAV-06 | L1 SITL 圖資載入回歸 + L4 場地演示 | 1 | 三區圖資包載入且驗章通過、任務規劃期拒絕禁航區航點、圖資逾期 > 30 天起飛前告警觸發 |
| REQ-COM-01 | VT-COM-01 | L4 距離梯度實測(1/2/4/8 km) | 1 | 8 km 封包成功率 ≥ 99% |
| REQ-COM-02 | VT-COM-02 | L4 主鏈路人工切斷(F 系列延伸) | 1 | ≤ 3 s 切換、任務不中斷 |
| REQ-COM-03 | VT-COM-03 | L2 端到端延遲儀測 + L4 | 1 | < 250 / 500 ms |
| REQ-COM-04 | VT-COM-04 | L2 協議一致性(ASTM F3411) | 3 | 認證實驗室報告 |
| REQ-SAF-01 | VT-SAF-01 | L2 逐感測器注錯 + L1 投票邏輯回歸 | 1 | 單感測器失效零影響 |
| REQ-SAF-02 | VT-SAF-02 | L2 寫入中斷電 ×20(SITL 近似治具:`tools/ulog_powercut_test.sh`,手動跑;實機斷電治具屬飛測週次 / L2 台架項) | 0→1 | 已寫入資料零丟失(F 架次全程 ULog 為佐證);事故調查欄位齊備性檢核(對 [firmware §6](20-software/firmware.md) 記錄內容最小集逐欄比對) |
| REQ-SAF-03 | VT-SAF-03 | L2 BMS 功能 + 委外濫用測試(UN38.3 前置) | 1 | 見 propulsion §9 電池濫用列 |
| REQ-SAF-04 | VT-SAF-04 | L5 機隊統計(Phase 2 試點 500 h) | 2 | MTBF ≥ 300 h(口徑見 §7) |
| REQ-OPS-01 | VT-OPS-01 | 秒表實測 ×10 人次 | 1 | 中位數達標 |
| REQ-OPS-02 | VT-OPS-02 | 維修演練(拆換四大件) | 1 | 每件 < 30 min |
| REQ-OPS-03 | VT-OPS-03 | 端到端演示(Phase 0 雛形 = F19/F20;軟體鏈 SITL 承載:`tools/e2e_demo.sh`,nightly `e2e-demo` job) | 0→2 | 派遣→飛行→日誌上傳全自動 |

### 場景(MAP/SEC/AGR/LOG/ENV)

| 需求 | 測試 | 方法(層) | 階段 | 通過準則要點 |
|------|------|-----------|------|--------------|
| REQ-MAP-01..04 | VT-MAP-01..04 | L4 實地測繪任務 + 成果後處理比對 | 1 | 面積/精度/同步各自達標(GCP 對比報告) |
| REQ-SEC-01..02 | VT-SEC-01..02 | L4 帶載滯空實測 | 1 | 35 min(25°C 無風) |
| REQ-SEC-03..06 | VT-SEC-03..06 | L4 + 雲端端到端 + 夜航專項 | 2 | 排程/分流延遲/夜航檢查表 |
| REQ-AGR-01..07 | VT-AGR-01..07 | L2 流量標定 + L4 田間(坡地專項)+ 鹽霧/浸泡 | 2 | 效率 10 ha/h、流量 ±5%、仿地 ±0.3 m |
| REQ-LOG-01..03 | VT-LOG-01..03 | L2 振動/跌落 + L4 往返航程 + 100 次降落統計 | 2 | 半徑 8 km 剩電 ≥20%、降落 <30 cm(95%) |
| REQ-LOG-04 | VT-LOG-04 | L4 BVLOS 演示(依 SORA 核准範圍) | 3 | 主管機關核准文件 |
| REQ-ENV-01..04 | VT-ENV-01..04 | 環境艙(-10/45°C)、抗風(自然風+風扇牆)、IP 淋雨、海拔(高地實測或艙) | 1→2 | 各級距功能全項通過 |
| REQ-ENV-05 | VT-ENV-05 | 收納量測 + 運輸振動 | 1 | 尺寸與開箱檢查 |

## 4. 各階段驗證關卡(與 roadmap 退出條件一一對齊)

| 關卡 | 對應 roadmap 退出條件 | 本體系門檻 |
|------|----------------------|------------|
| Phase 0 出口 | 20 架次無事故 + 規格凍結 | F01–F20 全銷項;階段 0 的 VT 全通過;RTM 無「無測試對應」的 [M] 需求 |
| Phase 1 出口(EVT) | 滿酬載 35 min、8 km、RTK 精度、失效保護全場景、50 h、rev C 環測 | 階段 1 的 VT 全通過並歸檔;缺陷清單無 S1/S2 未結案 |
| Phase 2 出口(DVT) | 試點續約 ≥2、500 h、重大故障率達標 | 階段 2 VT + VT-SAF-04 統計報告;HALT 完成 |
| Phase 3(PVT/認證) | 台美歐認證 | 階段 3 VT;認證實驗室報告歸檔 |

## 5. 環境/可靠度測試矩陣(摘要)

溫度(工作/儲存)、IP(43/55)、振動(運輸 + 工作)、EMC(rev A 預掃 → rev C 預掃 → 認證正測,時點見 [flight-controller.md](10-hardware/flight-controller.md))、電池(UN38.3 系列,委外)。詳細條件與樣本數於 Phase 1 測試程序書(每 VT 一份)定案。

## 6. 測試設施

推力台(RCbenchmark 級,採購)、振動台/環境艙/RF 暗室(租用,對 [bom.md NRE](10-hardware/bom.md) 測試設備 900K)、試飛場地(Phase 0 起租,見 phase0/README §5)。

## 7. 缺陷分級與放飛標準

| 級 | 定義 | 處置 |
|----|------|------|
| S1 重大 | 炸機/失控/火災/傷損,或任何會導致上述的潛在缺陷 | 全機隊停飛,根因結案前不復飛 |
| S2 嚴重 | 失效保護行為不符預期、冗餘失效、資料丟失 | 該機停飛;她機受限飛行(限縮包線) |
| S3 一般 | 功能缺陷不影響安全(酬載、雲端、UI) | 開單排程修復,不停飛 |
| S4 輕微 | 觀感/文件/非功能 | 彙整處理 |

**重大故障(MTBF 口徑)**= S1 + S2。放飛標準:無 S1/S2 未結案 + 當日檢查表(build-and-first-flight §7)通過。

## 8. 證據歸檔

每 VT 的證據(ULog、報告、影片、儀器數據)按 `VT-ID/日期` 歸檔;架次證據依 flight-test-plan §3 模板。RTM 由架構負責人於每階段關卡前更新一版並標注證據連結。
