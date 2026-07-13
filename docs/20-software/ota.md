# 20-8 OTA 設計規格

> rev 1 · 2026-07。全機隊軟體更新(OTA)的單一設計文件:飛控端與 Jetson 端的更新機制、簽章鏈驗簽點、相容性矩陣資料模型與灰度編排。安全面(簽章金鑰保管、防降級)以 [security.md §4](security.md) 為準,此處只定「怎麼更新」;[architecture.md §4](architecture.md) 與 [companion-computer.md §4](companion-computer.md) 的相容矩陣/OTA 句自本檔展開。

## 1. 更新標的與前置條件

| 標的 | 產出來源 | 傳遞路徑 |
|------|----------|----------|
| 飛控韌體(FC-H7 映像) | firmware release pipeline([firmware.md §4](firmware.md) 簽章釋出) | 雲 → drone-agent → 飛控(§2) |
| 參數包 | 與韌體版綁定釋出([firmware.md §7](firmware.md) 參數基線管理) | 隨韌體映像同批下發,燒錄後寫入並回讀核對 |
| Jetson 系統(rootfs) | onboard release pipeline(A/B 映像) | 雲 → drone-agent → 非活動分區(§3) |
| 酬載韌體 | 酬載模組 release | 經 Jetson 轉發(DroneCAN bootloader),Phase 2 起 |

共通前置條件(drone-agent 於安裝前檢查,任一不過即拒絕並回報):**地面且 disarmed、電量 > 40%**(沿用 companion-computer §4)、簽章驗證通過、相容性矩陣檢查通過(§5)。

傳輸面(蜂窩鏈路特性,對 [cloud-fleet.md §4/§5](cloud-fleet.md)):

- **斷點續傳**:映像分塊下載 + checksum,斷線自續,不重頭來——Jetson rootfs 映像 GB 級,行動網路一次拉完不現實
- **下載與安裝解耦**:映像可於任何時間背景下載暫存(僅佔頻寬不佔安全性),安裝才受前置條件約束;現場作業期間預設暫停下載,避免與影像回傳搶頻寬
- **差分更新**(Phase 2 評估):rootfs 層級 delta(如 OSTree/casync 級方案)壓縮流量;飛控映像小(MB 級),不做差分
- 每機月流量預算(遙測 < 1 GB,cloud-fleet §5)不含 OTA;OTA 流量按批次另計,私有部署走客戶內網鏡像倉(§7)

## 2. 飛控端更新

兩個候選機制,**依 FC-H7 rev A 的 flash 布局與 bootloader 實測細化定案**:

- **方案 A|雙 bank 交換**:STM32H7 flash 雙 bank——新映像寫入非活動 bank,bootloader 驗簽通過後切換啟動 bank;啟動失敗(watchdog 未餵)自動切回舊 bank。優點:斷電安全、回滾原生;代價:單映像上限 = 半 flash,bootloader 需支援 bank swap。
- **方案 B|外部升級器(Jetson 代燒)**:Jetson 收妥並驗簽映像後,經串列/USB DFU 對飛控燒錄;bootloader 僅做啟動前驗簽,燒錄中斷由 bootloader 停在可重燒狀態。優點:飛控端邏輯最簡;代價:燒錄期間飛控不可用、依賴 Jetson 在場。

兩案共通:**bootloader 一律驗簽,只啟動合法簽章映像**(security §4);燒錄後 drone-agent 回讀韌體版本與參數 hash([firmware.md §6.5](firmware.md))確認生效,並回報雲端終態。

## 3. Jetson 端更新(A/B 分區)

- 新 rootfs 映像由更新代理驗簽後寫入**非活動分區**,設定下次啟動指向新分區並重啟(僅地面時)
- **健康檢查回滾**:新分區啟動後由 drone-agent 跑健康檢查(關鍵服務起動、與飛控 DDS 連通、與雲連線)——全數通過才「提交」(commit)新分區;逾時或未過,bootloader 啟動計數耗盡自動回退舊分區,並回報回滾事件
- 唯讀根檔案系統(companion-computer §1)使分區內容即映像內容,無就地漂移;應用層設定與資料放獨立資料分割區,不隨 A/B 切換

## 4. 簽章鏈與驗簽點

簽章鏈本體(離線 HSM、雙人核可、防降級)見 [security.md §4](security.md),此處只列**驗簽點**:

| 驗簽點 | 驗什麼 | 失敗行為 |
|--------|--------|----------|
| 雲端發布入口 | 上架映像的簽章與 SBOM 齊備 | 拒絕上架 |
| drone-agent 收檔後 | 映像簽章 + checksum | 丟棄並回報,不進入安裝 |
| 飛控 bootloader | 啟動映像簽章 | 不啟動,停在 bootloader 等重燒 |
| Jetson 更新代理 | 寫入非活動分區前驗簽 | 不寫入,回報失敗 |

## 5. 相容性矩陣資料模型

[architecture.md §4](architecture.md)「韌體版 × 機載版 × GCS 版 × 酬載版,OTA 時強制檢查」的資料設計(落地於 fleet-svc,[cloud-fleet.md §2](cloud-fleet.md)):

