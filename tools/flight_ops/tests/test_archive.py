"""archive_flight 單元測試:目錄結構、模板預填、報告失敗不擋歸檔(tmp_path,不需 SITL)。"""

import pytest
from flight_ops.archive_flight import archive, run_ulog_report, sortie_record_md


@pytest.fixture
def ulog(tmp_path):
    f = tmp_path / "07_31_22.ulg"
    f.write_bytes(b"ULog\x01not-a-real-log")
    return f


def fake_report_ok(ulog, out):
    out.write_text("=== ULog 摘要(fake) ===\n", encoding="utf-8")
    return True, ""


def test_archive_layout_and_contents(tmp_path, ulog, capsys):
    root = tmp_path / "flight-logs"
    dest = archive(
        ulog, "F05", "DEV-01", root, result="通過", date="2026-07-11",
        report_runner=fake_report_ok,
    )
    assert dest == root / "2026-07-11" / "F05-DEV-01"
    assert (dest / "07_31_22.ulg").read_bytes() == ulog.read_bytes()  # 保留原名
    assert (dest / "report.txt").is_file()

    record = (dest / "sortie-record.md").read_text(encoding="utf-8")
    assert "F05 / 2026-07-11 / DEV-01" in record  # 架次/日期/機號預填
    assert "07_31_22.ulg(本目錄)" in record  # ULog 檔名預填
    assert "| 結果 | 通過 |" in record  # --result 預填
    assert "風速實測(m/s):__" in record  # 天候留空待填
    assert "操手 / GCS / 觀察員 | __ / __ / __" in record

    out = capsys.readouterr().out
    assert "四件套 checklist" in out
    assert "[ ] 任務檔" in out  # 缺項提醒


def test_result_left_blank_when_not_given():
    record = sortie_record_md("F01", "DEV-02", "2026-07-12", "a.ulg", None)
    assert "通過 / 不通過(原因:__)/ 事故" in record


def test_report_failure_does_not_block_archive(tmp_path, ulog, capsys):
    def failing_report(u, out):
        out.write_text("(ulog_report 執行失敗:boom)\n", encoding="utf-8")
        return False, "ulog_report 執行失敗:boom"

    dest = archive(ulog, "F06", "DEV-01", tmp_path / "logs", report_runner=failing_report)
    assert (dest / "sortie-record.md").is_file()  # 歸檔照常完成
    assert (dest / "07_31_22.ulg").is_file()
    out = capsys.readouterr().out
    assert "(註)ulog_report 執行失敗:boom" in out
    assert "[x] ulog_report 報告" in out


def test_run_ulog_report_crash_marks_failure_but_writes_file(tmp_path, ulog):
    """真 subprocess:壞 ULog 讓 ulog_report 崩潰 → 回報失敗但輸出仍落檔。"""
    out = tmp_path / "report.txt"
    ok, note = run_ulog_report(ulog, out)
    assert not ok
    assert note  # 有附註
    assert out.is_file()


def test_archive_missing_ulog_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        archive(tmp_path / "nope.ulg", "F01", "DEV-01", tmp_path / "logs")
