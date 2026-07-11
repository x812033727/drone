# 50-6 供應鏈與製造策略

> rev 1 · 2026-07。整併散落各文件的 Make/Buy 既定策略為單一總表,並建立料件風險分級、NDAA/出口管制檢核制度、供應商管理與各 Phase 製造策略。本文是「策略與制度」層;逐料件即時狀態(單價/交期/詢價)的單一事實來源仍在 [bom.md](../10-hardware/bom.md),RFQ 執行細節在 [phase0/procurement.md](phase0/procurement.md),不重複維護。

## 1. Make/Buy 決策總表

各列策略皆為既定結論(出處欄),本表補上決策準則與轉換條件,供每 Phase 檢查點覆核:

| 項目 | 決策 | 出處 | 決策準則 | 轉換條件 |
|------|------|------|----------|----------|
| 飛控 FC-H7 硬體板 | **Make**(自研,PCBA 委外) | [flight-controller §1](../10-hardware/flight-controller.md) | 核心差異化(NDAA 履歷/認證增改/整合降線束)、量產成本主導權 | 反向:rev C 前若三版皆延期且 Pixhawk 6X 商務條件可談到量產價 → 回退外購(Phase 1 檢查點覆核) |
| 飛控韌體核心 | **Buy**(用 PX4,只做板級與上層) | [flight-controller §1](../10-hardware/flight-controller.md) | 無商業差異化、驗證成本極高(百萬飛行小時級) | 原則上不轉 Make;認證若強制自主韌體佐證再議 |
| Jetson 載板/PMU | **Make**(自研,PCBA 委外) | [flight-controller §2](../10-hardware/flight-controller.md)、[bom §1](../10-hardware/bom.md) | 平台整合是差異化(減線束/冗餘電源拓撲) | 反向:無(與 FC-H7 同節奏,綁定自研) |
| 數傳/遙控器 | **Buy**(現成套裝)→ Phase 2 **ODM 客製** | [team §3](team.md)、[bom §4 路線 1](../10-hardware/bom.md) | 射頻開發非核心能力,但量產成本敏感(−40%/台) | 轉 ODM:量 >100 台/年且 ODM NRE ~1.5M 可攤提(Phase 2 啟動時決) |
| 電池 pack | **Buy**(台灣 pack 廠 ODM,BMS 協同設計,不自製電芯) | [team §3](team.md)、[propulsion §2/§10](../10-hardware/propulsion.md)、[00-overview §5](../00-overview.md) | UN38.3 認證與製程品質靠 pack 廠既有能力;規格主導權留自己(§7 規格書) | 原則上不轉 Make(認證風險);電芯第二來源另見 §2 |
| 雲台 | **Buy**(Phase 1 外購整合)→ Phase 2 評估**自研** | [sensors-and-payload §3](../10-hardware/sensors-and-payload.md)、[bom §4 路線 2](../10-hardware/bom.md)、[team §3](team.md) | 首發時程優先;量產後外購 15 萬/顆吃掉毛利 | 轉 Make:雙光構型量 >50 台/年且開發 ~3M 過 P2 預算修訂 |
| 線束 | **Buy**(治具化外包) | [team §3](team.md)、[materials §2](../30-structure/materials.md) | 一致性是商用可靠度大戶,治具化外包優於手工 | 原型期(<10 台)手工自製;EVT 起轉治具化外包 |
| 結構件 | **Make 設計 + Buy 製造**:CNC/列印(Phase 1)→ 開模(Phase 3) | [materials §2](../30-structure/materials.md)、[bom §4 路線 3](../10-hardware/bom.md) | 設計凍結前保留迭代自由度,免模具沉沒成本 | 轉開模:量 >200 台/年、DVT 通過後下模(詳 §5) |

## 2. 關鍵料件風險分級與雙源

**A 級(斷供即停線)**——任一缺料直接卡整機出貨:

| 料件 | 風險 | 雙源策略 | 監測方式 |
|------|------|----------|----------|
| STM32H753(FMU 主控) | EOL 風險低(ST 10 年供貨承諾),但曾有全業界缺貨前例 | H743 腳位相容替代([flight-controller §3](../10-hardware/flight-controller.md));安全庫存 6 個月 | 訂閱 ST 產品變更/EOL 通知(PCN);代理商季報 |
| IMU(ICM-45686 + BMI088 異構組合) | 兩者皆單一來源件、消費級生命週期短 | 核心板雙 footprint、device tree 切換、異廠互為備援([flight-controller §3](../10-hardware/flight-controller.md));安全庫存 6 個月 | TDK/Bosch EOL 通知訂閱;每 rev 覆核在產狀態 |
| Jetson Orin NX 模組 | 單一供應商(NVIDIA)、地緣需求波動大、曾有長交期紀錄 | 無真雙源;緩解 = NVIDIA 工業級供貨承諾(產品生命週期頁)+ Orin Nano 降級構型(bom §4 路線 4)+ 安全庫存 6 個月 | NVIDIA 生命週期公告;經銷商季度供需回報 |
| 電芯(Molicel P45B/P50B) | 單一產地(台灣高雄)、電動載具需求排擠、批次分配制 | 第二來源電芯驗證 + UN38.3 重測 ~0.5M(bom §4 路線 5,Phase 2–3 定案);pack 廠合約鎖批量;安全庫存 6 個月(電芯有存放老化,滾動輪用) | pack 廠季度供需會議;Molicel 分配狀態追蹤 |

