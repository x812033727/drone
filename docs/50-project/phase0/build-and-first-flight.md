# 50-4-2 開發機組裝與首飛檢查表

> rev 1 · 2026-07。適用 DEV-01 / DEV-02(Holybro X500 V2 + Pixhawk 6X + Jetson Orin Nano 開發套件,見 [procurement.md](procurement.md))。首飛屬 [README.md](README.md) W5 主軸;架次驗證接續 [flight-test-plan.md](flight-test-plan.md)。

## 1. 組裝工序檢查表

依 X500 V2 官方組裝順序,加入本專案差異點。每項完成打勾並由第二人複驗(組裝者 ≠ 複驗者)。

| # | 工序 | 本專案差異點 / 驗收 |
|---|------|---------------------|
| 1 | 機架:底板、機臂、腳架 | 臂管螺絲上藍色螺絲膠並劃記漆線(鬆動目視可判) |
| 2 | 動力:2216 馬達 ×4、ESC、1045 槳(**先不裝槳**) | 馬達座螺絲長度確認不觸線圈;ESC 走臂內,電源線焊點拉力測試 |
| 3 | 配電:PM03D 電源模組 → 分電 | 焊點目檢 + XT60 極性三查;熱縮完整 |
| 4 | 飛控:Pixhawk 6X 減震座安裝 | 箭頭朝機頭;安裝方位與 QGC 內 `SENS_BOARD_ROT` 一致(標準朝向 = 0,不設偏轉) |
| 5 | GNSS:H-RTK F9P 桅杆安裝 | 桅杆遠離 ESC/電源線 ≥ 8 cm;羅盤箭頭朝機頭 |
| 6 | 數傳/RC:Herelink(或 SiK 備援)空中端 | 天線垂直向下、遠離 GNSS;RC failsafe 行為留待參數節設定 |
| 7 | 走線與紮線 | 所有線束離槳盤面;活動端加編織套;插頭全部點膠 |
| 8 | Jetson Orin Nano(W8 起,DEV-02 先行) | 獨立 5V/4A 供電自 PM03D;與 FC 以乙太網連接(uXRCE-DDS) |
| 9 | 銘牌與資產編號 | 機身貼 DEV-01/DEV-02 與 CAA 註冊號 |

## 2. 上電前檢查(每次重大改裝後必做)

- [ ] 萬用表量 XT60 正負極**無短路**(蜂鳴檔);量 5V/12V 軌對地阻值合理
- [ ] 螺絲膠劃線全數完好;槳**未安裝**
- [ ] 電池電壓 15.2–16.8 V(4S)且外觀無膨脹
- [ ] 首次上電用限流電源或煙測器(smoke stopper),電流 < 0.5 A 靜置無異味

## 3. PX4 初始設定清單(v1.15.4)

QGC 依序完成;全部參數改動記入參數表檔案並隨 ULog 歸檔(兩機參數表分開版控)。

1. 韌體:燒錄 PX4 **v1.15.4**(stable,不用 daily)
2. 機架:選 **Holybro X500 V2**(機架清單無此項時選 Generic Quadcopter X 並手動核對動力參數)
3. 感測校準順序:陀螺 → 加速度計 → 羅盤(戶外、遠離鐵磁)→ 水平面
4. RC 校準與開關:模式開關(Position/Altitude/Stabilized)、**Kill switch 必配**、RTL 開關
5. 電池:`BAT1_N_CELLS=4`、`BAT1_V_EMPTY=3.5`、`BAT1_V_CHARGED=4.05`(4S LiPo)

### 失效保護參數表 v1(首飛基線)

