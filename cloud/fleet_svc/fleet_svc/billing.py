"""訂閱金流(綠界 ECPay)控制面。純函式 + 設定,不碰 DB。

接續 #118(fleet.org 的 plan/status 控制面)與 #115(usage_counter 計量):
本模組把「方案」從 admin 手動設定,升級為**可自助結帳付費啟用**。不新增獨立服務,
金流控制面內嵌 fleet-svc(避免 helm/compose/release 全套 infra 擴張)。

金流流程:
  1. operator/admin 為自己 org 發起 POST /billing/checkout(指定 plan)。
  2. 本模組產生綠界 AioCheckOut 表單參數(含 CheckMacValue),前端 auto-submit 導向綠界。
  3. 使用者於綠界完成付款;綠界 server 以 POST 回調 /billing/callback。
  4. 回調**驗 CheckMacValue**(HashKey/HashIV),成功則啟用該 org 方案(plan+status=active),
     並落一筆 billing_transaction。回綠界要求的純文字 `1|OK`。

CheckMacValue(綠界規範,SHA256,零外部依賴):
  參數依鍵名 A→Z 排序 → 前綴 HashKey= 後綴 &HashIV= → urlencode → 轉小寫
  → .NET HttpUtility.UrlEncode 相容字元還原 → SHA256 → 轉大寫。
  以綠界官方文件測試向量驗證(見 tests/test_billing.py)。

憑證(env;未設=沙箱模式,用綠界公開測試參數,不影響 cloud-smoke):
  ECPAY_MERCHANT_ID / ECPAY_HASH_KEY / ECPAY_HASH_IV  金流商店代號與雜湊金鑰(必填才走正式)
  ECPAY_RETURN_URL         綠界 server 回調本服務 /billing/callback 的公開 URL
  ECPAY_CLIENT_BACK_URL    使用者付款後返回的前端 URL(可選)
  ECPAY_STAGE              "true" 時即使有正式憑證仍打綠界測試環境(預設 false)
  ECPAY_PRICE_PRO / ECPAY_PRICE_ENTERPRISE  各方案月費(TWD,可覆寫預設)
**絕不硬編正式憑證**——沙箱用的是綠界官方公開的測試商店代號/金鑰(全網公開,非機敏)。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote_plus

# ---- 綠界 AioCheckOut 端點 ----
ECPAY_ACTION_PROD = "https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5"
ECPAY_ACTION_STAGE = "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5"

# 綠界官方「公開」測試商店(全網文件公開,非機敏、非正式憑證):未設 env 時的沙箱預設。
SANDBOX_MERCHANT_ID = "2000132"
SANDBOX_HASH_KEY = "5294y06JbISpM5x9"
SANDBOX_HASH_IV = "v77hoKGq4kWxNNIS"

# .NET HttpUtility.UrlEncode 與 Python quote_plus 的差異字元:綠界規範要求還原這些
# (Python 會把 !*()編碼,.NET 不會;-_. 兩者皆不編碼故為 no-op,列全以符合官方順序)。
_DOTNET_UNRESERVED = (
    ("%2d", "-"), ("%5f", "_"), ("%2e", "."), ("%21", "!"),
    ("%2a", "*"), ("%28", "("), ("%29", ")"),
)

# 方案月費(TWD)預設;free 恆為 0(不可結帳)。env 覆寫見 plan_price()。
_PLAN_PRICE_DEFAULT: dict[str, int] = {"free": 0, "pro": 3000, "enterprise": 30000}


def _env(name: str) -> str | None:
    """讀取環境變數;空字串(compose ${VAR:-})視為未設 → None。"""
    v = os.environ.get(name)
    return v if (v and v.strip()) else None


@dataclass(frozen=True)
class EcpayConfig:
    """一次請求解析出的綠界設定。sandbox=True 表示走測試商店/測試環境。"""

    merchant_id: str
    hash_key: str
    hash_iv: str
    action_url: str
    return_url: str
    client_back_url: str | None
    sandbox: bool


def load_config() -> EcpayConfig:
    """從 env 解析綠界設定。三個憑證缺任一 → 沙箱模式(綠界公開測試參數 + 測試環境)。

    正式模式亦可用 ECPAY_STAGE=true 強制打測試環境(用正式商店代號在 stage 測試)。
    """
    mid = _env("ECPAY_MERCHANT_ID")
    key = _env("ECPAY_HASH_KEY")
    iv = _env("ECPAY_HASH_IV")
    configured = bool(mid and key and iv)
    sandbox = not configured
    stage = sandbox or (_env("ECPAY_STAGE") or "").lower() == "true"
    return EcpayConfig(
        merchant_id=mid or SANDBOX_MERCHANT_ID,
        hash_key=key or SANDBOX_HASH_KEY,
        hash_iv=iv or SANDBOX_HASH_IV,
        action_url=ECPAY_ACTION_STAGE if stage else ECPAY_ACTION_PROD,
        # 沙箱/dev 給一個明確可辨識的預設,正式部署務必設為公開可達的回調 URL。
        return_url=_env("ECPAY_RETURN_URL") or "http://localhost:8000/api/v1/billing/callback",
        client_back_url=_env("ECPAY_CLIENT_BACK_URL"),
        sandbox=sandbox,
    )


def plan_price(plan: str) -> int:
    """方案月費(TWD)。env(ECPAY_PRICE_PRO/ECPAY_PRICE_ENTERPRISE)覆寫;free 恆 0。"""
    if plan == "pro":
        raw = _env("ECPAY_PRICE_PRO")
    elif plan == "enterprise":
        raw = _env("ECPAY_PRICE_ENTERPRISE")
    else:
        raw = None
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return _PLAN_PRICE_DEFAULT.get(plan, 0)


def check_mac_value(params: dict[str, str], hash_key: str, hash_iv: str) -> str:
    """依綠界規範(SHA256)計算 CheckMacValue。純函式,零外部依賴。

    步驟(對綠界「檢查碼機制」文件):
      1. 參數(不含 CheckMacValue)依鍵名不分大小寫 A→Z 排序,以 & 串成 k=v。
      2. 前綴 `HashKey=<key>&`,後綴 `&HashIV=<iv>`。
      3. 整串以 URL encode(空白→+),轉小寫。
      4. 還原 .NET HttpUtility.UrlEncode 不編碼的字元(-_.!*()),與 .NET 一致。
      5. SHA256 取十六進位,轉大寫。
    """
    ordered = sorted(
        ((k, v) for k, v in params.items() if k != "CheckMacValue"),
        key=lambda kv: kv[0].lower(),
    )
    raw = (
        f"HashKey={hash_key}&"
        + "&".join(f"{k}={v}" for k, v in ordered)
        + f"&HashIV={hash_iv}"
    )
    encoded = quote_plus(raw).lower()
    for enc, dec in _DOTNET_UNRESERVED:
        encoded = encoded.replace(enc, dec)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()


def new_trade_no(prefix: str = "SUB") -> str:
    """產生綠界 MerchantTradeNo(唯一、僅英數、≤20 字元)。

    prefix(3) + UTC 時戳 YYYYMMDDHHMMSS(14) + 3 位隨機十六進位 = 20 字元。
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = secrets.token_hex(2)[:3]
    return f"{prefix}{ts}{rand}"[:20]


