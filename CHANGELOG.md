# Changelog

本專案所有值得記錄的變更都會寫在這裡。

格式依循 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/),
版本號依循 [語意化版本](https://semver.org/lang/zh-TW/)。

Release 由 `git push` tag `v*` 觸發:CI 建置並簽章各服務容器映像、推送到 GHCR,
並以本檔對應版本章節作為 GitHub Release notes(見 `.github/workflows/release.yml`)。

## [Unreleased]

<!-- 下一版變更累積於此,發版時移至新版本章節。 -->

## [0.1.0] - 2026-07-13

首個可商用交付版本(Phase 0 平台底座 + P0/P1 商用化)。以私有部署(Helm)交付:
遙測落庫、機隊/任務服務、Web 指揮中心,並具備認證、傳輸安全與供應鏈可驗證性。

### Added

- **雲端服務層**
  - fleet-svc:機隊/裝置/韌體 CRUD、遙測在線狀態、SSE 即時串流。
  - mission-svc:航線庫、任務 CRUD、派遣(MissionPlan/MissionCommand)與進度回收。
  - log-svc:ULog 上傳、背景解析報告、飛行日誌摘要落庫。
  - ingest:MQTT(proto3 JSON)遙測 → TimescaleDB。
- **地面站 / Web 指揮中心**:即時地圖、機隊狀態、操作端寫入 UI 與前端 RBAC。
- **機載**:drone_agent systemd 部署單元與安裝腳本(Jetson);obstacle_guard 避障安全庫與 ROS node。
- **認證與授權**:fleet/mission/log-svc JWT 認證 + RBAC(viewer/operator/admin);
  Web OIDC SSO 登入(授權碼 + PKCE);SSE token 認證。
- **傳輸安全(端到端)**:PKI 最小體系(CA/簽發/輪換/CRL);MQTT mTLS + per-device ACL +
  CRL 吊銷強制;drone_agent/ingest/fleet-svc/mission-svc 全鏈客戶端 mTLS;整棧 mTLS overlay。
- **私有部署**:drone-platform Helm chart,含生產運維(備份、migration hook、
  NetworkPolicy、PDB、livenessProbe、securityContext、Grafana provisioning)。
- **可觀測性**:各服務 `/metrics`(Prometheus)+ 告警規則 + SLO 文件。
- **視訊**:MediaMTX 串流認證 + 端到端部署 runbook。
- **供應鏈與發布(本版新增)**:
  - 容器映像發布到 GHCR,附掛 provenance / SBOM attestation。
  - cosign keyless(GitHub OIDC,無長期金鑰)映像簽章,來源可 `cosign verify`。
  - 機器可讀 API 契約:fleet/mission/log-svc 的 `openapi.json` 入版控,
    CI 守門確保契約與程式碼同步(`tools/dump_openapi.py` + `openapi` workflow)。
  - 本 CHANGELOG 與 tag 觸發的 GitHub Release 自動化。

### Security

- 容器映像以非 root(uid/gid 1000)執行。
- CI 供應鏈掃描:bandit、buf breaking、CodeQL、SBOM。

[Unreleased]: https://github.com/x812033727/drone/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/x812033727/drone/releases/tag/v0.1.0