**B 級(斷供可繞行,但傷時程/成本)**:

| 料件 | 風險 | 雙源策略 | 監測方式 |
|------|------|----------|----------|
| 全局快門 sensor(OV9282/AR0234) | 供貨波動大([sensors-and-payload §5](../10-hardware/sensors-and-payload.md)) | 雙目模組預留 footprint 相容(既定);庫存 3 個月 | 模組廠/代理商季報 |
| 5G 模組 RM520N-GL | 陸系供應商的地緣/合規風險(NDAA 敘事需逐市場檢核,見 §3) | 同廠 RM500Q-GL 替代(bom §1);中長期評估非陸系模組供美國市場構型 | 出貨市場變更時觸發檢核(§3);FCC/NDAA 政策追蹤 |
| 槳(T-Motor 摺疊碳槳) | 單一供應商、規格件 | MEJZLIK 備援([propulsion §10](../10-hardware/propulsion.md));量產評估自開模;庫存 3 個月(耗損件) | 代理商交期季報 |

分級掛鉤:A 級料異動(EOL/交期 >2 倍/漲價 >20%)須進 roadmap 風險登錄並於週會提報;B 級記錄於 bom.md 對應列即可。

## 3. NDAA/出口管制合規流程

美國市場前置(定位見 [00-overview §1](../00-overview.md)),用**檢核表制度**而非個案判斷:

- **檢核時點**(三觸發):(1) 新料選型時——進 BOM 前必填 NDAA 欄;(2) 每硬體 rev 凍結時——全表覆核一次(對 [flight-controller §3](../10-hardware/flight-controller.md) NDAA 欄,檢核表本體在 `hardware/docs/` 維護);(3) 出貨市場變更時——同一構型換市場即重跑
- **出口管制注意**:FLIR Boson 級熱像屬美國 EAR 管制品——出貨歐盟/其他市場需檢核許可;其備援 Hikmicro 與 NDAA 衝突、美國市場不可用 → **雙供應鏈依市場切換**([sensors-and-payload §5](../10-hardware/sensors-and-payload.md)),雲台構型 BOM 必須分市場版本管理
- **供應鏈履歷文件化**:A 級料與通訊/影像類料件保存「原廠→代理→我方」採購鏈證明(發票/原廠授權書),電芯附產地證明——這是對美銷售與政府標案的加分項([materials §4](../30-structure/materials.md)),認證階段(Phase 3)會被要求提交
- 已知待辦:陸系件(5G 模組、部分感測)的美國市場構型替代方案,Phase 2 結束前定案

## 4. 供應商管理

- **分級**:A 關鍵(A 級料供應商、pack 廠、PCBA 廠、碳件 CNC 主力)/ B 一般(現貨通路、雜項)。A 級供應商要求:出廠測試報告、變更通知(PCN)義務、第二廠區或備援方案說明
- **pack 廠交付物(A 級專項)**:UN38.3 **T.1–T.8 全項測試報告 + IATA Test Summary** 為 A 級供應商必要交付物,報告涵蓋之電芯批次/組態須與量產一致(條款細目與送測時點見 [propulsion §7.1](../10-hardware/propulsion.md) 運輸合規列);**PCN(變更通知)觸發重測評估**——電芯/BMS/pack 結構/材料任一變更,pack 廠須於出貨前提交變更影響評估並判定 UN38.3 報告有效性,必要時重測(UN 手冊 Part III §38.3 口徑;2026-07 查核,送件前以最新版覆核)
- **新供應商導入**:樣品驗證 → 小批(10–50 件)裝機驗證 → 書面稽核(量產前 A 級加現場稽核);每步驟證據歸檔
- **詢價紀錄歸檔**:全部 RFQ 走 [procurement §4](phase0/procurement.md) 固定欄位模板(數量分級 2/10/50/200),回價原件與比價結論歸檔 git;bom.md 對應列於回價後 1 週內更新(bom 檔頭滾動更新機制)
- **稽核節奏**:A 級供應商年度稽核(量產前為書面 + 交期/品質紀錄回顧);pack 廠因涉 UN38.3 與熱失控交付要求,Phase 2 起加現場稽核

