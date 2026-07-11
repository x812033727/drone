# 10-7 EMC / RF 設計

> rev 1 · 2026-07。整併散見各文件的 EMC/RF 既有結論為單一設計文件:天線佈局原則([communication §5](communication.md)、airframe rev 2 佈局決議)、接地與屏蔽([flight-controller §5](flight-controller.md)、[materials §1](../30-structure/materials.md))、EMC 預掃計畫([flight-controller §7](flight-controller.md)、[roadmap](../50-project/roadmap.md))與量測項目([certification-roadmap §4](../40-regulatory/certification-roadmap.md) 未勾項)。**本檔只整併+結構化,不新增設計決策**;新出現的數值均為設計基線,標「rev A 量測後定案」。版本紀錄見 §6。

## 1. 天線佈局原則

既有原則出處:GNSS 天線遠離圖傳、蜂窩([communication §5](communication.md));GNSS 用抑徑板、磁力計外置於 GNSS 模組遠離動力線([sensors-and-payload §1](sensors-and-payload.md));數傳/5G 天線對角隔離(airframe rev 2 佈局決議,見 [phase0/README §8](../50-project/phase0/README.md));RID 天線遠離 GNSS([communication §4.1](communication.md) 待辦)。

| 天線 | 位置原則 | 與其他天線最小隔離(設計基線,rev A 量測後定案) | 備註 |
|------|----------|------------------------------------------------|------|
| GNSS RTK(+抑徑板) | 機頂最高點、天空視野無遮擋;遠離數傳/5G/RID 發射天線與動力線 | 對任一發射天線 ≥ 150 mm | RM3100 磁力計同模組,連帶遠離大電流路徑;PB-1 雙天線沿縱軸最大化基線 |
| 2.4 GHz 數傳 | 機腹/機臂端向下,與 5G 天線**對角佈置**(airframe rev 2 站位) | 對 5G ≥ 100 mm;對 GNSS ≥ 150 mm | 雙天線分集時兩支正交極化 |
| 5G(RM520N-GL) | 與數傳對角;避開碳纖維板遮擋(需開窗或外置) | 對數傳 ≥ 100 mm;對 GNSS ≥ 150 mm | MIMO 多天線間自身 ≥ λ/2(~60 mm @2.6 GHz 級) |
| Remote ID(BT5 LR) | 隨模組佔位,遠離 GNSS 天線 | 對 GNSS ≥ 100 mm | 功率 mW 級,約束主要是保護 GNSS 收訊 |
| RC(遙控) | Phase 0–1 與數傳同一整合模組([communication §2](communication.md)),不獨立佈天線 | 同數傳列 | 若 Phase 2 拆分,回本表補列 |

- 共同原則:**發射天線彼此拉開、收訊敏感者(GNSS)離所有發射者最遠**;天線佈局在結構設計初期就定位(communication §5),站位變更需回寫 airframe 佈局表
- 碳纖維板導電、對天線是遮擋與去諧因素([materials §1](../30-structure/materials.md)):所有天線外置或置於非金屬/非碳件開窗區

## 2. 接地與屏蔽原則

- 核心板↔載板連接器:GND pin 於高速/類比訊號兩側交錯屏蔽([flight-controller §5](flight-controller.md)),乙太網 MDI 差分對帶屏蔽
- 感測 3.3V 走低噪聲 LDO 獨立軌(flight-controller §4.1),類比/RF 前端與數位開關電源分區
- 動力大電流路徑(電池→PMU→ESC 母線)與訊號線束分開走線;ESC 遙測走 DroneCAN 差分(抗噪,[system-architecture §1](system-architecture.md))
- 碳纖維機身導電:可作局部屏蔽參考面,但**不得作為回流路徑**;接地單點匯接於 PMU,避免地迴路
- 全板 conformal coating(flight-controller §2)兼顧防潮與耐壓;PB-1 接觸器/預充電路的突波源就地抑制(system-architecture §2)

## 3. EMC 預掃計畫(時點引 [flight-controller §7](flight-controller.md))

| 時點 | 內容 | 出處 |
|------|------|------|
| FC-H7 rev A(Phase 1 M1–M3) | **提早進 EMC 預掃**(風險緩解,非正式節點):bring-up 後帶板進預掃實驗室摸底,發現輻射熱點供 rev B layout 修正 | [risk-register R-01](../50-project/risk-register.md)(原 roadmap §4) |
| FC-H7 rev B(M4–M6) | 正式 EMC 預掃節點(flight-controller §7 rev B 列;certification-roadmap §4「預掃於 rev B」) | flight-controller §7 |
| FC-H7 rev C / DVT(M7–M9) | rev C 通過環測與 EMC 預掃 = Phase 1 退出條件之一 | [roadmap §2](../50-project/roadmap.md) |
| Phase 3 | 整機正式認證測試(FCC ID / CE RED / NCC),費用與時程見 certification-roadmap §5 | certification-roadmap |

## 4. 量測項目與通過準則(引 [certification-roadmap §4](../40-regulatory/certification-roadmap.md) 未勾項)

| 項目 | 標準 | 預掃通過準則(設計基線,rev A 量測後定案) |
|------|------|--------------------------------------------|
| 輻射發射(RE) | EN 55032 Class B / FCC Part 15B | 限值裕度 ≥ 6 dB(裕度即 certification-roadmap「EMC 設計裕度」項的量化) |
| 傳導發射(CE) | EN 55032 | 限值裕度 ≥ 6 dB |
| 抗擾(RS/EFT/ESD) | EN 55035 | 功能等級 A(飛行功能不受擾);ESD 接觸 ±4 kV / 空氣 ±8 kV 級 |
| 射頻(2.4 GHz 數傳) | EN 300 328 / FCC 15.247 / NCC LP0002 | 佔用頻寬/雜散/EIRP 合格(模組層由供應商預認證覆蓋,communication §5) |
| 帶內共存 | 自訂:GNSS C/N0 於全發射器滿載時劣化 ≤ 3 dB(rev A 量測後定案) | 驗證 §1 隔離距離是否足夠的實測判準 |

- 通過準則凍結時點:rev A 預掃後定案並回寫本表;Phase 1 起量測報告依 [02-V&V §8](../02-verification-validation.md) 歸檔

## 5. Phase 0 開發機簡化注意

- 開發機(X500 V2 + Pixhawk 6X)全用已認證現成模組,**不做 EMC 測試**;但 §1 佈局原則照抄:GNSS 桅杆遠離數傳/4G dongle、dongle 不貼 GNSS 走線
- 開發機干擾排查靠現象面:RTK 收斂變慢/磁羅盤干擾告警即先動天線位置(phase0 W4 校磁與 [build-and-first-flight.md](../50-project/phase0/build-and-first-flight.md) 檢查表)
- Phase 0 的天線相對位置經驗(哪些擺法讓 C/N0 掉)記入異常追蹤單,作為 PA-1 佈局輸入

## 6. 版本紀錄

| rev | 日期 | 變更摘要 |
|-----|------|----------|
| 1 | 2026-07-12 | 初版:整併 communication/flight-controller/materials/certification-roadmap/airframe 佈局決議之 EMC/RF 散見內容;新增數值均標「rev A 量測後定案」 |
