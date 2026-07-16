# patches — 對 upstream 的樹內小 patch

命名:`NNNN-<slug>.patch`(依序套用,`git apply --3way`)。
**patch 數量即 firmware.md §1「≤20 commits」預算的量尺;> 10 個時啟動
fork repo 升級決策**(見 [../README.md](../README.md))。

現況(預算 3/20):

| # | 內容 | 狀態 |
|---|------|------|
| 0001 | SITL dialect 切換(`CONFIG_MAVLINK_DIALECT` → drone_sitl) | ✅ F3 |
| 0002 | 自訂訊息 streams(三 stream 標頭 + mavlink_messages.cpp 守衛註冊) | ✅ F4 |
| 0003 | PA-1 SIH airframe 10990_sihsim_pa1(內建失效保護參數包 v1) | ✅ F5 |

規則:每個 patch 對 upstream 的**單一關注點**;不碰 EKF2/控制器/commander;
upstream 升版(px4.lock)時全數重滾並以 firmware-ci 驗證。
