# 20-7 QGC 客製評估與 Phase 1 GCS 決策建議

> rev 1 · 2026-07。本文件展開 [ground-station.md §1](ground-station.md) 的「QGC 客製」策略:盤點三級客製深度(stock+預設檔 / 官方 custom-build 模板 / 深 fork)各自能做什麼與維護成本、Apache 2.0 / GPLv3 雙授權的商用合規路徑、對 [ground-station.md §3](ground-station.md) Phase 1 功能列逐項判級,並給出 Phase 1 決策建議。QGC 版本與 custom-build 機制以撰寫時公開資訊為準,凡涉及具體版本行為均標「需查證最新版」;實作落地目錄結構對 [gcs/README.md](../../gcs/README.md)。

## 1. 背景與評估範圍

- 既定策略(ground-station.md §1):Phase 0–1 用 QGC 客製,Phase 2+ 自研 GCS。本文件回答的是「Phase 0–1 這段,客製要做多深」——這直接決定要不要養 Qt 工具鏈 CI、要不要背 upstream 跟版成本。
- 評估基準版本:QGC v4.4(Qt 5.15/qmake 世代)→ v5.x(Qt 6 + CMake 世代,官方文件已有 Stable V5.0 分支)。**需查證最新版**:實際採用前確認當時 stable 版號、Qt 版本要求與 custom-build 在 CMake 世代的支援完整度(2024 年 CMake 遷移期 custom build 支援曾有缺口,upstream issue #11436)。
- 不在範圍:Phase 2 自研 GCS 架構(見 ground-station.md §2)、遙測鏈路硬體。

## 2. 客製選項光譜

### 2.1 三級選項總表

| | A. stock QGC + 預設檔 | B. 官方 custom-build 模板 | C. 深 fork |
|---|---|---|---|
| 做法 | 不改碼。發佈官方安裝檔 + 隨附:參數預設檔(.params)、任務範本(.plan)、離線圖磚包、設定說明 | 用 upstream 內建 `custom-example/` 機制:複製為 `custom/` overlay,以 plugin 子類(CorePlugin/FirmwarePlugin)覆寫行為,不改 upstream 原始碼 | 直接改 upstream 原始碼(UI 結構、任務引擎、地圖引擎、通訊層) |
| 能做到 | 機型參數/失效保護預設、標準任務範本、離線地圖(圖磚快取/匯入)、自訂圖源 URL(見 §4.2) | A 全部 + branding(名稱/圖示/配色)、鎖定機型(隱藏無關韌體/機型選項)、簡化 UI(隱藏進階設定頁、鎖定設定預設值)、預載圖源與台灣圖資、內建自檢清單、預設單位/語言 | B 全部 + 改任務規劃引擎(農噴地塊/處方圖)、新 MAVLink 微服務、深度改版 UI 工作流 |
| 做不到 | 換 branding、藏設定、鎖機型;使用者可任意改壞設定 | 觸及 upstream 核心的功能(任務引擎新類型、地圖引擎重寫);overlay 介面雖相對穩定但無 API 相容性保證 | (沒有做不到,但等同接管一個 ~百萬行級 Qt 專案) |
| 建置/CI 負擔 | **零**。不 build,只 pin 官方版號 | 自建 Qt 6.x 工具鏈 CI(Linux/Windows/Android 三平台矩陣)、簽章與發佈流程 | 同 B,外加 upstream CI 差異維護 |
| 跟版(升版 rebase)負擔 | 零(換官方安裝檔 + 回歸測預設檔) | 低–中:overlay 檔案與 plugin 子類隨 upstream 介面變動調整;大版本跳遷(如 Qt5→Qt6)一次性較痛 | 高:每次升版全量 merge 衝突;越改越深越背離,最終常演變成凍版不跟 |
| 人力估(初次) | ~0.25 人月(整理預設檔+驗證) | 0.5–1 人月(overlay 搭建 + 三平台 CI + branding 素材) | ≥2–3 人月起,依改動範圍開放上限 |
| 人力估(持續) | ~0.05 FTE | 0.1–0.25 FTE(每次 upstream stable 升版 0.1–0.2 人月) | ≥0.5 FTE(升版 merge 0.5–1 人月/次,或凍版累積技債) |

### 2.2 官方 custom-build 機制現況(選項 B 依據)

- upstream 內建 `custom-example/` 目錄即官方支援的客製途徑:複製為 `custom/` 後建置系統自動納入;透過 **plugin 子類**覆寫 QGC 行為(branding 圖片、色盤、隱藏/覆寫應用設定、調整預設值),明確為「不改 upstream 碼」而設計,升版時只需對 overlay 介面做適配。
- **需查證最新版**:①`custom/` 在 CMake 建置下的啟用方式與範例完整度(qmake 世代靠 `updateqrc.py`,CMake 世代流程不同);②plugin 覆寫點(CorePlugin/FirmwarePlugin/設定隱藏清單)在當時 stable 的實際覆蓋範圍;③Android 客製簽章打包流程。
- 選型意涵:選項 B 的維護成本本質上是「養一條 Qt 桌面+Android CI」+「每次升版適配 overlay」,而**不是**維護 QGC 本體——這是 B 與 C 的成本分水嶺。

## 3. 授權分析(Apache 2.0 / GPLv3 雙授權)

### 3.1 邊界事實

| 面向 | Apache 2.0 路徑 | GPLv3 路徑 |
|------|-----------------|------------|
| 性質 | 寬鬆授權:允許閉源衍生、可上 iOS/Android 應用商店 | 強 copyleft:散布 QGC 衍生執行檔時,衍生部分原始碼須以 GPLv3 提供 |
| Qt 依賴 | 官方文件明示:以 Apache 2.0 建置需**商用 Qt 授權**(開源 Qt 為 (L)GPL,靜態連結/商店上架場景尤其牴觸)。**需查證**:桌面端動態連結 LGPLv3 Qt 能否滿足閉源需求,採用前取法律意見 | 可用**開源版 Qt**,零授權費 |
| 我方客製碼(overlay/fork) | 可閉源 | 屬 QGC 衍生作品,散布即須開源 |
| 適用場景 | 客製內容含商業機密、或需上應用商店 | 客製內容無機密(branding/鎖機型/圖資)時的零成本路徑 |

### 3.2 商用合規要點

1. **GPL 邊界止於 GCS 執行檔**:QGC 衍生品開源,**不感染**經 MAVLink 協議通訊的對端——飛控韌體、機上軟體(drone_agent 等)、雲端平台照常閉源。這與 ground-station.md §1 註記一致。
2. **散布才觸發**:GPLv3 義務在「散布」時發生。僅內部/自有機隊操作用不對外發佈,義務實質不觸發;但商用產品會隨機出貨 GCS → 應按「必然散布」規劃。
3. **機密隔離原則**:任何有商業差異化價值的邏輯(未來的處方圖演算法、排程引擎)**不放進 QGC 客製層**,放機上或雲端(閉源自由)——這同時是「深 fork 不划算」的授權面理由。
4. **閉源客製的條件**(若走 Apache 2.0):(a) 以 Apache 2.0 選項使用 QGC 原始碼;(b) 解決 Qt 授權(商用 Qt 或經法律確認的 LGPL 動態連結方案);(c) 仍須保留 Apache 2.0 要求的授權聲明與 NOTICE。
5. **商標**:QGroundControl 名稱/圖示非授權標的,rebrand 後不得以 QGC 官方名義發佈造成混淆;自有品牌名須自行查核。
6. **Phase 1 建議路徑**:客製層(branding/鎖機型/圖資)無機密 → **GPLv3 + 開源 Qt**,客製層照 GPLv3 隨附原始碼即可,零授權費、零法律不確定性;若後續需上應用商店或閉源,再切 Apache 2.0 + 商用 Qt(切換點=Phase 2 預算修訂)。

## 4. Phase 1 需求盤點(對 ground-station.md §3 逐項判級)

### 4.1 判級表(僅列 Phase 1 相關列)

| ground-station.md §3 功能(Phase 1 部分) | 最低滿足級 | 判斷依據 |
|---|---|---|
| 飛行儀表、地圖、影像、告警 | **A(stock)** | QGC 核心功能;影像走 RTSP/UDP 內建播放(對 [companion-computer](companion-computer.md) 影像管線) |
| 測繪航線規劃:多邊形分區、重疊率、GSD 計算 | **A(stock)** | QGC Survey pattern 內建多邊形航線、重疊率與 GSD 參數 |
| 測繪斷點續飛 | **A(stock)** | QGC 內建 Resume Mission 流程;與 mission_exec 斷點續飛(機上側)互補,需整合驗證。**需查證最新版**:當時 stable 的 resume 行為細節 |
| 離線地圖 | **A(stock)** | QGC 內建圖磚快取(線上瀏覽預抓)與離線圖磚包匯入 |
| 台灣圖資(TGOS/國土測繪中心 WMTS) | **A–B** | 見 §4.2:stock 有自訂圖源 URL 途徑但為 XYZ 型;正式產品要「開箱即有台灣圖資」須 B 級預載 |
| 電子圍欄 | **A(stock)** | QGC GeoFence(多邊形/圓形上傳)內建 |
| 禁航區法規圖層(台灣) | **B**(Phase 1–2) | 台灣禁航區圖層非 QGC 內建;custom-build 以圖層/圖源方式疊加。**需查證**:QGC Airspace 介面現況(歷史上以歐美服務為主) |
| 飛行紀錄回放 | **A(stock)** | QGC Telemetry log 回放內建 |
| 一鍵任務自檢清單(ground-station.md §4 UX) | **A–B** | QGC 有內建 preflight checklist(預設關閉,可開);「自檢不過不給飛」的強制邏輯與客製項目須 B 級覆寫 |
| branding、鎖定機型、簡化 UI(§1 既定客製目標) | **B** | 即 custom-build 模板的設計用途 |
| 中英雙語 | **A(stock)** | QGC 內建多語系(含繁中);字串品質驗收後不足處 B 級補翻譯檔 |

### 4.2 台灣圖資與離線地圖(唯一的圖資工程項)

- **stock 途徑**:QGC 支援自訂圖源(custom tile server URL,XYZ 樣式)+ 離線圖磚匯入。TGOS/國土測繪中心(NLSC)供應的是 **WMTS** 服務——多數 WMTS(含 NLSC EMAP)同時可用 XYZ 樣式 REST 路徑存取,可直接填入;不行則架一層 WMTS→XYZ 轉換代理或預製離線圖磚包。**需查證最新版**:當時 stable 的自訂圖源設定介面與快取上限;NLSC 圖磚服務之商用授權條款(政府圖資多為開放授權但商用需確認)。
- **B 級收尾**:custom-build 把台灣圖源(電子地圖/正射影像)設為內建預設選項並預載常用區圖磚,達成「開箱即用」;此為純 overlay 設定,不觸 upstream 地圖引擎。
- **結論**:台灣圖資**不構成**深 fork 理由。

### 4.3 盤點結論

Phase 1 功能列**無一項需要 C(深 fork)**:核心飛行/測繪/圍欄/回放全數 stock 已備,產品化訴求(branding、鎖機型、簡化 UI、台灣圖資預載、強制自檢)全數落在 B 級 overlay 範圍。需要觸 upstream 核心的需求(農噴地塊/處方圖、巡邏排程、多機同屏)全部是 Phase 2 列——而那正是既定策略切換到自研 GCS 的時點。

## 5. 建議與決策記錄

### 5.1 建議

1. **Phase 0:選項 A**(stock QGC + 參數/任務預設檔 + 台灣圖源設定說明)。開發機驗證期不值得養 CI;預設檔已能消掉九成操作風險。
2. **Phase 1:選項 B**(官方 custom-build 模板,GPLv3 + 開源 Qt)。EVT/交付試點需要 branding、鎖機型、簡化 UI 與圖資開箱即用;成本上限清楚(0.5–1 人月初建 + ~0.2 FTE 持續),且客製層開源無商業損失(§3.2)。啟動前先做 §2.2 三項「需查證最新版」確認。
3. **不做選項 C(深 fork)**。理由:(a) Phase 1 功能無一項需要(§4.3);(b) 維護成本(≥0.5 FTE + 升版 merge)投在一個 Phase 2 就會被自研 GCS 取代的載體上,是純沉沒成本;(c) GPLv3 下深客製須全數開源,商業差異化邏輯放不進去,做深了也守不住。
4. **Phase 2 決策點**:自研 GCS(ground-station.md §2)立項評審時,以「B 級 overlay 撐不住的第一個付費需求」(預期為農噴地塊管理或多機同屏)為觸發;屆時若自研延期,備援不是深 fork QGC,而是**延用 B + 需求降級**。
5. 落地時同步修正 [gcs/README.md](../../gcs/README.md) 的目錄對應(`qgc/` fork submodule → 依 B 級做法應為 upstream submodule + `custom/` overlay,無自有 fork 碼)。

### 5.2 決策記錄(格式對齊 [phase0/README.md §8](../50-project/phase0/README.md))

| 日期 | 決議 | 理由 | 記錄人 |
|------|------|------|--------|
| 2026-07 | Phase 0 GCS 採 stock QGC + 預設檔(選項 A);Phase 1 採官方 custom-build 模板(選項 B,GPLv3 + 開源 Qt);不做深 fork,深客製需求一律導向 Phase 2 自研 GCS 決策點 | Phase 1 功能盤點無一項需深 fork(§4.3);B 級成本上限明確且升版負擔低(§2);GPLv3 路徑零授權費、客製層無機密可開源(§3.2);深 fork 為 Phase 2 即棄資產 | S16 評估(本文件) |

## 6. 版本紀錄

| rev | 日期 | 內容 |
|-----|------|------|
| 1 | 2026-07 | 初版:客製光譜、授權分析、Phase 1 逐項判級、決策建議(S16) |
