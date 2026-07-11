# 10-1 系統架構

> rev 2 · 2026-07。拓撲與匯流排結論不變;本版於 §2 加系統級功耗預算表(數字單一事實來源在各子系統文件)、§4 加酬載介面連接器列、新增 §5 介面契約索引。

## 1. 全系統方塊圖

兩個平台共用同一套航電拓撲(AC-1),差異只在動力規模與酬載。

```mermaid
flowchart TB
    subgraph AVIONICS["航電核心 AC-1(兩平台共用)"]
        FC["飛控 FC-H7<br/>STM32H753 + IO STM32F103<br/>PX4"]
        CC["機載電腦<br/>Jetson Orin NX 16GB<br/>ROS 2"]
        GNSS["GNSS RTK<br/>ZED-F9P + RM3100 磁力計"]
        RADIO["數傳/遙控<br/>2.4 GHz"]
        LTE["5G 模組<br/>RM520N-GL"]
        RID["Remote ID<br/>廣播模組"]
        FC <-->|"MAVLink / uXRCE-DDS<br/>(Ethernet)"| CC
        GNSS -->|UART + DroneCAN| FC
        RADIO <-->|MAVLink| FC
        CC <--> LTE
        FC --> RID
    end

    subgraph SENSORS["感測與避障"]
        STEREO["雙目相機(前/下)"]
        RADAR["毫米波雷達 60GHz<br/>(PB-1 仿地/上下避障)"]
        TOF["上視 ToF(PA-1)"]
        STEREO --> CC
        RADAR --> CC
        TOF --> CC
    end

    subgraph POWER["動力系統"]
        BATT["智慧電池<br/>PA-1: 12S 12Ah<br/>PB-1: 14S 22Ah×2"]
        PMU["電源管理 PMU<br/>(自研,含配電/監測)"]
        ESC["FOC 電變 ×4/×6<br/>(DroneCAN)"]
        MOTOR["無刷馬達 ×4/×6"]
        BATT --> PMU
        PMU -->|高壓母線| ESC
        ESC --> MOTOR
        PMU -->|"5V / 12V"| AVIONICS
        ESC -->|DroneCAN 遙測| FC
        BATT -->|SMBus| FC
    end

    subgraph PAYLOAD["模組化酬載(快拆介面)"]
        GIMBAL["雲台相機 / 雙光"]
        SPRAY["噴灑系統(PB-1)"]
        CARGO["貨箱(PB-1)"]
        GIMBAL <-->|"12V + Ethernet + CAN"| CC
        SPRAY <-->|CAN| FC
        CARGO <-->|CAN| FC
    end

    subgraph GROUND["地面/雲端"]
        RC["手持遙控器<br/>(內建 GCS)"]
        CLOUD["雲端機隊平台"]
        RC <-->|2.4 GHz| RADIO
        CLOUD <-->|"4G/5G"| LTE
    end
```

### 架構要點

1. **飛控與機載電腦分離**:安全關鍵的飛行控制(PX4/FC-H7)與高算力應用(AI/避障/影像)隔離。Jetson 當機不影響飛安;飛控只接受經過驗證的 MAVLink 指令
2. **匯流排策略**:
   - 馬達電變、GNSS、酬載控制走 **DroneCAN**(抗噪、可熱插拔、有標準協議)
   - 飛控 ↔ 機載電腦走 **Ethernet(uXRCE-DDS + MAVLink)**,頻寬足夠傳感測器融合資料
   - 電池走 **SMBus**(智慧電池業界慣例)
3. **雙鏈路通訊**:2.4 GHz 數傳(低延遲、視距)+ 5G(BVLOS、影像上雲),飛控端自動路由
4. **酬載介面標準化**:機械快拆 + 12V 供電 + Ethernet + CAN,詳見 [30-structure/payload-interface.md](../30-structure/payload-interface.md)

## 2. 電源樹

```mermaid
flowchart LR
    B["電池<br/>PA-1: 12S 44.4V<br/>PB-1: 14S 51.8V ×2"] --> PMU["PMU 自研配電板"]
    PMU -->|"高壓直通<br/>(接觸器+保險)"| ESCBUS["ESC 母線"]
    PMU --> DC12["12V/8A Buck"]
    PMU --> DC5["5V/6A Buck ×2(冗餘)"]
    DC12 --> PL["酬載 12V"]
    DC12 --> CCP["Jetson(12V 輸入)"]
    DC5 --> FCP["飛控(雙路 ORing)"]
    DC5 --> RP["數傳/GNSS/Remote ID"]
    BKP["備援電池<br/>(黑盒子/RID)"] -.-> FCP
```