| 參數 | 值 | 理由 |
|------|----|------|
| `NAV_RCL_ACT` | 2(RTL) | RC 失聯即返航;開闊場地 RTL 比 Hold 安全 |
| `COM_RC_LOSS_T` | 0.5 s(預設) | 快速判定;Herelink 鏈路品質由 F 架次驗證 |
| `NAV_DLL_ACT` | 0(停用) | Phase 0 以 RC 為主鏈路,GCS 資料鏈失聯不觸發動作,避免雙重觸發 |
| `COM_LOW_BAT_ACT` | 2(Critical 觸發 RTL) | 低電量分級:Low 警告 → Critical 返航 → Emergency 降落 |
| `BAT_LOW_THR` / `BAT_CRIT_THR` / `BAT_EMERGEN_THR` | 0.20 / 0.10 / 0.05 | 首飛期保守;續航基線(F03)後可下修 Low 至 0.15 |
| `GF_ACTION` | 3(RTL) | 越界即返航 |
| `GF_MAX_HOR_DIST` / `GF_MAX_VER_DIST` | 500 m / 100 m | 首飛期小圍欄;任務類架次(F05 起)依航線放寬 |
| `RTL_RETURN_ALT` | 40 m | 高於場地周邊障礙 |
| `RTL_DESCEND_ALT` | 10 m | 返航點上方減速下降起點 |
| `COM_OBL_RC_ACT` | 0(回 Position) | Offboard(Jetson)失聯且 RC 在手 → 交還操手,對齊 [onboard/README](../../../onboard/README.md) 安全邊界 |

## 4. 台架 / 繫留測試(裝槳前後)

| 項 | 內容 | 通過 |
|----|------|------|
| 馬達序 | QGC Actuator 頁逐顆點動,Motor 1–4 位置與轉向對 PX4 Quad X 定義 | 全對(**此項錯誤 = 首飛炸機主因**) |
| ESC 校準 | 依 ESC 型號執行油門行程校準 | 四顆同步啟轉 |
| 全油門拉測 | 繫留狀態 10 s 全油門 | 電流在 PM03D 量程內、無異音 |
| 懸停油門記錄 | 繫留輕載懸浮,記 `MPC_THR_HOVER` 參考值 | 40–55% 區間 |
| 振動初查 | 懸停 1 min 的 ULog,`ulog_report.py` 看加速度 FFT | 槳頻峰值於 EKF 濾波帶外(思路引 [propulsion.md §4](../../10-hardware/propulsion.md)) |

## 5. 首飛程序(M1 檢核起點)

首飛與後續手動/調參飛行**不佔** F01–F20 計數架次(計數規則見 [README.md §3](README.md))。

- 場地:已核准場域、半徑 100 m 淨空、地表無揚塵物;人員僅操手/GCS 手/觀察員三人,站位於起飛點後方 15 m
- 風限:地面實測 ≤ 5 m/s(首飛從嚴;例行架次依 SOP ≤ 8 m/s)
- 剖面:Stabilized(或 Position)起飛 → 2 m 懸停 30 s 檢查漂移/異音 → 四向 5 m 平移 → 10 m 定高盤旋 → 降落。全程 < 3 min,首飛不跑任務
- **Abort 準則**(任一即降落/Kill):異音或振動異常、姿態振盪、GPS 衛星 < 12 或 RTK 無法收斂(僅記錄不擋手動)、電壓驟降 > 0.5 V/cell、任何 QGC 紅色告警
- 首飛完成定義:剖面全程完成、降落後機體檢查無異常、ULog 判讀無紅旗

## 6. 首飛後檢查與歸檔

- [ ] 機體:螺絲劃線、馬達溫度(手觸 < 60°C)、槳尖無傷、腳架無裂
- [ ] `ulog_report.py` 產出首份報告:振動、電壓 sag、GPS 品質三項判讀並存檔
- [ ] 參數表 v1 凍結存檔(此後改動走差異記錄);異常開追蹤單

## 7. 每日飛行前 / 後檢查表(例行,配合 README.md 飛行日 SOP)

**飛行前(每機每日一次)**:機體結構目檢與螺絲劃線 → 槳況與鎖緊 → 電池電壓/內阻記錄與外觀 → GNSS/羅盤桅杆牢固 → RC/數傳鏈路煙霧測試(`telemetry_monitor.py` 掛機確認模式/電池/GPS 三類資料流)→ Kill switch 功能實測(未裝槳點動或地面怠速)→ 圍欄與 RTL 高度參數核對當日場地。

**飛行後(每機每日一次)**:馬達/ESC 溫度手感 → 機體與槳複檢 → ULog 下載歸檔並跑 `ulog_report.py` → 異常追蹤單更新 → 電池放電至儲存電壓(3.80–3.85 V/cell)→ 架次燒盡圖更新(計數架次才計)。
