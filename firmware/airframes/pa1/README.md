# airframes/pa1 — PA-1 SITL 參數包(代理值)

- **airframe**:patch 0003 的 `10990_sihsim_pa1`(SIH;`PX4_SYS_AUTOSTART=10990` 起機)。
- **參數包**:`pa1-sitl-v1.params`——失效保護參數表 v1 + 電池三參數,與
  [tools/flight_ops/params/dev-machine-v1.params](../../../tools/flight_ops/params/) 同口徑
  (單一事實來源 = build-and-first-flight.md §3);煙霧以 `assert_params.py` 逐項回讀核對。

⚠️ **誠實邊界**:動力、慣量、混控沿 SIH 預設(X500 級代理)——本 airframe 驗證的是
任務邏輯 / 參數 / 契約層;PA-1 實機的機體數值待 rev A 實測定容後另立版本
(firmware.md §3 調參流程)。
