"""report.py 單元測試:report_ok 判讀、摘要截斷、子程序執行(fake 腳本)。

不需 DB,也不需 docker。
"""

import asyncio
from pathlib import Path

from log_svc import report as report_mod
from log_svc.report import excerpt, parse_report_output, run_report


def test_parse_ok_exit0() -> None:
    ok, text = parse_report_output("=== ULog 摘要:x.ulg ===\n✓ 未觸發異常規則\n", "", 0)
    assert ok is True
    assert "未觸發異常規則" in text


def test_parse_ok_exit1_warnings_still_ok() -> None:
    """exit 1 = 有異常提示,報告仍算產出成功(沿用 archive_flight 準則)。"""
    ok, _ = parse_report_output("=== ULog 摘要:x.ulg ===\n⚠ 異常提示:\n", "", 1)
    assert ok is True


def test_parse_crash_no_marker_is_not_ok() -> None:
    ok, text = parse_report_output("", "Traceback ...\nValueError: bad header", 1)
    assert ok is False
    assert "Traceback" in text  # stderr 附錄保留供排查


def test_parse_no_output_at_all() -> None:
    ok, text = parse_report_output("", "", 2)
    assert ok is False
    assert "exit 2" in text


def test_excerpt_truncates_to_500() -> None:
    assert excerpt("x" * 900) == "x" * 500
    assert excerpt("短文") == "短文"


def _write_fake_report(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_report.py"
    script.write_text(body, encoding="utf-8")
    return script


def test_run_report_writes_report_txt_and_ok(tmp_path, monkeypatch) -> None:
    script = _write_fake_report(
        tmp_path, "import sys\nprint('=== ULog 摘要:fake ===')\nsys.exit(0)\n"
    )
    monkeypatch.setattr(report_mod, "REPORT_SCRIPT", script)
    ulog = tmp_path / "a.ulg"
    ulog.write_bytes(b"x")

    ok, text = asyncio.run(run_report(ulog))

    assert ok is True
    report_txt = tmp_path / "a.ulg.report.txt"
    assert report_txt.exists()
    assert "ULog 摘要" in report_txt.read_text(encoding="utf-8")
    assert "ULog 摘要" in text


def test_run_report_crash_is_not_ok_but_does_not_raise(tmp_path, monkeypatch) -> None:
    """報告崩潰不拋例外:report_ok=false + 錯誤內容照回傳(落庫不被擋)。"""
    script = _write_fake_report(tmp_path, "raise ValueError('bad ulog')\n")
    monkeypatch.setattr(report_mod, "REPORT_SCRIPT", script)
    ulog = tmp_path / "b.ulg"
    ulog.write_bytes(b"not a ulog")

    ok, text = asyncio.run(run_report(ulog))

    assert ok is False
    assert "bad ulog" in text
    assert (tmp_path / "b.ulg.report.txt").exists()


def test_run_report_timeout_is_not_ok(tmp_path, monkeypatch) -> None:
    script = _write_fake_report(tmp_path, "import time\ntime.sleep(30)\n")
    monkeypatch.setattr(report_mod, "REPORT_SCRIPT", script)
    ulog = tmp_path / "c.ulg"
    ulog.write_bytes(b"x")

    ok, text = asyncio.run(run_report(ulog, timeout_s=0.5))

    assert ok is False
    assert "逾時" in text
