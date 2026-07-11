# 20-6 資安架構

> rev 1 · 2026-07。本文件展開 [architecture.md §5](architecture.md) 的資安基線,是全案資安的單一事實來源:威脅模型、PKI、鏈路/OTA/資料安全、供應鏈與合規對應。安全邊界(四層職責切分)沿用 [architecture.md §2](architecture.md);操作面安全見 [03-safety-analysis.md](../03-safety-analysis.md)。合規細節以 [certification-roadmap.md](../40-regulatory/certification-roadmap.md) 為準。

## 1. 威脅模型

按 [architecture.md §2](architecture.md) 的四層邊界(PX4 / Jetson / GCS / 雲)盤點主要威脅。原則同飛安:**任一外層被攻破,內層仍能安全飛行**——雲端全失守時,飛機最壞情況等同斷線(續飛/懸停/返航),不存在「雲端下指令直接控制馬達」的路徑。

| 威脅 | 攻擊面 | 影響 | 對策(索引) |
|------|--------|------|--------------|
| 鏈路劫持與重放(MAVLink) | GCS ↔ PX4 數傳鏈路;偽造 GCS 注入指令、重放歷史封包 | 奪取控制權、誘發返航/降落 | MAVLink 2 signing + GCS 配對(§3);PX4 端指令仍受 GeoFence/失效保護約束 |
| GPS spoofing / jamming | GNSS 天線(非網路面) | 位置估算被誘導或發散 | 資安面無解,由飛安面承接:EKF 新息檢核 + GNSS 降級鏈([03 §3](../03-safety-analysis.md)) |
| 雲端入侵與橫向移動 | 雲平台 API、裝置閘道、內部服務 | 機隊資料外洩、偽造派遣任務 | mTLS 裝置身份(§2)、K8s 網段隔離與審計日誌(§5);任務僅為建議,執行仍受機上驗證 |
| 供應鏈植入(韌體/依賴) | PX4 fork 依賴、pip/apt/容器映像、CI | 惡意碼隨 OTA 散布全機隊 | 簽章鏈(§4)、SBOM + 依賴掃描 + protected branch(§6) |
| 裝置失竊(憑證與資料萃取) | 整機/Jetson/儲存被物理取得 | 憑證冒用入雲、機上影像日誌外洩 | 憑證吊銷(§2)、靜態加密 + 唯讀根檔案系統(§5) |
| 內部人員 | 開發者權限、雲端運維權限、遠端診斷通道 | 後門植入、越權存取客戶資料 | 簽 commit + 雙人審查(§6)、遠端診斷雙人授權(§2)、審計日誌(§5) |

## 2. 裝置身份與 PKI

- **每機一憑證**:出廠燒錄裝置憑證與私鑰;Phase 1 落在 FC-H7/Jetson 的 flash 加密區,量產(Phase 2+)評估 TPM/SE 專用安全元件。私鑰不出裝置。
- **機-雲 mTLS**:drone-agent 對裝置閘道(EMQX/NATS,見 [cloud-fleet.md §2](cloud-fleet.md))雙向驗證;雲端以憑證指紋綁定機身序號,防裝置冒名。
- **輪換與吊銷**:憑證有效期一年,經 OTA 通道自動輪換(舊憑證仍有效期間內完成換發);失竊/退役機列入 CRL,閘道即時拒絕。憑證輪換為 [cloud-fleet.md §4](cloud-fleet.md) 資安原則的落地項。
- **WireGuard 隧道**:遠端診斷(反向 SSH)一律走 WireGuard,且需雲端雙人授權——沿用 [companion-computer.md §4](companion-computer.md) 既有規定;隧道金鑰與裝置憑證同生命週期管理。

## 3. 鏈路安全

- **MAVLink 2 message signing**(數傳鏈路,GCS ↔ PX4):簽章金鑰於 **GCS 配對流程**配發——地面經 USB/近距離安全通道注入共享金鑰,每機-每 GCS 一把;輪換隨韌體大版本或金鑰疑洩時執行。未簽章的控制指令一律拒絕(遙測廣播不在此限)。
- **數傳廠商層加密的信任邊界**:數傳模組自帶 FHSS + AES-256([communication.md](../10-hardware/communication.md)),但金鑰管理在廠商黑盒內——**視為縱深防禦的一層,不作為信任根**;信任根是 MAVLink signing 與 mTLS。
- **蜂窩鏈路**:SIM 與裝置綁定(IMEI 綁定,異動告警)、使用私有 APN 隔離公網;其上仍疊 mTLS + WireGuard,不信任電信網路本身。

## 4. OTA 安全

