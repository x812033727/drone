# CLAUDE.md

商用無人機 monorepo(規劃文件 + Phase 0 軟體)。產品:PA-1(6 kg 四軸)/ PB-1(48 kg 六軸)共用航電 AC-1;細節見根 README 導覽。全部文件與 commit 用繁體中文。

## 常用指令

```bash
# 環境(Python 3.10+;所有套件共用一個 venv)
python -m venv .venv && . .venv/bin/activate
pip install ruff pytest && for f in tools/requirements.txt onboard/*/requirements.txt cloud/ingest/requirements.txt; do pip install -r "$f"; done
pip install -e interfaces/proto/gen/python -e onboard/mission_exec

ruff check .          # lint(設定在根 pyproject.toml;proto 生成碼已 exclude)
pytest -q             # 全部單元測試(testpaths=onboard/cloud/tools,不需 SITL/docker)

# 雲端棧(本機驗證用隔離埠,勿用預設埠——此機可能跑著其他服務)
cd cloud/deploy/compose && MQTT_PORT=31883 PG_PORT=35432 GRAFANA_PORT=33100 \
  docker-compose -p <獨特名> up -d --build --wait   # 結束必 down -v

# SITL(headless,不需編譯 PX4)
docker run --rm -d --name <獨特名> jonasvautherin/px4-gazebo-headless:1.15.4
# 等 ~40–60s GPS lock;客戶端 udpin://0.0.0.0:14540
```

## 鐵則(實測換來的,勿重蹈)

1. **headless SITL 映像主動送 MAVLink 到 docker gateway——絕不可做 `-p` UDP 埠映射**(docker-proxy 會佔住 host 埠反而收不到)。host 14540 被占時:sed 容器內 `build/px4_sitl_default/etc/init.d-posix/px4-rc.mavlink` 改 offboard remote port(勿改 ROMFS 源檔,會觸發 rebuild)。
2. 該映像**不含 uxrce_dds_client**(1.15.x 全系列,基底 cmake 過舊被靜默跳過);DDS 測試用 `onboard/ros2_ws/docker/Dockerfile.px4-sitl-dds`(SIH,3 秒就緒)。
3. **PX4 topic 的 ROS 2 訂閱 QoS 必須 BestEffort + TransientLocal**(Reliable 靜默收不到)。
4. SITL 就緒晚於任何固定 sleep 都可能發生:**arm 一律走重試**(`mission_exec.executor._arm_with_retry` / `sitl_scenarios.runner.arm_with_retry`),失敗路徑必須快速退出(mavsdk/grpc 非 daemon 執行緒會拖住 `sys.exit`,失敗分支用 `os._exit`)。
5. mavsdk_server 同機多程序:**一個 spawn、其餘 `--mavsdk-address localhost:50051` 顯式共用**,不要依賴隱性埠共用。
6. SITL 電量模擬有 SOC 地板陷阱(`BAT1_V_LOAD_DROP=0` 才能放到 Critical 以下);`COM_LOW_BAT_ACT=2` 在 v1.15 是 Land mode,本專案矩陣行為用 **3**。
7. GeoFence 越界注入用 offboard 速度(任務航點放界外會被 PX4 三層預防擋掉);RC 失聯在 SITL 無韌體消費者,用 datalink 失聯代理。
8. 本機一切測試資源(容器名/埠/compose -p)用**獨特名稱與高位埠**,跑完清乾淨;此機同時跑著多個正式服務。

## 慣例

- **規格數字單一事實來源**:規格總表在 `docs/00-overview.md`;重量預算在 `propulsion.md §3`;測試 ID 在 `docs/02-verification-validation.md`(RTM);失效保護行為矩陣在 `docs/03-safety-analysis.md §4`。其他文件一律引用、不複寫;改數字要全樹 grep 同步。
- 文件升 rev 會重排章節號:**交叉引用(§N)要跟著修**,全 repo grep 舊節號。
- 需求引用一律用 REQ ID(`docs/01-requirements.md`);Phase 0 的驗證載體是 F01–F20(`docs/50-project/phase0/flight-test-plan.md`)。
- proto 契約(`interfaces/proto/`)是機-雲唯一 schema:改動先改 .proto,`generate.sh`(釘版 grpcio-tools)重生並 commit 生成碼;線上 wire = proto3 JSON(int64 序列化為字串);MQTT 事件語意 at-least-once,消費端以首個終態為準。
- PR 工作流:worktree + 每 PR 一個 `claude/*` 分支 → CI 綠再合;**堆疊 PR 勿用 `gh pr merge --delete-branch`**(子 PR 會被 CLOSED 且無法 reopen)——先 `gh pr edit --base main` 再合,最後統一清分支。
- 跨多分支的改動,合併前先在本地建整合樹驗證(單支 PR 的 CI 看不到組合問題)。

## CI

- `ci.yml`:每 PR lint+pytest(條件式裝依賴,堆疊合併任何中間態可跑)。
- `sitl-integration.yml`:**nightly**(台北 02:30)+ 手動——mission-sitl / failsafe f09–f12 matrix / uxrce-dds-smoke;刻意不掛 PR(實時模擬有 flaky 面),穩定後再議升 gate。失敗先讀 job log 的 `RESULT:` 行與 SITL 傾印。
- `cloud-smoke.yml` / `proto.yml`:compose 煙霧與契約守門(codegen 漂移 = `git diff --exit-code gen/`)。
