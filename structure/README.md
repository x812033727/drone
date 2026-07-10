# structure — 機體結構設計

> 規劃依據:[docs/30-structure/](../docs/30-structure/airframe-design.md)

```
structure/
├── pa1/            # PA-1 機體:CAD(原生檔 + STEP)、圖紙、重量預算表
├── pb1/            # PB-1 機體
├── payload-if/     # QR-S / QR-L 酬載介面(對外發布的機械規格也從這裡出)
└── analysis/       # FEA 報告、模態/振動測試數據
```

## 規則

- CAD 原生檔 + 中性檔(STEP)都入庫;大檔走 Git LFS
- **重量預算表週更**(整機重量是續航的生死線,規格留 10% 餘裕)
- 每個結構件標注:材料、製程(原型 CNC / 量產開模)、安全係數、供應商
