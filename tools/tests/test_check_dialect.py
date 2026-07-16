"""interfaces/mavlink/check_dialect.py 的守門邏輯測試。

真實 drone_custom.xml 必須通過;各違規類型以合成 XML 逐一驗證會被抓到。
checker 位於 interfaces/(非 tools/),本檔自行加 path。
"""

from __future__ import annotations

import sys
from pathlib import Path

_MAVLINK_DIR = Path(__file__).resolve().parents[2] / "interfaces" / "mavlink"
sys.path.insert(0, str(_MAVLINK_DIR))

from check_dialect import check_dialect  # noqa: E402

REAL_XML = _MAVLINK_DIR / "drone_custom.xml"


def _write(tmp_path, body: str) -> Path:
    p = tmp_path / "dialect.xml"
    p.write_text(
        f'<?xml version="1.0"?>\n<mavlink><version>1</version>{body}</mavlink>',
        encoding="utf-8",
    )
    return p


def test_real_dialect_passes():
    assert check_dialect(REAL_XML) == []


def test_id_out_of_range(tmp_path):
    xml = _write(
        tmp_path,
        '<messages><message id="24200" name="M1">'
        '<field type="uint8_t" name="a">x</field></message></messages>',
    )
    errors = check_dialect(xml)
    assert any("超出私有區段" in e for e in errors)


def test_duplicate_message_id(tmp_path):
    xml = _write(
        tmp_path,
        '<messages>'
        '<message id="24150" name="M1"><field type="uint8_t" name="a">x</field></message>'
        '<message id="24150" name="M2"><field type="uint8_t" name="a">x</field></message>'
        "</messages>",
    )
    errors = check_dialect(xml)
    assert any("重複" in e and "24150" in e for e in errors)


def test_duplicate_field_name(tmp_path):
    xml = _write(
        tmp_path,
        '<messages><message id="24151" name="M1">'
        '<field type="uint8_t" name="a">x</field>'
        '<field type="uint8_t" name="a">y</field>'
        "</message></messages>",
    )
    errors = check_dialect(xml)
    assert any("欄位名重複" in e for e in errors)


def test_bitmask_not_power_of_two(tmp_path):
    xml = _write(
        tmp_path,
        '<enums><enum name="E1" bitmask="true">'
        '<entry value="3" name="E1_BAD"><description>x</description></entry>'
        "</enum></enums>",
    )
    errors = check_dialect(xml)
    assert any("非 2 的冪" in e for e in errors)


def test_duplicate_entry_name_across_enums(tmp_path):
    xml = _write(
        tmp_path,
        '<enums>'
        '<enum name="E1"><entry value="0" name="DUP"><description>x</description></entry></enum>'
        '<enum name="E2"><entry value="0" name="DUP"><description>x</description></entry></enum>'
        "</enums>",
    )
    errors = check_dialect(xml)
    assert any("entry 名全域重複" in e for e in errors)


def test_missing_version(tmp_path):
    p = tmp_path / "dialect.xml"
    p.write_text('<?xml version="1.0"?>\n<mavlink></mavlink>', encoding="utf-8")
    errors = check_dialect(p)
    assert any("<version>" in e for e in errors)
