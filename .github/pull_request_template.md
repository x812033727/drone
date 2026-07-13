<!-- 全部用繁體中文。標題精簡描述變更。 -->

## 變更摘要
<!-- 做了什麼、為什麼。關聯 REQ ID / 架次 F<nn> / 測試 ID(若有)。 -->

## 變更類型
- [ ] 文件
- [ ] 機載軟體(onboard)
- [ ] 雲端(cloud)
- [ ] 介面契約(interfaces/proto)
- [ ] 工具 / CI

## 驗證
<!-- 怎麼驗的。至少貼 ruff / pytest 結果;動到 cloud/SITL 者說明煙霧或 nightly。 -->
- [ ] `ruff check .` 通過
- [ ] `pytest -q` 通過
- [ ] 動到 proto:已跑 `generate.sh` 並 commit 生成碼(`git diff --exit-code gen/` 乾淨)

## 規格一致性(慣例守則)
- [ ] 改到規格數字者已全樹 grep 同步(單一事實來源見 CLAUDE.md)
- [ ] 文件升 rev / 改節號者已修好交叉引用(§N)
- [ ] 契約破壞性變更?若是,已走 `drone.v2`(非在 v1 動欄位編號/型別)
