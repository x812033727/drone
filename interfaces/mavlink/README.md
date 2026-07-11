# interfaces/mavlink — 自訂 MAVLink dialect(骨架)

> 目錄骨架 · 2026-07。訊息定義為**佔位草稿**,Phase 1 啟用(見下);
> 對應 [firmware.md §2](../../docs/20-software/firmware.md)「自訂 MAVLink」客製項
> 與 [interfaces/README](../README.md) 規則 3。

## 用途

GCS ↔ PX4 數傳鏈路上,upstream `common.xml` 沒有的自家訊息:

| 訊息群 | 內容 | 消費端 |
|--------|------|--------|
| 酬載狀態 | 雲台/相機/掛載模組健康與模式 | GCS 儀表、drone-agent 轉遙測 |
| 噴灑遙測 | 流量、藥量餘量、畝用量、斷點(PB-1) | GCS 農噴面板、作業紀錄 |
| 電池詳情 | SMBus 全欄位(單芯電壓/溫度/SoH/告警旗標) | GCS 電池頁、維保開單 |

## 預計 schema

- 本目錄維護 dialect XML(`drone_custom.xml` 為骨架),`<include>common.xml</include>`
  基礎上擴充;不修改 upstream 訊息
- codegen:pymavlink/mavgen 產 C(飛控)與各端綁定,產物進各自 build,
  不像 proto 把生成碼 commit 進版控(MAVLink 生態慣例)

## version 規則

- dialect `<version>` 欄位單調遞增;訊息一經釋出**欄位只增不改**
  (MAVLink 無 proto3 式向後相容,改欄位 = 新訊息 + 舊訊息保留一個相容期)
- message ID 使用私有區段 **24150–24199**(interfaces/README 規則 3),
  ID 分配記錄於 XML 註解,用過的 ID 永不回收
- 與 proto 側同步:跨端結構改動先改 interfaces、PR 標註影響方(規則 1)

## Phase 1 啟用條件

滿足全部三項才把草稿轉正、進 codegen 與 CI:

1. FC-H7 rev A 板級 bring-up 完成,自訂模組(噴灑/智慧電池)開始開發
2. 首個消費端確定(QGC custom-build 或 drone-agent)並完成一輪欄位評審
3. CI 加入 dialect XML 驗證(mavgen dry-run)與 ID 區段占用檢查
