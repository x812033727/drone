# interfaces/payload — 酬載描述檔 schema(骨架)

> 目錄骨架 · 2026-07。schema 為**佔位草稿**,Phase 1 啟用(見下);
> 對應快拆酬載介面(QR-S/QR-L,見
> [sensors-and-payload.md](../../docs/10-hardware/sensors-and-payload.md))的
> EEPROM 內容定義與 [interfaces/README](../README.md) 規則。

## 用途

每個快拆酬載模組內建 EEPROM,存一份**酬載描述檔**;機上於掛載偵測時讀取:

- **自我介紹**:酬載類型/型號/序號/韌體版——免手動設定,插上即識別
- **資源需求宣告**:供電(電壓/峰值電流)、通訊(DroneCAN node id 範圍/RTSP)、
  重量與重心偏移——飛控/Jetson 據此檢查供電預算並修正質量特性
- **相容性檢查**:酬載韌體版納入 OTA 相容性矩陣
  ([ota.md §5](../../docs/20-software/ota.md) 的 payload 維度)

## 預計 schema

- `payload-descriptor.schema.json`(草稿)= 描述檔的 JSON Schema;
  EEPROM 實際存的是其**緊湊二進位編碼**(CBOR 候選,Phase 1 定案)+ CRC,
  JSON 形式用於工具鏈(產測燒錄、除錯 dump、雲端登記)
- 消費端:PX4(質量/供電檢查)、Jetson drone-agent(識別上報)、
  產測燒錄治具([manufacturing.md §6](../../docs/50-project/manufacturing.md))

## version 規則

- 描述檔帶 `schema_version`(SemVer):MINOR = 加欄位(舊讀取端忽略未知欄),
  MAJOR = 布局變更(讀取端須同時支援 N 與 N-1,機隊酬載不會同步換代)
- EEPROM 內容一經出廠燒錄即凍結;欄位更新(如韌體版)只允許指定的可寫區

## Phase 1 啟用條件

1. QR-S/QR-L 電氣介面凍結(連接器/供電/通訊腳位定案)
2. 首個實體酬載模組(雲台構型)進入整合,描述檔欄位過一輪評審
3. 二進位編碼與 CRC/防寫策略定案,產測燒錄工具就緒
