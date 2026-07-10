# hardware — 電子硬體設計

> 規劃依據:[docs/10-hardware/flight-controller.md](../docs/10-hardware/flight-controller.md)

```
hardware/
├── fc-h7/          # 飛控核心板(KiCad):rev-a / rev-b / rev-c 分目錄,每版打 git tag
├── carrier-pa1/    # PA-1 載板(含 PMU 整合)
├── carrier-pb1/    # PB-1 載板(接觸器、預充、降落傘觸發)
├── pmu/            # 電源管理板
├── stereo-cam/     # 雙目相機模組
└── docs/           # 原理圖 PDF、BOM(含替代料)、測試報告(每 rev 歸檔)
```

## 規則

- EDA:KiCad 8(開放格式);二進位大檔(製造檔壓縮包)走 Git LFS
- 每版 rev 的驗收:點亮 → PX4 bring-up → 感測全通 → 24h 燒機 → 環測/EMC 預掃報告歸檔
- 關鍵 IC 維護 NDAA/出口管制檢核表(`docs/` 內),美國市場前置