- **artifact 登記表** `artifacts(component, version, image_hash, signature, min_hw_rev, channel, released_at)`——component ∈ {firmware, onboard, gcs, payload-*};每筆對應一個已簽章可下發的版本
- **相容規則表** `compat_rules(rule_id, firmware_range, onboard_range, gcs_range, payload_range, verdict, reason, source)`——range 為 SemVer 區間(如 `>=1.2 <2.0`,`*` = 不限);verdict ∈ {allow, deny};deny 優先於 allow,用於封鎖「合法簽章舊版拼出漏洞面」的組合(security §4)
- **機隊現況表** `device_versions(drone_id, component, version, updated_at)`——由 drone-agent 遙測回報維護
- **檢查語意**:目標組合(現況 + 欲更新項)必須**命中至少一條 allow 且不命中任何 deny**才可排程;規則由 release pipeline 隨版本發布時新增,人工增補 deny 需雙人核可
- **檢查時點**:雲端排程時(初判)、drone-agent 安裝前(以機上實際版本再驗——排程與安裝間版本可能已變)、GCS 連線時(版本不相容給告警,不阻斷監視)

## 6. 灰度編排

- **分批(ring)**:ring 0 = 內部測試機 → ring 1 = 試點機隊 ~10%(每客戶至少留一台不更新)→ ring 2 = 全量;各 ring 之間設最短觀察期(預設 72 h,涵蓋數個飛行日)
- **暫停條件**(自動,任一觸發即凍結後續批次):批次內安裝失敗率 > 5%、任何一台發生自動回滾、更新後新增 S1/S2 缺陷([02-verification-validation.md §7](../02-verification-validation.md))
- **回滾條件**:機上自動回滾(§2/§3 啟動失敗與健康檢查)之外,雲端可對已完成批次下發「回退前一簽章版本」指令;防降級邊界依 security §4(不得低於吊銷版本號)
- 每批次狀態(排程/下發/安裝中/成功/失敗/回滾)入 fleet-svc,OTA 管理面板(cloud-fleet §3)呈現
- **審計軌跡**:誰核可、哪個版本、下發哪些機、各機終態與時間戳全數落庫且不可改——既是維運需求,也是認證階段的變更管理證據(SOC2 控制清單記帳,security §7)與 CRA 安全更新義務的佐證

## 7. 分階段落地

| 階段 | 落地項 | 暫不做 |
|------|--------|--------|
| Phase 0 | 無 OTA(開發機 USB 燒錄 + `apply_params.py`) | — |
| Phase 1 | Jetson A/B 分區與健康檢查回滾;飛控端機制定案(rev A 實測)與手動觸發更新;`device_versions` 版本回報 | 簽章鏈仍用開發簽章;無灰度(逐台手動) |
| Phase 2 | 正式簽章鏈(security §8)、相容性矩陣強制檢查、灰度編排與 OTA 管理面板、酬載韌體 OTA | — |
| Phase 3 | 私有部署環境的 OTA(客戶機房內鏡像倉)、認證所需變更管理紀錄 | — |

## 7b. 機載代理實作現況(G23,onboard/drone_agent)

[onboard/drone_agent/drone_agent/ota.py](../../onboard/drone_agent/drone_agent/ota.py)
落地本文**機載代理側的程式可達部分**,標的為**軟體套件/設定 OTA**,以目錄
slot + `current` symlink **模擬** A/B 分區(§3),驗證代理側編排邏輯:

- **已實作並單元測試涵蓋**:斷點續傳下載(§1)、收檔後驗簽點(§4,SHA-256 + Ed25519
  公鑰驗簽,壞簽章/無公鑰一律 fail-closed 拒絕)、A/B slot 套用與原子切換、健康檢查
  失敗自動回滾(§3)、進度回報(at-least-once)、pause/resume/rollback 指令(§6 機載端)。
- 指令與進度走 **JSON**(主題 `fleet/{id}/cmd/ota` 與 `fleet/{id}/ota/progress`),
  刻意不動 proto 契約。公鑰來源 env `OTA_PUBLIC_KEY`(Ed25519 PEM);釋出私鑰存離線
  HSM(security §4)。
- **Phase 3(實體硬體代燒)尚未實作**,於程式對應位置以 `TODO` 標明:飛控雙 bank 交換 /
  Jetson 代燒(§2 方案 A/B 實體 flash)、rootfs 分區實體寫入 + bootloader 啟動計數回退
  (§3)。**Phase 1 TODO**:真實健康檢查(服務/DDS/雲連線,目前為佔位可注入)。
  **Phase 2**:正式簽章鏈防降級(拒裝低於吊銷版本號)、相容性矩陣強制檢查(§5)、
  灰度 ring 編排(§6)。詳見 [onboard/drone_agent/README.md](../../onboard/drone_agent/README.md)
  「OTA 機載代理」節的對照表。

## 8. 版本紀錄

| rev | 日期 | 變更 |
|-----|------|------|
| 1 | 2026-07 | 初版:飛控/Jetson 兩端機制、驗簽點、相容性矩陣資料模型、灰度編排、分期落地 |
