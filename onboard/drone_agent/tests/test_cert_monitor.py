"""cert_monitor 純函式單元測試:憑證解析 / 剩餘天數 / 門檻 / 指紋 / 告警 JSON。

不需 SITL、不需 MQTT broker。憑證解析用預先產生的靜態測試憑證
(tests/fixtures/test_cert.pem,notAfter 固定為 2035-01-01 00:00:00 UTC),
解析走標準庫 ssl,測試本身不需 cryptography 套件。
"""

import json
from pathlib import Path

from drone_agent.cert_monitor import (
    cert_fingerprint,
    days_until_expiry,
    expiry_alert_json,
    read_cert_not_after,
    should_warn,
)

FIXTURE_CERT = str(Path(__file__).parent / "fixtures" / "test_cert.pem")
# fixtures/test_cert.pem 的 notAfter = 2035-01-01T00:00:00Z 之 epoch 秒
FIXTURE_NOT_AFTER_EPOCH = 2_051_222_400.0


# ---- read_cert_not_after(標準庫 ssl 解析,不需 TLS 連線)----


def test_read_cert_not_after_parses_fixture() -> None:
    assert read_cert_not_after(FIXTURE_CERT) == FIXTURE_NOT_AFTER_EPOCH


def test_read_cert_not_after_missing_file_returns_none() -> None:
    """讀不到憑證檔:回 None、不拋(監控盡力而為,不能炸掉主流程)。"""
    assert read_cert_not_after("/no/such/cert.pem") is None


def test_read_cert_not_after_garbage_returns_none(tmp_path) -> None:
    bad = tmp_path / "bad.pem"
    bad.write_text("not a certificate at all")
    assert read_cert_not_after(str(bad)) is None


# ---- days_until_expiry(純函式)----


def test_days_until_expiry_positive() -> None:
    not_after = 1_000_000.0 + 10 * 86400
    assert days_until_expiry(not_after, 1_000_000.0) == 10.0


def test_days_until_expiry_negative_when_expired() -> None:
    """已過期:剩餘天數為負(供告警把過期也涵蓋)。"""
    not_after = 1_000_000.0 - 3 * 86400
    assert days_until_expiry(not_after, 1_000_000.0) == -3.0


def test_days_until_expiry_zero_at_exact_moment() -> None:
    assert days_until_expiry(1_000_000.0, 1_000_000.0) == 0.0


# ---- should_warn(純函式,門檻邊界)----


def test_should_warn_above_threshold_is_false() -> None:
    assert should_warn(45.0, 30.0) is False


def test_should_warn_at_threshold_is_true() -> None:
    """恰好等於門檻即告警(<=)。"""
    assert should_warn(30.0, 30.0) is True


def test_should_warn_below_threshold_is_true() -> None:
    assert should_warn(5.0, 30.0) is True


def test_should_warn_expired_negative_is_true() -> None:
    assert should_warn(-2.0, 30.0) is True


# ---- cert_fingerprint(輪換偵測)----


def test_cert_fingerprint_is_stable_sha256_hex() -> None:
    fp1 = cert_fingerprint(FIXTURE_CERT)
    fp2 = cert_fingerprint(FIXTURE_CERT)
    assert fp1 == fp2
    assert isinstance(fp1, str)
    assert len(fp1) == 64  # SHA-256 十六進位
    int(fp1, 16)  # 全為十六進位字元


def test_cert_fingerprint_changes_on_content_change(tmp_path) -> None:
    p = tmp_path / "c.pem"
    p.write_bytes(b"AAAA")
    first = cert_fingerprint(str(p))
    p.write_bytes(b"BBBB")
    second = cert_fingerprint(str(p))
    assert first != second


def test_cert_fingerprint_missing_returns_none() -> None:
    assert cert_fingerprint("/no/such/cert.pem") is None


# ---- expiry_alert_json(純 JSON,非 proto,不動契約)----


def test_expiry_alert_json_fields_and_single_line() -> None:
    payload = expiry_alert_json(
        "qs-0001", days_remaining=12.345, not_after_epoch=1_752_000_000.0, now_unix_ms=1_700_000
    )
    assert "\n" not in payload
    obj = json.loads(payload)
    assert obj["drone_id"] == "qs-0001"
    assert obj["alert"] == "cert_expiring"
    assert obj["days_remaining"] == 12.35  # round(…, 2)
    assert obj["unix_time_ms"] == 1_700_000
    assert obj["not_after_unix_ms"] == 1_752_000_000_000
