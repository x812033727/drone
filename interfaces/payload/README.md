# interfaces/payload — 酬載描述檔 schema(定案 rev 1)

> 定案 rev 1 · 2026-07。`payload-descriptor.schema.json`(schema_version 1.x)欄位、
> 二進位編碼、CRC 與防寫策略已定案並過 meta-schema 驗證;`examples/` 附範例描述檔
> 通過 schema 驗證。對應快拆酬載介面(QR-S/QR-L,見
> [sensors-and-payload.md](../../docs/10-hardware/sensors-and-payload.md))的
> EEPROM 內容定義與 [interfaces/README](../README.md) 規則。

## 用途

每個快拆酬載模組內建 EEPROM,存一份**酬載描述檔**;機上於掛載偵測時讀取:

- **自我介紹**:酬載類型/型號/序號/韌體版——免手動設定,插上即識別
- **資源需求宣告**:供電(電壓/峰值電流)、通訊(DroneCAN node id 範圍/RTSP)、
  重量與重心偏移——飛控/Jetson 據此檢查供電預算並修正質量特性
- **相容性檢查**:酬載韌體版納入 OTA 相容性矩陣
  ([ota.md §5](../../docs/20-software/ota.md) 的 payload 維度)

## schema(定案 rev 1)

- `payload-descriptor.schema.json` = 描述檔的 JSON Schema(Draft 2020-12);
  EEPROM 實際存的是其**緊湊二進位編碼** + CRC,JSON 形式用於工具鏈(產測燒錄、
  除錯 dump、雲端登記)
- `examples/`:`gimbal-eo.descriptor.json`、`sprayer.descriptor.json` 為通過驗證的
  範例描述檔
- 消費端:PX4(質量/供電檢查)、Jetson drone-agent(識別上報)、
  產測燒錄治具([manufacturing.md §6](../../docs/50-project/manufacturing.md))

### 二進位編碼與完整性(定案)

`eeprom` 物件為 firmware 讀寫端與燒錄治具的共同契約:

- **編碼**:確定性 CBOR(RFC 8949 §4.2.1 core-deterministic),同一描述檔跨工具
  產生相同位元組,CRC 方可比對
- **表頭**:EEPROM 起始 4-byte ASCII 魔數 `DPD1` + `layout_version`(對齊
  schema_version 之 MAJOR;MAJOR 佈局變更時魔數末碼遞增 `DPD2…`)
- **兩段式佈局**:`frozen` 區(身分/資源宣告,出廠燒錄後由防寫機制鎖定唯讀)與
  `writable` 區(允許受控更新的欄位,預設僅 `/fw_version`)
- **CRC**:`CRC-32/ISO-HDLC`(標準 CRC-32,zlib/PNG 相容;poly `0x04C11DB7`、
  init/xorout `0xFFFFFFFF`、refin/refout=true,自檢值 `check=0xCBF43926`);
  frozen 與 writable 兩區各帶一枚 4-byte CRC,小端序存於各區尾端;讀取端先驗
  CRC 再解 CBOR,writable 區每次寫入後重算其 CRC
- **防寫**:`write_protect.mechanism` = EEPROM 區塊保護暫存器 /硬體 `/WP` 腳位
  /兩者併用;frozen 區於產測燒錄後上鎖(`frozen_locked=true`)

### 驗證

```bash
pip install jsonschema
python - <<'PY'
import json
from jsonschema import Draft202012Validator as V
s = json.load(open("payload-descriptor.schema.json"))
V.check_schema(s)                     # schema 本身合法(meta-schema)
for f in ("examples/gimbal-eo.descriptor.json","examples/sprayer.descriptor.json"):
    V(s).validate(json.load(open(f))) # 範例通過 schema
print("OK")
PY
```

## version 規則

- 描述檔帶 `schema_version`(SemVer):MINOR = 加欄位(舊讀取端忽略未知欄),
  MAJOR = 布局變更(讀取端須同時支援 N 與 N-1,機隊酬載不會同步換代)
- EEPROM 內容一經出廠燒錄即凍結;欄位更新(如韌體版)只允許指定的可寫區

## Phase 1 啟用狀態

schema 定案(rev 1)已完成:欄位、二進位編碼、CRC 與防寫策略齊備並過驗證。
剩餘為硬體與產線落地:

1. ✅ 描述檔欄位 + 二進位編碼 + CRC/防寫策略定案(rev 1) — 本 PR
2. ⬜ QR-S/QR-L 電氣介面凍結(連接器/供電/通訊腳位定案)
3. ⬜ 首個實體酬載模組(雲台構型)進入整合,依範例描述檔實際燒錄
4. ⬜ 產測燒錄工具實作(CBOR 編碼 + CRC 計算 + 防寫上鎖)並就緒
