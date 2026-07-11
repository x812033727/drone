# sitl_scenarios — 失效保護 SITL 場景回歸(F09–F12)

對 PX4 v1.15.4 SITL(`jonasvautherin/px4-gazebo-headless:1.15.4`,classic Gazebo iris)
自動跑 [flight-test-plan](../../docs/50-project/phase0/flight-test-plan.md) F09–F12 的
失效保護場景,注入失效並以遙測斷言行為,輸出 `RESULT: PASS/FAIL` 與模式轉換序列。
是 [03-safety-analysis §4 失效保護矩陣](../../docs/03-safety-analysis.md) 與
[sitl-setup.md §5](../../docs/50-project/phase0/sitl-setup.md) 注入表的可執行版;
CI 由 `.github/workflows/sitl-integration.yml` 的 `failsafe-scenarios` job nightly 執行。

> 此映像用 classic gazebo iris(非 gz_x500):失效保護行為與機型無關,僅驗
> 邏輯與模式序列,不可用於調參(對齊 sitl-setup.md §3)。

## 用法

```bash
# 1. 啟動 SITL(映像主動把 MAVLink 送到 host,監聽即可,「不要」做 -p 埠映射)
docker run --rm -d --name px4-sitl jonasvautherin/px4-gazebo-headless:1.15.4
sleep 60   # 等 EKF/GPS lock(實測約 40 秒)

# 2. 安裝依賴,於 tools/ 目錄下執行
pip install -r sitl_scenarios/requirements.txt
python -m sitl_scenarios --scenario f11 --url udpin://0.0.0.0:14540 --container px4-sitl

# 3. 跑完清容器
docker rm -f px4-sitl
```

- `--container`:**F10 必要**(docker exec 跑 px4-listener 輪詢與 px4-param 調 drain)、
  **F09 必要**(docker inspect 取容器 IP 做被動觀測的源 IP 過濾;亦可改給 `--source-ip`)。
- `--grpc-port`(預設 50600):mavsdk_server gRPC 埠;多 agent / 多場景並行時錯開。
- `--all` 依序跑四場景:場景會改參數、放電、觸發失效保護,**每場景之間請重啟
  SITL 容器**(CI 即每場景獨立容器);單容器連跑僅供開發便利,不保證狀態乾淨。
- 多實例並行時 host 14540 會相撞:改埠要在容器內 sed **build 副本**
  `/root/Firmware/build/px4_sitl_default/etc/init.d-posix/px4-rc.mavlink` 的
  `udp_offboard_port_remote=$((14540+px4_instance))`(切勿改 ROMFS 源檔,會觸發
  romfs 重建而 make 失敗),例:

  ```bash
  docker run --rm -d --name px4-mine --entrypoint /bin/bash \
    jonasvautherin/px4-gazebo-headless:1.15.4 \
    -c "sed -i 's/14540+px4_instance/28540+px4_instance/' \
        /root/Firmware/build/px4_sitl_default/etc/init.d-posix/px4-rc.mavlink \
        && exec /root/entrypoint.sh"
  # host 端:--url udpin://0.0.0.0:28540
  ```

## 場景一覽(注入法與通過準則,全部以探測實測行為為準)

| 場景 | 對應架次 / 矩陣列 | 注入法 | 通過準則(實測基準) |
|------|------------------|--------|----------------------|
| `f09` 失聯保護 | F09「失聯 RTL」/ 矩陣「RC 失聯」列 | **datalink/GCS 失聯代理**:`NAV_DLL_ACT=2`、`COM_DL_LOSS_T=3`,kill 自 spawn 的 mavsdk_server(= 唯一 GCS 心跳源);被動 pymavlink 觀測 14550(依容器源 IP 過濾) | 注入前 AUTO_MISSION+IN_AIR;kill 後 30 s 內 AUTO_RTL(實測 +10.4/+11.2 s,經 AUTO_LOITER 過渡);RTL 前維持 IN_AIR |
| `f10` 低電量三級 | F10「低電量分級」/ 矩陣低電量三列 | `COM_LOW_BAT_ACT=3` + 門檻 0.20/0.10/0.05 + `BAT1_V_LOAD_DROP=0`(SITL 限定)後 `SIM_BAT_MIN_PCT=0`+`SIM_BAT_DRAIN=90`;CRITICAL 瞬間放慢 drain 至 240 避免 5 s Hold 吞掉 RTL | LOW/CRITICAL/EMERGENCY 依序;LOW 僅警告留 MISSION;CRITICAL→AUTO_RTL(允許 LOITER Hold 過渡);EMERGENCY→AUTO_LAND;落地自動 disarm |
| `f11` GeoFence | F11「GeoFence 觸發」 | 150 m circle inclusion 圍欄 + `GF_ACTION=3`、`GF_PREDICT=1`;起飛 30 m 後 offboard 北向 8 m/s 逼近邊界(任務航點放界外飛不起來,見下) | RETURN_TO_LAUNCH 觸發;觸發點離 home > 90 m(實測 128.8 m,預測煞停在邊界內);全程不穿越邊界 > 10 m(實測零穿越) |
| `f12` GPS 失效 | F12「GPS 劣化降級」 | `SYS_FAILURE_EN=1` 後任務中 `failure.inject(SENSOR_GPS, OFF, 0)` | 注入後 8 s 內 NO_GPS、15 s 內 flight_mode→**LAND(就地降落)**、25 s 內 global_position_ok=False、150 s 內落地自動 disarm |

