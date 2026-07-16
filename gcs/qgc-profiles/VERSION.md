# QGC 版本 pin

| 項目 | 值 |
|------|-----|
| Pin 版本 | **v5.0.8**(官方 stable,2025-10 釋出) |
| 下載 | https://github.com/mavlink/qgroundcontrol/releases/tag/v5.0.8 |
| 對應飛控 | PX4 v1.15.x(Pixhawk 6X 開發機 / SITL) |
| Pin 日期 | 2026-07-16 |

## 升版流程(改本檔前必跑)

1. 讀 upstream release notes,確認無破壞性變更(參數檔載入、.plan 格式、自訂圖源設定)。
2. 回歸清單:
   - [ ] 載入 `params/` 參數預設檔無錯誤且逐項生效(SITL 或開發機核對)
   - [ ] 載入 `plans/` 任務範本,航點/圍欄正確顯示
   - [ ] 台灣圖源(README §台灣圖源 兩條 URL)在新版設定介面可用
   - [ ] 連 SITL(`jonasvautherin/px4-gazebo-headless:1.15.4`)遙測正常
3. 通過後更新本表的版本與日期,並在下方紀錄。

## 升版紀錄

| 日期 | 版本 | 備註 |
|------|------|------|
| 2026-07-16 | v5.0.8 | 初次 pin(選項 A 落地,PR 見 git 歷史) |