def build_checkout_params(
    cfg: EcpayConfig,
    *,
    org_id: str,
    plan: str,
    amount: int,
    trade_no: str,
    trade_date: str | None = None,
) -> dict[str, str]:
    """組出綠界 AioCheckOut 表單參數(含 CheckMacValue),供前端 auto-submit 導向結帳頁。

    org_id / plan 放 CustomField1 / CustomField2 隨單帶回:回調驗章後即可信任據以啟用方案
    (攻擊者無 HashKey/HashIV,無法偽造合法 CheckMacValue,故回傳的 CustomField 可信)。
    """
    date_str = trade_date or datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S")
    params: dict[str, str] = {
        "MerchantID": cfg.merchant_id,
        "MerchantTradeNo": trade_no,
        "MerchantTradeDate": date_str,
        "PaymentType": "aio",
        "TotalAmount": str(amount),
        "TradeDesc": f"drone platform {plan} subscription",
        "ItemName": f"Drone Platform {plan.capitalize()} Plan (monthly)",
        "ReturnURL": cfg.return_url,
        "ChoosePayment": "ALL",
        "EncryptType": "1",
        "CustomField1": org_id,
        "CustomField2": plan,
    }
    if cfg.client_back_url:
        params["ClientBackURL"] = cfg.client_back_url
    params["CheckMacValue"] = check_mac_value(params, cfg.hash_key, cfg.hash_iv)
    return params


def verify_callback(params: dict[str, str], cfg: EcpayConfig) -> bool:
    """驗綠界回調的 CheckMacValue。缺章或不符回 False(常數時間比較)。"""
    received = params.get("CheckMacValue")
    if not received:
        return False
    expected = check_mac_value(params, cfg.hash_key, cfg.hash_iv)
    return hmac.compare_digest(received.upper(), expected)
