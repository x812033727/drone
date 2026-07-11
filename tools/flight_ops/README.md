# flight_ops — 執飛工具包

飛行日的三件工具:參數檔、參數批次寫入/核對、飛行後歸檔。對應
[build-and-first-flight.md](../../docs/50-project/phase0/build-and-first-flight.md)
§3(參數表 v1)/ §7(飛行日 SOP)與
[flight-test-plan.md](../../docs/50-project/phase0/flight-test-plan.md)
§1(四件套缺一不計數)/ §3(架次紀錄模板)。

| 交付 | 用途 | 對應文件 |
|------|------|----------|
| `params/dev-machine-v1.params` | QGC 標準參數檔:失效保護參數表 v1 + 電池三參數(4S) | build-and-first-flight §3 |
| `apply_params.py` | 批次寫入 + 逐項回讀比對;`--dry-run` 只核對不寫 | §3 寫入凍結、§7 飛行日參數核對 |
| `archive_flight.py` | ULog 歸檔 + 跑 `ulog_report.py` + 生成架次紀錄底稿 | flight-test-plan §1/§3 |

## 用法(於 tools/ 目錄執行)

```bash
pip install -r requirements.txt   # mavsdk 等

# 1. 寫入參數表 v1 並回讀核對(全 OK exit 0,任一 DIFF exit 1)
python -m flight_ops.apply_params --url udpin://0.0.0.0:14540

# 2. 飛行日參數核對(只讀現值比對,不寫入;圍欄/RTL 高度核對當日場地)
python -m flight_ops.apply_params --dry-run

# 3. 飛行後歸檔(建 {root}/{日期}/{架次}-{機號}/,拷 ULog、產 report.txt、
#    生成 sortie-record.md 底稿並印四件套缺項提醒)
python -m flight_ops.archive_flight --ulog ~/logs/07_31_22.ulg \
    --sortie F05 --drone DEV-01 --result 通過
```

- `--file` 預設為套件內 `params/dev-machine-v1.params`;兩機參數表分開版控時各自給檔。
- 歸檔根目錄預設 `flight-logs/`(已列入 .gitignore,正式歸檔走雲端/LFS)。
- `COM_LOW_BAT_ACT=3`:v1.15 中 2=Land mode 會讓 Critical 就地降落(SITL F10 實測),勿回退 2。

## 測試

```bash
python -m pytest tools/flight_ops/tests -q   # 不需 SITL
```
