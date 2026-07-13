# cloud/pki — 裝置憑證 PKI(C1 最小體系)

> 對 [docs/20-software/security.md §2](../../docs/20-software/security.md)「裝置身分與 PKI」:
> 每機一憑證、機-雲 mTLS、失竊/退役 CRL 吊銷。

**範圍(C1)**:純工具 + 文件,**不動 broker**。以 openssl 建根 CA、簽發 per-device
client 憑證、輪換、CRL 吊銷。C2 才把憑證接上 EMQX 的 mTLS + per-device 主題 ACL。
無實體硬體時,SITL 裝置身分 = 用同一 CA 簽 `dev-1` 等測試憑證(模擬「出廠燒錄」)。

## 用法

```bash
export PKI_CA_DIR=/secure/path/ca          # 選填;預設 cloud/pki/ca(不入版控)
cloud/pki/init_ca.sh                        # 建根 CA(私鑰 4096,離線保管)
cloud/pki/issue_device.sh PA1-0001         # 簽發裝置憑證(CN/SAN=serial,clientAuth)
                                           #   → 印 SHA-256 指紋供 fleet-svc 綁定
cloud/pki/revoke_device.sh PA1-0001        # 吊銷 + 更新 CRL(失竊/退役)
cloud/pki/gen_crl.sh                        # 手動更新 CRL
cloud/pki/verify_pki.sh                     # 自我驗證整個生命週期(CI 亦跑)
```

## 與 fleet-svc 整合

- `issue_device.sh` 印出的 SHA-256 指紋填入 `fleet.device.cert_fingerprint`(#55 已留欄位),
  雲端以指紋綁機身序號、防裝置冒名。
- 憑證有效期一年;輪換 = 對同 serial 再 `issue_device.sh`(舊憑證效期內完成換發後吊銷)。
- 吊銷後 fleet-svc 應把 `device.status` 設為 `revoked`(#60 已有該狀態與 `cert:revoke` 端點規劃)。

## 安全鐵則

- **私鑰絕不入版控**(`.gitignore` 已擋 `ca/`、`*.pem`、`*.key`);根 CA 私鑰離線保管。
- 根 CA 私鑰 4096-bit、離線;裝置私鑰不出裝置(此處為 SITL/開發模擬)。
- 量產(Phase 2+)評估 TPM/SE 安全元件存裝置私鑰。

## 待做(後續)

- **C2**:EMQX mTLS 終結 + 載入此 CRL + per-device 主題 ACL(HTTP auth hook → fleet-svc)。
- 生產可評估 smallstep `step-ca`(內建 ACME/自動輪換);本 C1 用 openssl 求零額外依賴、易審。
