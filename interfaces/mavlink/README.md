# interfaces/mavlink — 自訂 MAVLink dialect(定案 rev 1)

> 定案 rev 1 · 2026-07。三則訊息(`PAYLOAD_STATUS` / `SPRAY_TELEMETRY` /
> `BATTERY_DETAIL`)欄位已定案並過 mavgen 驗證(見下「驗證」);
> 對應 [firmware.md §2](../../docs/20-software/firmware.md)「自訂 MAVLink」客製項
> 與 [interfaces/README](../README.md) 規則 3。dialect `<version>` = 1。

## 用途

GCS ↔ PX4 數傳鏈路上,upstream `common.xml` 沒有的自家訊息:

| 訊息 | ID | 內容 | 消費端 |
|------|----|------|--------|
| `PAYLOAD_STATUS` | 24150 | 酬載通用狀態:類型/實例/狀態機/故障旗標/溫度/韌體版(1 Hz) | GCS 儀表、drone-agent 轉遙測 |
| `SPRAY_TELEMETRY` | 24151 | 噴灑作業遙測:流量(含設定值)/藥量餘量/施用量/泵壓/噴桿幅寬/泵狀態/旗標(PB-1) | GCS 農噴面板、作業紀錄 |
| `BATTERY_DETAIL` | 24152 | 智慧電池電芯級:各電芯電壓(至 14S)/溫度/循環數/SoH/SoC/容量/BMS 故障旗標(SMBus) | GCS 電池頁、維保開單 |

`BATTERY_DETAIL` 補充 common.xml `BATTERY_STATUS`(147)未涵蓋的電芯級資料;
`id` 欄位與 `BATTERY_STATUS.id` 對齊。無效值沿用 common 慣例(整數用型別最大值、
浮點用 NaN)。

## 欄位定案摘要(rev 1)

- **型別/單位/命名遵循 common.xml 風格**;單位用標準記法(`[ms]`/`[V]`/`[A]`/
  `[cA]`/`[mV]`/`[mAh]`/`[cdegC]`/`[bar]`/`[%]`/`[m]`/`[ml/s]`/`[ml]`/`[ml/m2]`)
- 五個自訂 enum:`DRONE_PAYLOAD_TYPE`、`DRONE_PAYLOAD_STATE`、
  `DRONE_PAYLOAD_FAULT_FLAGS`(bitmask)、`DRONE_SPRAY_PUMP_STATE`、
  `DRONE_SPRAY_FLAGS`(bitmask)、`DRONE_BATTERY_FAULT_FLAGS`(bitmask)
- 訊息一經釋出**欄位只增不改**(MAVLink 無 proto3 式相容,改欄位 = 新訊息 +
  舊訊息保留一個相容期)

## 驗證

`drone_custom.xml` 已用 pymavlink/mavgen 驗證可生成 C 與 Python 綁定,並通過
三則訊息的 encode→wire→decode 往返;訊息 ID 落在私有區段、不重複,各訊息欄位名
唯一,bitmask enum 值皆為 2 的冪。本機重現(需 `pip install pymavlink`,將
upstream `common.xml`/`standard.xml`/`minimal.xml` 與本檔置於同目錄;
⚠️ pip 包的 mavgen 入口是 console script,`pymavlink.tools` 不隨包發佈;
upstream XML 需用與 pymavlink 版本配對的 commit,master 最新 schema 元素舊版
mavgen 會拒絕——配對值見 `.github/workflows/mavlink-ci.yml`):

```bash
mavgen.py --lang=C --wire-protocol=2.0 --output=/tmp/out drone_custom.xml
```

CI 守門:`mavlink-ci.yml`(靜態檢查 `check_dialect.py` + mavgen C/Python
dry-run),path-gated 於 `interfaces/mavlink/**`。

## 預計 schema

- 本目錄維護 dialect XML(`drone_custom.xml`),`<include>common.xml</include>`
  基礎上擴充;不修改 upstream 訊息
- codegen:pymavlink/mavgen 產 C(飛控)與各端綁定,產物進各自 build,
  不像 proto 把生成碼 commit 進版控(MAVLink 生態慣例)

## version 規則

- dialect `<version>` 欄位單調遞增;訊息一經釋出**欄位只增不改**
  (MAVLink 無 proto3 式向後相容,改欄位 = 新訊息 + 舊訊息保留一個相容期)
- message ID 使用私有區段 **24150–24199**(interfaces/README 規則 3),
  ID 分配記錄於 XML 註解,用過的 ID 永不回收
- 與 proto 側同步:跨端結構改動先改 interfaces、PR 標註影響方(規則 1)

## Phase 1 啟用狀態

欄位定案(rev 1)已完成:三則訊息與 enum 定義齊備、mavgen 生成與往返驗證通過
(見「驗證」)、ID 區段/欄位唯一性/bitmask 已檢查。剩餘為硬體與工具鏈落地:

1. ✅ 欄位定案 rev 1(型別/單位/命名/無效值語意) — 本 PR
2. ⬜ FC-H7 rev A 板級 bring-up 完成,自訂模組(噴灑/智慧電池)韌體開始送這些訊息
3. ⬜ 首個消費端(QGC custom-build 或 drone-agent)接上並回饋
4. ✅ CI 加入 dialect XML 驗證(mavgen dry-run)與 ID 區段占用檢查 — `mavlink-ci.yml` + `check_dialect.py`

> 欄位一經釋出即凍結;後續調整循「欄位只增不改 / 改欄位開新訊息」規則,
> dialect `<version>` 隨之遞增。
