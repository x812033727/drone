# patches — 對 upstream 的樹內小 patch

命名:`NNNN-<slug>.patch`(依序套用,`git apply --3way`)。
**patch 數量即 firmware.md §1「≤20 commits」預算的量尺;> 10 個時啟動
fork repo 升級決策**(見 [../README.md](../README.md))。

現況:尚無 patch(F1 建置鷹架驗證純 upstream)。已排定:

| # | 內容 | 對應 PR |
|---|------|---------|
| 0001 | SITL dialect 切換(`CONFIG_MAVLINK_DIALECT` → drone_sitl) | F3 |
| 0002 | 自訂訊息 streams 註冊(SPRAY_TELEMETRY/BATTERY_DETAIL/PAYLOAD_STATUS) | F4 |
| 0003 | PA-1 SIH airframe(init.d-posix) | F5 |

規則:每個 patch 對 upstream 的**單一關注點**;不碰 EKF2/控制器/commander;
upstream 升版(px4.lock)時全數重滾並以 firmware-ci 驗證。
