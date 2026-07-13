"""drone_common:雲端服務(fleet/mission/log)共用純邏輯。Wave 1 A1 去重。

模組:
- auth:JWT/RBAC 純函式(角色萃取、權級、租戶隔離、Principal)。**無環境相依、
  無模組狀態**——各服務的 auth.py 仍保留自己的執行期層(env 常數、_decode、
  authorize_token、require_*),因單元測試以 monkeypatch 服務模組級全域驗證。
- migrate:輕量前向 SQL migration runner,schema 與 migrations 目錄由呼叫端參數化。
- audit:審計軌跡寫入(best-effort),schema 由呼叫端參數化。
"""
