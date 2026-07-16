# params — QGC 載入用參數預設檔

**單一事實來源 = [tools/flight_ops/params/dev-machine-v1.params](../../../tools/flight_ops/params/dev-machine-v1.params)**
(失效保護參數表 v1 + 電池三參數,與 build-and-first-flight.md §3 由
`tools/flight_ops/tests/test_params_file.py` 雙重錨定)。

QGC 操作步驟:Vehicle Setup → Parameters → Tools → **Load from file**,
直接載入上述檔案(QGC 的 .params 與 apply_params.py 用同一格式)。
本目錄刻意**不複製**該檔(repo 慣例:引用不複寫,防兩處漂移)。

- Phase 0 開發機(X500 V2,4S)= 上述檔案。
- PA-1 專屬參數包:機體慣量/動力數值需 rev A 實測定容(Phase 1),屆時另立
  `pa1-v1.params` 並比照建立錨定測試;SITL 代理參數(SIH)屬 firmware 軌,
  見 [firmware/airframes/](../../../firmware/)。