- 飛控 5V 供電雙路 ORing:任一 Buck 故障不斷電
- PMU 量測母線電壓/電流,提供 PX4 電量估算;PB-1 版含預充電路(大電容 ESC 突波)與接觸器急停
- 酬載電源獨立限流,酬載短路不影響飛行系統

### 系統級功耗預算(rev A/EVT 實測後更新)

本表僅系統彙總;各數字的細目與單一事實來源在對應子系統文件(飛控細目在 [flight-controller.md §4](flight-controller.md)),與 [propulsion §4](propulsion.md)「航電 ~50 W」同口徑。

| 負載 | 預算 | 細目來源 |
|------|------|----------|
| Jetson Orin NX 16GB | ~25 W(峰值) | 20-software 機載應用側寫 |
| 飛控 FC-H7(含板上感測) | ~5 W(峰值口徑) | flight-controller §4.1 功耗預算表 |
| 數傳空中端 | ~8 W | communication.md |
| 5G RM520N-GL | ~6 W | communication.md |
| Remote ID | ~1 W | — |
| 避障感測(雙目/ToF/毫米波) | ~5 W | sensors-and-payload.md |
| **航電合計(不含酬載)** | **~50 W** | = propulsion §4 續航計算的航電項 |
| 相機/雲台(酬載 12V,獨立限流) | 10–15 W 預算 | [payload-interface.md](../30-structure/payload-interface.md) |

## 3. 資料流(任務執行時)

| 資料 | 路徑 | 頻率/頻寬 |
|------|------|-----------|
| 姿態控制迴路 | IMU → PX4 rate loop → ESC | 2 kHz 內迴路 |
| 位置控制 | GNSS/氣壓/光流 → EKF2 → 位置環 | 50 Hz |
| 避障 | 雙目/雷達 → Jetson(深度→佔據圖)→ 速度限制/繞行指令 → PX4 | 15–30 Hz |
| 遙測下行 | PX4 → 數傳 + Jetson → 5G → 雲端 | 1–4 Hz 摘要 + 事件 |
| 影像 | 雲台 → Jetson(編碼 H.265)→ 數傳/5G → GCS/雲端 | 1080p30, 2–8 Mbps |
| 日誌 | PX4 ULog → SD + 落地後自動上傳雲端 | 全程 |

## 4. 平台差異一覽

| 項目 | PA-1 | PB-1 |
|------|------|------|
| 動力 | 4 × MN505-S KV320 + 18" 槳 | 6 × P80 III KV100 + 30" 槳 |
| ESC | 40 A FOC DroneCAN | 80 A HV FOC DroneCAN |
| 電池 | 12S 12 Ah ×1 | 14S 22 Ah ×2(並聯、熱插拔) |
| GNSS 天線 | 單天線 RTK | 雙天線 RTK(定向,抗磁干擾) |
| 避障 | 前/下雙目 + 上 ToF | 前雙目 + 上/下毫米波 + 仿地雷達 |
| 酬載介面 | 下掛單點快拆 | 腹部大型快拆(藥箱/貨箱互換) |
| 酬載介面連接器 | QR-S | QR-L(選型與 pinout 見 [payload-interface.md](../30-structure/payload-interface.md),此處不重複) |
| 額外安全 | — | 降落傘艙(物流構型)、急停接觸器 |

## 5. 介面契約索引

跨端(機上/地面站/雲端)協議的單一事實來源在 [interfaces/](../../interfaces/README.md),契約先行、獨立版本化,本節僅索引:

| 契約 | 內容 | 位置 |
|------|------|------|
| MAVLink dialect | 酬載狀態、噴灑遙測、電池詳情(私有 message ID 24150–24199 級) | `interfaces/mavlink/` |
| Protobuf schema | 機-雲遙測與指令(MQTT/gRPC) | `interfaces/proto/` |
| 酬載描述檔 schema | QR-S/QR-L EEPROM 內容定義 | `interfaces/payload/` |
