# tools/loadgen — 負載產生器

雲端平台的負載/壓測工具。方法論、誠實邊界與實測記錄表在
[docs/50-project/phase1/perf-baseline.md](../../docs/50-project/phase1/perf-baseline.md)。

```bash
pip install -r tools/loadgen/requirements.txt   # 獨立依賴,刻意不進主 CI
```

| 檔案 | 用途 |
|------|------|
| `mint_token.py` | HS256 token 鑄造(viewer/operator/admin × org)。⚠️ 受測棧必須設 `JWT_SECRET`,dev 模式一律 admin、壓不到配額/限流/org 路徑 |
| `locustfile.py` | REST 場景:viewer 讀路徑 + operator route→mission→dispatch 全流程;402/429 視為預期回應另計 |
| `mqtt_fanin.py` | N 台假機 × R Hz 遙測 fan-in(單連線輪發;`--connections` 可分片),結束印實發速率與落庫率核對查詢 |

一律對**隔離棧**跑(獨特 compose -p + 高位埠,CLAUDE.md 鐵則 8),跑完 `down -v`。
