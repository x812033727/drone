"""main.py 純函式測試:drone_id 路徑把關與存檔名。端到端 API 行為由 cloud-smoke CI 覆蓋。"""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from log_svc.main import stored_name, validate_drone_id

FIXED = datetime(2026, 7, 11, 3, 4, 5, tzinfo=timezone.utc)


def test_stored_name_prefixes_utc_timestamp() -> None:
    assert stored_name("flight.ulg", FIXED) == "20260711T030405Z_flight.ulg"


def test_stored_name_strips_path_components() -> None:
    assert stored_name("../../etc/passwd", FIXED) == "20260711T030405Z_passwd"


def test_stored_name_empty_falls_back() -> None:
    assert stored_name(None, FIXED) == "20260711T030405Z_unnamed.ulg"


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "../x"])
def test_validate_drone_id_rejects_path_escape(bad: str) -> None:
    with pytest.raises(HTTPException):
        validate_drone_id(bad)


def test_validate_drone_id_accepts_normal() -> None:
    validate_drone_id("qs-0001")  # 不拋即通過