## 5. 製造策略(Phase 1 → 3)

- **Phase 1(<10 台):全部免開模**——碳板 CNC、碳管現貨、塑膠件 CNC POM/MJF 列印([materials §2](../30-structure/materials.md)),把迭代自由度留到設計凍結;PCBA 小批委外
- **Phase 2(設計凍結後):模具投資決策樹**——結構凍結(Phase 2 結束)且 DVT 通過後,逐件跑:年量預測 × 單件降本 ≥ 模具攤提(18 個月內)才下模。基準數字:射出模單套 30–80 萬(materials §2)、模具首批預算 2.5M(budget Phase 2)、觸發量 >200 台/年、結構降本 −50%(bom §4 路線 3)。未過門檻的件維持 CNC——**提前投模是新創常見燒錢事故**
- **Phase 3:代工 vs 自建產線決策**——不預下結論,決策時點 = Phase 3 啟動(認證送件同期),負責人 = 系統負責人 + PM/供應鏈,產品委員會核定:

| 決策因素 | 傾向代工(EMS/整機組裝廠) | 傾向自建產線 |
|----------|--------------------------|--------------|
| 量 | <500 台/年,攤不平產線固定成本 | 量大且穩定成長 |
| 品質控制 | 標準製程(PCBA/組裝)代工廠更成熟 | 校飛/調參等飛行器特有工序需自控 |
| 資本 | 資金優先投研發與通路 | 已有量產營運資金(budget Phase 3 另計項) |
| 機密性 | 一般組裝可外放 | 飛控燒錄/金鑰注入/校準必須自持 |

現實混合解(供屆時評估基準):PCBA 與次組裝外包、**總裝/校準/產測自持**——產測系統與治具已列 Phase 3 預算(budget §1)。

## 6. 庫存與長交期策略

- **里程碑化採購**:rev B 驗證通過才下 rev C 物料([budget §3](budget.md) 燒錢原則 3);預備金動用需技術負責人核准(procurement §2 同規則)
- **長交期件清單**(下單排程永遠先排這批,對 [procurement §3](phase0/procurement.md) 優先序邏輯):電池 pack 樣品 8–12 週(BAT-B ~12 週)、RTK 模組與數傳套裝 4–6 週、Jetson 模組 4–8 週、動力套件 4–8 週(交期欄同源 bom §1/§2)
- **安全庫存原則**:A 級料 6 個月、B 級料 3 個月(量產起算;原型期以「當前 rev 用量 + 一輪重製」代替);電芯類有存放老化,以滾動先進先出管理
- 停產風險件(EOL 通知後):立即評估 last-time-buy 量 = 剩餘產品壽命需求 × 1.2,與替代料驗證並行

## 7. 台灣供應鏈地圖

本地聚落是本案 NDAA 敘事的天然資產([materials §4](../30-structure/materials.md)),各類概況(不點名個別公司,RFQ 收件人清單在 procurement §4 持續維護):

| 類別 | 本地概況 | 備註 |
|------|----------|------|
| 碳纖維板/管 | 自行車/複材產業鏈現貨規格多(中部聚落) | Phase 1 用現貨捲管 + 板材 CNC |
| CNC 加工 | 台中精密加工聚落,打樣 1–2 週 | 至少兩家併行比價(bom 結構列既定) |
| 電池 pack | 多家具 UN38.3 經驗的 pack 廠可 ODM 含 BMS 協同 | 電芯 Molicel 本身即台灣產 |
| 線束 | 汽機車/工控線束廠成熟,可治具化小批 | EVT 起導入 |
| PCBA | 全球最密集的 PCB/組裝供應鏈,小批打樣至量產皆有 | FC-H7/載板/PMU 委外對象 |
| 射出/模具 | 本地開模成本與溝通優勢 | Phase 3 才用(§5) |
| 整機組裝/EMS | 具系統組裝能力的 EMS 多,但無人機總裝經驗者少 | §5 Phase 3 決策的實地訪廠標的 |

誠實備註:雲台、熱像、全局快門 sensor、5G 模組等仍依賴進口(美/歐/陸系),台灣供應鏈覆蓋的是結構/電池/PCBA/組裝這一層——NDAA 敘事寫實陳述,不誇大為「全本土」。

## 8. 版本紀錄

| rev | 日期 | 變更 |
|-----|------|------|
| 1 | 2026-07 | 初版:Make/Buy 總表(整併 flight-controller/bom/propulsion/sensors-and-payload/materials/team 既定策略)、料件風險分級與雙源、NDAA/出口管制檢核制度、供應商管理、Phase 1–3 製造策略、庫存與長交期、台灣供應鏈地圖 |
