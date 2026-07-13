"""訂閱金流(綠界 ECPay)測試。四層,皆不碰真 DB:

1. CheckMacValue 純函式:**以綠界官方文件的已知測試向量驗證**(HashKey/HashIV + 一組
   AioCheckOut 參數 → 官方公布的 SHA256 CheckMacValue),另驗排序無關、驗章壞章拒絕。
2. 設定/定價/訂單號純函式:load_config 沙箱 vs 正式、plan_price env 覆寫、new_trade_no 格式。
3. repo 層 SQL 契約:billing_transaction CRUD + activate_org_plan upsert 綁正確參數。
4. 端點層(TestClient + 記憶體連線):checkout(RBAC/free 拒絕/沙箱參數/落 pending 交易)、
   callback(驗章成功啟用方案 + 記交易、壞章 400、冪等重送)、subscription 查詢、dev 模式。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import asyncpg
import jwt
import pytest
from fastapi.testclient import TestClient
from fleet_svc import auth, billing, limits, main, repo
from fleet_svc.billing import (
    EcpayConfig,
    build_checkout_params,
    check_mac_value,
    load_config,
    new_trade_no,
    plan_price,
    verify_callback,
)
from fleet_svc.limits import RateLimiter

# ----------------------------------------------------------------------------
# 1. CheckMacValue —— 綠界官方文件已知測試向量(known-answer test)
# ----------------------------------------------------------------------------

# 出處:綠界 ECPay Developers「檢查碼機制」文件 worked example。
# https://developers.ecpay.com.tw/2902/
_OFFICIAL_HASH_KEY = "pwFHCqoQZGmho4w6"
_OFFICIAL_HASH_IV = "EkRm7iFT261dpevs"
_OFFICIAL_PARAMS = {
    "MerchantID": "3002607",
    "MerchantTradeNo": "ecpay20230312153023",
    "MerchantTradeDate": "2023/03/12 15:30:23",
    "PaymentType": "aio",
    "TotalAmount": "30000",
    "TradeDesc": "促銷方案",
    "ItemName": "Apple iphone 15",
    "ReturnURL": "https://www.ecpay.com.tw/receive.php",
    "ChoosePayment": "ALL",
    "EncryptType": "1",
}
_OFFICIAL_EXPECTED = "6C51C9E6888DE861FD62FB1DD17029FC742634498FD813DC43D4243B5685B840"


def test_check_mac_value_matches_official_vector():
    """核心正確性:與綠界文件公布的 CheckMacValue 逐字元相符。"""
    got = check_mac_value(_OFFICIAL_PARAMS, _OFFICIAL_HASH_KEY, _OFFICIAL_HASH_IV)
    assert got == _OFFICIAL_EXPECTED


def test_check_mac_value_ignores_input_order():
    """排序在函式內做,輸入字典順序不影響結果(仍等於官方向量)。"""
    shuffled = dict(reversed(list(_OFFICIAL_PARAMS.items())))
    assert check_mac_value(shuffled, _OFFICIAL_HASH_KEY, _OFFICIAL_HASH_IV) == _OFFICIAL_EXPECTED


def test_check_mac_value_excludes_checkmacvalue_field():
    """已帶 CheckMacValue 的字典再算一次,結果不變(該欄被排除)。"""
    with_mac = {**_OFFICIAL_PARAMS, "CheckMacValue": "STALE"}
    assert check_mac_value(with_mac, _OFFICIAL_HASH_KEY, _OFFICIAL_HASH_IV) == _OFFICIAL_EXPECTED


def test_verify_callback_good_and_bad():
    cfg = EcpayConfig(
        merchant_id="3002607", hash_key=_OFFICIAL_HASH_KEY, hash_iv=_OFFICIAL_HASH_IV,
        action_url="x", return_url="y", client_back_url=None, sandbox=False,
    )
    good = {**_OFFICIAL_PARAMS, "CheckMacValue": _OFFICIAL_EXPECTED}
    assert verify_callback(good, cfg) is True
    # 大小寫不敏感(綠界回傳大寫,仍應通過)
    assert verify_callback({**_OFFICIAL_PARAMS, "CheckMacValue": _OFFICIAL_EXPECTED.lower()}, cfg)
    # 壞章 / 缺章 → 拒絕
    assert verify_callback({**_OFFICIAL_PARAMS, "CheckMacValue": "DEADBEEF"}, cfg) is False
    assert verify_callback(dict(_OFFICIAL_PARAMS), cfg) is False


# ----------------------------------------------------------------------------
# 2. 設定 / 定價 / 訂單號 純函式
# ----------------------------------------------------------------------------


def _clear_ecpay_env(monkeypatch):
    for k in (
        "ECPAY_MERCHANT_ID", "ECPAY_HASH_KEY", "ECPAY_HASH_IV", "ECPAY_STAGE",
        "ECPAY_RETURN_URL", "ECPAY_CLIENT_BACK_URL", "ECPAY_PRICE_PRO", "ECPAY_PRICE_ENTERPRISE",
    ):
        monkeypatch.delenv(k, raising=False)


def test_load_config_sandbox_when_unset(monkeypatch):
    _clear_ecpay_env(monkeypatch)
    cfg = load_config()
    assert cfg.sandbox is True
    assert cfg.merchant_id == billing.SANDBOX_MERCHANT_ID
    assert cfg.hash_key == billing.SANDBOX_HASH_KEY
    assert "payment-stage.ecpay.com.tw" in cfg.action_url  # 沙箱走測試環境


def test_load_config_production_when_all_set(monkeypatch):
    _clear_ecpay_env(monkeypatch)
    monkeypatch.setenv("ECPAY_MERCHANT_ID", "1234567")
    monkeypatch.setenv("ECPAY_HASH_KEY", "prodkey1234567890")
    monkeypatch.setenv("ECPAY_HASH_IV", "prodiv1234567890")
    cfg = load_config()
    assert cfg.sandbox is False
    assert cfg.merchant_id == "1234567"
    assert "payment.ecpay.com.tw" in cfg.action_url and "stage" not in cfg.action_url


def test_load_config_partial_creds_falls_back_to_sandbox(monkeypatch):
    """只設 MerchantID(缺金鑰)→ 仍沙箱(不會用半套正式憑證去打正式環境)。"""
    _clear_ecpay_env(monkeypatch)
    monkeypatch.setenv("ECPAY_MERCHANT_ID", "1234567")
    assert load_config().sandbox is True


def test_plan_price_defaults_and_env_override(monkeypatch):
    _clear_ecpay_env(monkeypatch)
    assert plan_price("free") == 0
    assert plan_price("pro") == 3000
    assert plan_price("enterprise") == 30000
    monkeypatch.setenv("ECPAY_PRICE_PRO", "1888")
    assert plan_price("pro") == 1888
    monkeypatch.setenv("ECPAY_PRICE_PRO", "not-an-int")  # 非法值退回預設
    assert plan_price("pro") == 3000


def test_new_trade_no_format():
    tn = new_trade_no()
    assert tn.startswith("SUB") and len(tn) <= 20 and tn.isalnum()
    assert new_trade_no() != new_trade_no()  # 具唯一性


def test_build_checkout_params_has_required_fields_and_valid_mac(monkeypatch):
    _clear_ecpay_env(monkeypatch)
    cfg = load_config()
    p = build_checkout_params(cfg, org_id="acme", plan="pro", amount=3000, trade_no="SUBTEST01")
    for field in (
        "MerchantID", "MerchantTradeNo", "MerchantTradeDate", "PaymentType",
        "TotalAmount", "TradeDesc", "ItemName", "ReturnURL", "ChoosePayment",
        "EncryptType", "CheckMacValue",
    ):
        assert field in p
    assert p["TotalAmount"] == "3000"
    assert p["CustomField1"] == "acme" and p["CustomField2"] == "pro"
    # 自身產生的 CheckMacValue 必可自我驗證
    assert verify_callback(p, cfg) is True


# ----------------------------------------------------------------------------
# 3. repo 層 SQL 契約(stub 連線)
# ----------------------------------------------------------------------------


class _StubConn:
    def __init__(self, row: dict | None = None) -> None:
        self.fetchrow_calls: list[tuple] = []
        self.fetch_calls: list[tuple] = []
        self._row = row

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        return self._row

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return [self._row] if self._row else []


_TXN_ROW = {
    "id": 1, "org_id": "acme", "plan": "pro", "amount": 3000,
    "trade_no": "SUB1", "status": "pending", "at": datetime.now(timezone.utc),
}
_ORG_ROW = {
    "org_id": "acme", "name": "acme", "plan": "pro", "status": "active",
    "max_devices": None, "max_fleets": None,
    "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
}


def test_repo_create_billing_txn_binds_columns():
    conn = _StubConn(row=_TXN_ROW)
    asyncio.run(repo.create_billing_txn(
        conn, org_id="acme", plan="pro", amount=3000, trade_no="SUB1"))
    sql, args = conn.fetchrow_calls[0]
    assert "INSERT INTO fleet.billing_transaction" in sql
    assert args == ("acme", "pro", 3000, "SUB1", "pending")


def test_repo_get_billing_txn_by_trade_no():
    conn = _StubConn(row=_TXN_ROW)
    asyncio.run(repo.get_billing_txn(conn, "SUB1"))
    sql, args = conn.fetchrow_calls[0]
    assert "WHERE trade_no = $1" in sql and args == ("SUB1",)


def test_repo_set_billing_txn_status():
    conn = _StubConn(row={**_TXN_ROW, "status": "paid"})
    asyncio.run(repo.set_billing_txn_status(conn, "SUB1", "paid"))
    sql, args = conn.fetchrow_calls[0]
    assert "SET status = $1, updated_at = now()" in sql and args == ("paid", "SUB1")


def test_repo_activate_org_plan_upserts():
    conn = _StubConn(row=_ORG_ROW)
    asyncio.run(repo.activate_org_plan(conn, "acme", "pro"))
    sql, args = conn.fetchrow_calls[0]
    assert "INSERT INTO fleet.org" in sql and "ON CONFLICT (org_id) DO UPDATE" in sql
    assert "status = 'active'" in sql and args == ("acme", "pro")


def test_repo_list_billing_txns_scoped_and_limited():
    conn = _StubConn(row=_TXN_ROW)
    asyncio.run(repo.list_billing_txns(conn, "acme", limit=5))
    sql, args = conn.fetch_calls[0]
    assert "WHERE org_id = $1" in sql and "LIMIT $2" in sql and args == ("acme", 5)


# ----------------------------------------------------------------------------
# 4. 端點層:記憶體連線 + TestClient
# ----------------------------------------------------------------------------

SECRET = "test-secret-key-billing-ecpay-0123456789abcdef"


class _MemConn:
    """支援 fleet.org + billing_transaction 的記憶體連線(端到端金流流程用)。"""

    def __init__(self) -> None:
        self.orgs: dict[str, dict] = {}
        self.txns: dict[str, dict] = {}
        self._next_id = 1

    async def fetchval(self, sql, *args):
        if "count(*) FROM fleet.org" in sql:
            return len(self.orgs)
        return 0

    async def fetch(self, sql, *args):
        if "FROM fleet.billing_transaction" in sql:  # list_billing_txns
            rows = [r for r in self.txns.values() if r["org_id"] == args[0]]
            rows.sort(key=lambda r: r["at"], reverse=True)
            return rows[: args[1]]
        if "FROM fleet.org" in sql:
            return sorted(self.orgs.values(), key=lambda r: r["org_id"])
        return []

    async def fetchrow(self, sql, *args):
        if "INSERT INTO fleet.billing_transaction" in sql:
            trade_no = args[3]
            if trade_no in self.txns:
                raise asyncpg.UniqueViolationError(f"dup {trade_no}")
            row = {
                "id": self._next_id, "org_id": args[0], "plan": args[1], "amount": args[2],
                "trade_no": trade_no, "status": args[4], "at": datetime.now(timezone.utc),
            }
            self._next_id += 1
            self.txns[trade_no] = row
            return row
        if "FROM fleet.billing_transaction WHERE trade_no = $1" in sql:
            return self.txns.get(args[0])
        if "UPDATE fleet.billing_transaction SET status" in sql:
            row = self.txns.get(args[1])
            if row is None:
                return None
            row["status"] = args[0]
            return row
        if "INSERT INTO fleet.org" in sql and "ON CONFLICT (org_id) DO UPDATE" in sql:
            org_id, plan = args[0], args[1]
            now = datetime.now(timezone.utc)
            row = self.orgs.get(org_id)
            if row is None:
                row = {
                    "org_id": org_id, "name": org_id, "plan": plan, "status": "active",
                    "max_devices": None, "max_fleets": None, "created_at": now, "updated_at": now,
                }
                self.orgs[org_id] = row
            else:
                row["plan"] = plan
                row["status"] = "active"
                row["updated_at"] = now
            return row
        if "INSERT INTO fleet.org" in sql:  # create_org (admin CRUD path)
            org_id = args[0]
            if org_id in self.orgs:
                raise asyncpg.UniqueViolationError(f"dup {org_id}")
            now = datetime.now(timezone.utc)
            row = {
                "org_id": args[0], "name": args[1], "plan": args[2], "status": args[3],
                "max_devices": args[4], "max_fleets": args[5], "created_at": now, "updated_at": now,
            }
            self.orgs[org_id] = row
            return row
        if "FROM fleet.org WHERE org_id = $1" in sql:
            return self.orgs.get(args[0])
        if "UPDATE fleet.org SET" in sql:
            org_id = args[-1]
            row = self.orgs.get(org_id)
            if row is None:
                return None
            set_part = sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
            for col, idx in re.findall(r"(\w+) = \$(\d+)", set_part):
                row[col] = args[int(idx) - 1]
            row["updated_at"] = datetime.now(timezone.utc)
            return row
        return None

    async def execute(self, sql, *args):
        return "INSERT 0 1"


class _MemPool:
    def __init__(self, conn: _MemConn) -> None:
        self._conn = conn

    def acquire(self):
        pool = self

        class _Acq:
            async def __aenter__(self):
                return pool._conn

            async def __aexit__(self, *a):
                return False

        return _Acq()


@pytest.fixture
def client(monkeypatch):
    _clear_ecpay_env(monkeypatch)  # 未設 ECPAY env → 沙箱模式
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(limits, "write_limiter", RateLimiter(rate_per_min=6000))
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    return TestClient(main.app), conn


def _tok(role: str, org: str) -> dict:
    claims = {"sub": f"{role}-{org}", "role": role, "org": org}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


# ---- checkout ----


def test_checkout_operator_own_org_sandbox(client):
    c, conn = client
    r = c.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=_tok("operator", "acme"))
    assert r.status_code == 200
    body = r.json()
    assert body["sandbox"] is True
    assert "payment-stage.ecpay.com.tw" in body["action_url"]
    p = body["params"]
    assert p["TotalAmount"] == "3000" and p["CustomField1"] == "acme" and "CheckMacValue" in p
    # 落一筆 pending 交易(供回調對帳)
    assert len(conn.txns) == 1
    txn = next(iter(conn.txns.values()))
    assert txn["org_id"] == "acme" and txn["plan"] == "pro" and txn["status"] == "pending"


def test_checkout_free_plan_rejected(client):
    c, conn = client
    r = c.post("/api/v1/billing/checkout", json={"plan": "free"}, headers=_tok("operator", "acme"))
    assert r.status_code == 400


def test_checkout_rbac_viewer_forbidden(client):
    c, conn = client
    r = c.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=_tok("viewer", "acme"))
    assert r.status_code == 403


# ---- callback ----


def _callback_body(conn_txn: dict, rtn_code: str = "1") -> dict:
    """依 pending 交易組一份綠界回調參數(用沙箱金鑰算 CheckMacValue)。"""
    params = {
        "MerchantID": billing.SANDBOX_MERCHANT_ID,
        "MerchantTradeNo": conn_txn["trade_no"],
        "RtnCode": rtn_code,
        "RtnMsg": "Succeeded" if rtn_code == "1" else "Failed",
        "TradeAmt": str(conn_txn["amount"]),
        "PaymentType": "Credit_CreditCard",
        "CustomField1": conn_txn["org_id"],
        "CustomField2": conn_txn["plan"],
    }
    params["CheckMacValue"] = check_mac_value(
        params, billing.SANDBOX_HASH_KEY, billing.SANDBOX_HASH_IV
    )
    return params


def test_callback_valid_activates_plan(client):
    c, conn = client
    # 先 checkout 產生 pending 交易
    c.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=_tok("operator", "acme"))
    txn = next(iter(conn.txns.values()))
    # 綠界回調:付款成功
    r = c.post("/api/v1/billing/callback", data=_callback_body(txn))
    assert r.status_code == 200 and r.text == "1|OK"
    # 交易轉 paid + org 方案啟用
    assert conn.txns[txn["trade_no"]]["status"] == "paid"
    assert conn.orgs["acme"]["plan"] == "pro" and conn.orgs["acme"]["status"] == "active"


def test_callback_bad_mac_rejected(client):
    c, conn = client
    c.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=_tok("operator", "acme"))
    txn = next(iter(conn.txns.values()))
    body = _callback_body(txn)
    body["CheckMacValue"] = "FORGED0000"  # 竄改章
    r = c.post("/api/v1/billing/callback", data=body)
    assert r.status_code == 400
    # 未啟用、交易仍 pending
    assert txn["trade_no"] in conn.txns and conn.txns[txn["trade_no"]]["status"] == "pending"
    assert "acme" not in conn.orgs


def test_callback_idempotent_on_resend(client):
    c, conn = client
    c.post("/api/v1/billing/checkout", json={"plan": "enterprise"}, headers=_tok("admin", "acme"))
    txn = next(iter(conn.txns.values()))
    body = _callback_body(txn)
    assert c.post("/api/v1/billing/callback", data=body).text == "1|OK"
    # 綠界重送:仍回 1|OK,但不重複處理(狀態已 paid)
    assert c.post("/api/v1/billing/callback", data=body).text == "1|OK"
    assert conn.txns[txn["trade_no"]]["status"] == "paid"


def test_callback_payment_failed_marks_failed(client):
    c, conn = client
    c.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=_tok("operator", "acme"))
    txn = next(iter(conn.txns.values()))
    r = c.post("/api/v1/billing/callback", data=_callback_body(txn, rtn_code="10100050"))
    assert r.status_code == 200 and r.text == "1|OK"
    assert conn.txns[txn["trade_no"]]["status"] == "failed"
    assert "acme" not in conn.orgs  # 付款失敗不啟用


# ---- subscription ----


def test_subscription_view(client):
    c, conn = client
    # 先建 org(admin)並跑一次完整結帳→回調
    conn.orgs["acme"] = {
        "org_id": "acme", "name": "Acme", "plan": "free", "status": "active",
        "max_devices": None, "max_fleets": None,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    c.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=_tok("operator", "acme"))
    txn = next(iter(conn.txns.values()))
    c.post("/api/v1/billing/callback", data=_callback_body(txn))
    r = c.get("/api/v1/billing/subscription", headers=_tok("viewer", "acme"))
    assert r.status_code == 200
    b = r.json()
    assert b["org_id"] == "acme" and b["plan"] == "pro" and b["status"] == "active"
    assert b["price"] == 3000 and b["sandbox"] is True
    assert len(b["recent_transactions"]) == 1
    assert b["recent_transactions"][0]["status"] == "paid"


def test_subscription_unknown_org_defaults_free(client):
    c, conn = client
    r = c.get("/api/v1/billing/subscription", headers=_tok("viewer", "ghost"))
    assert r.status_code == 200
    b = r.json()
    assert b["plan"] == "free" and b["price"] == 0 and b["recent_transactions"] == []


# ---- dev 模式(認證停用)----


def test_dev_mode_checkout_and_callback(monkeypatch):
    _clear_ecpay_env(monkeypatch)
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(limits, "write_limiter", RateLimiter(rate_per_min=6000))
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    c = TestClient(main.app)
    # dev = admin,org=default:可結帳(沙箱)
    r = c.post("/api/v1/billing/checkout", json={"plan": "pro"})
    assert r.status_code == 200 and r.json()["sandbox"] is True
    txn = next(iter(conn.txns.values()))
    assert c.post("/api/v1/billing/callback", data=_callback_body(txn)).text == "1|OK"
    assert conn.orgs["default"]["plan"] == "pro"