四場景經探測皆判定 **feasible**,故無 NotImplementedError 模組;若日後某場景被判
不可行,依套件慣例仍建模組並 `raise NotImplementedError(原因)`,CLI 會誠實輸出
`RESULT: NOT-IMPLEMENTED`。

## 探測發現(與文件的差異,場景 docstring 內亦有完整註記)

1. **F09 觸發語義偏移**:矩陣的承載觸發是 RC 失聯(`NAV_RCL_ACT=2`),但 SITL 無實體
   RC 且 `COM_RC_IN_MODE=1` 令 RC 失聯失效保護關閉;MAVSDK failure plugin 的
   `SYSTEM_MAVLINK_SIGNAL`/`RC_SIGNAL` 在 PX4 v1.15.4 無韌體消費者(實跑注入後模式
   恆為 AUTO_MISSION;`inject()` 回 TIMEOUT 是 PX4 不回 ack,非不支援之證)。本場景
   以 datalink 失聯(`NAV_DLL_ACT=2`)作可測代理——驗的是 RTL 失效保護機制,非
   Phase 0 `NAV_DLL_ACT=0` 的預設行為。
2. **F10 參數表 v1 有誤**:`COM_LOW_BAT_ACT=2` 在 PX4 v1.15 = Land mode(critical 即
   就地降落,實測證實),與 build-and-first-flight.md §3「2(Critical 觸發 RTL)」及
   03-safety-analysis §4.1 矛盾;矩陣「Critical RTL → Emergency 降落」須 **=3**。
   兩份文件待參數表改版時修訂。
3. **F11 試飛計畫寫法在 SITL 飛不起來**:界外航點任務 `start_mission` 被 feasibility
   check 拒(DENIED)、界外 goto 靜默忽略、空中補上傳圍欄令任務直接 HOLD——此三層
   是「預防/拒絕解鎖」佐證;空中觸發須用 offboard 速度逼近。`GF_PREDICT` 此映像
   預設 0(上游預設 1),本場景設 1;實機參數表應明確納入。
4. **F12 全 GPS OFF 走終端分支 LAND**,不是矩陣「懸停→RTH」漸進分支(位置估計徹底
   發散,Hold/RTL 無位置可用);要驗漸進降級需注入部分劣化(GARBAGE/降衛星數)。
5. **觀測污染陷阱**:多個 SITL 容器都把 GCS MAVLink 廣播到 host:14550,被動觀測不
   過濾源 IP 會混收多機心跳造成假 PASS——F09 強制要求 `--container` 或 `--source-ip`。

## 目錄結構

```
sitl_scenarios/
├── main.py / __main__.py   # CLI:python -m sitl_scenarios --scenario f09|f10|f11|f12 | --all
├── runner.py               # 共用骨架:連線/任務/遙測記錄(連線與任務段抄自 onboard/mission_exec,見檔頭)
├── checks.py               # 斷言純函式(無 mavsdk 依賴,單元可測)
├── scenarios/f09..f12*.py  # 各場景:docstring 含注入法、通過準則、與文件差異
└── tests/test_checks.py    # 斷言邏輯單元測試(不需 SITL)
```

## CI

`.github/workflows/sitl-integration.yml` 的 `failsafe-scenarios` job:與 `mission-sitl`
同 nightly 排程(不擋 PR),matrix 四場景各自獨立 runner VM + 獨立 SITL 容器,
斷言 log 內 `RESULT: PASS`;失敗傾印容器 log。
