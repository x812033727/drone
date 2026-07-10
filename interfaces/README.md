# interfaces — 介面契約(單一事實來源)

機上 / 地面站 / 雲端三方共用的協議定義,**契約先行、獨立版本化**,三方 codegen 取用。

```
interfaces/
├── mavlink/        # 自訂 MAVLink dialect XML(酬載狀態、噴灑遙測、電池詳情)
├── proto/          # Protobuf schema(機-雲遙測與指令:MQTT/gRPC 用)
└── payload/        # 酬載描述檔 schema(QR-S/QR-L 介面的 EEPROM 內容定義)
```

## 規則

1. 任何跨端資料結構改動先改這裡,PR 需標註影響方(firmware / onboard / gcs / cloud)
2. Schema 版本語意化(SemVer);破壞性變更需提供相容期(機隊 OTA 是分批的,
   雲端必須同時支援 N 與 N-1 版)
3. MAVLink dialect 基於 upstream common.xml 擴充,message ID 使用私有區段(24150–24199 級)