- **簽章鏈**:釋出簽章私鑰存離線 HSM,僅 release pipeline 於雙人核可後取用;飛控映像與 Jetson OTA 映像分別驗簽——飛控端由 bootloader 驗簽(GCS/OTA 只接受簽章版本,沿用 [firmware.md §4](firmware.md)),Jetson 端由 A/B 更新代理驗簽後才寫入非活動分區。
- **回滾**:飛控與 Jetson 皆 A/B 分區,啟動失敗自動回滾([companion-computer.md §4](companion-computer.md));防降級攻擊——回滾只回前一已簽章版本,拒絕安裝低於吊銷版本號的映像。
- **相容矩陣強制檢查**:韌體版 × 機載版 × GCS 版 × 酬載韌體版,OTA 時強制檢查(見 [architecture.md §4](architecture.md),此處不重複)——這同時是安全控制:阻止攻擊者以「合法簽章的舊版組合」拼出已知漏洞面。

## 5. 資料安全

- **靜態加密**:機上 NVMe 的影像/ULog 分割區加密(金鑰由裝置憑證體系派生),Jetson 唯讀根檔案系統減少竄改面;雲端物件儲存與資料庫開啟儲存層加密。
- **客戶資料主權**:私有部署(Helm chart,政府/電力客戶自建機房)是產品賣點([cloud-fleet.md §1/§3](cloud-fleet.md))——客戶資料可完全不出其機房,此為資安架構的商業落點。
- **保留與刪除**:遙測/日誌預設保留 2 年(維保與事故調查需求),影像依合約(預設 90 天);客戶終止服務時提供匯出 + 不可逆刪除證明。機上 NVMe 循環覆寫即為機上保留政策。
- **個資面**:巡邏/測繪影像可能含人臉/車牌,屬 GDPR 與台灣個資法範疇——分享連結帶浮水印與權限控制([cloud-fleet.md §3](cloud-fleet.md)),Phase 2 起提供偵測框模糊化選項,合約明確資料控制者為客戶。

## 6. 開發與供應鏈安全

- **SBOM**:release pipeline 對 firmware/onboard/cloud 三端自動產出 SBOM(SPDX/CycloneDX),隨版本歸檔——歐盟 CRA 與美國政府採購的前置([certification-roadmap.md §3](../40-regulatory/certification-roadmap.md));硬體側 NDAA 檢核表見 [flight-controller.md §5](../10-hardware/flight-controller.md)。
- **依賴掃描**:CI 內含已知漏洞掃描(pip/apt/容器映像/PX4 依賴),高危漏洞阻擋合併;基底映像每月重建。
- **原始碼防護**:簽 commit(簽名驗證)、protected branch + 必要審查、release pipeline 憑證與簽章金鑰隔離(開發者拿不到釋出私鑰)。
- **PSIRT 漏洞通報**:對外信箱 `security@<公司網域>`;SLA:48 小時內回覆確認、90 天內修補或公告緩解、修補隨 OTA 分批推送並發布安全通告。此流程即 CRA 漏洞處理義務的實作。

## 7. 合規對應表

| 法規/框架 | 義務 | 本文件對應 |
|-----------|------|-----------|
| 歐盟 CRA | SBOM、漏洞通報流程、安全更新義務 | §6(SBOM/PSIRT)+ §4(OTA 更新能力) |
| 美國 NDAA(政府採購) | 供應鏈履歷、禁用清單零件排除 | §6 + [flight-controller.md §5](../10-hardware/flight-controller.md) 檢核表 |
| SOC2(雲平台) | 控制清單從第一天記帳([cloud-fleet.md §4](cloud-fleet.md)) | §2(裝置憑證輪換)+ §5(審計日誌、保留政策) |
| GDPR / 台灣個資法 | 影像個資的控制者責任與刪除權 | §5(個資面、刪除政策) |

## 8. 分階段落地

> 對齊 [roadmap.md](../50-project/roadmap.md) 階段;**Phase 0 的豁免是明列的已知狀態,不是疏漏**——開發內網、無真實客戶資料、風險可接受。

| 階段 | 落地項 | 已知豁免 |
|------|--------|----------|
| Phase 0(開發 POC) | 開發內網隔離;基本 repo 防護(protected branch) | anonymous MQTT、無 TLS(Phase 0 開發內網部署,見 cloud 部署註記);無 MAVLink signing;無憑證體系 |
| Phase 1(平台開發) | mTLS + 裝置憑證(出廠燒錄)、MAVLink 2 signing + GCS 配對、WireGuard 遠端診斷、SIM 綁定 | SBOM 僅記帳未成 pipeline;無正式 PSIRT |
| Phase 2(產品化試點) | OTA 簽章鏈(離線簽章金鑰 + 雙端驗簽 + 防降級)、SBOM 自動產出、依賴掃描阻擋、PSIRT 上線、靜態加密全面啟用、TPM/SE 導入評估 | SOC2 稽核未執行(控制清單持續記帳) |
| Phase 3(認證量產) | 認證審計:CRA 合規聲明、SOC2 稽核、滲透測試(機-雲全鏈路)、私有部署安全基線文件化 | — |

## 9. 版本紀錄

| rev | 日期 | 變更 |
|-----|------|------|
| 1 | 2026-07 | 初版:自 architecture.md §5 資安基線展開(威脅模型/PKI/鏈路/OTA/資料/供應鏈/合規/分階段) |
