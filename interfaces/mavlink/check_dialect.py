#!/usr/bin/env python3
"""自訂 dialect XML 靜態檢查(README「Phase 1 啟用條件 4」的 CI 守門)。

規則(對齊 README「version 規則」與 mavgen 驗證章):
- message ID 必須落在私有區段 24150–24199 且不重複
- 訊息名/欄位名唯一(欄位名以訊息為界)
- enum 名唯一;entry 名全域唯一(MAVLink 要求)
- bitmask enum 的 entry 值必須是 2 的冪且不重複
- dialect <version> 存在且為正整數

僅用標準庫;錯誤逐條列印,任何違規以 exit 1 結束。
輸入限定 repo 內版控的 dialect XML(CI 守門用),非不受信任來源;
若未來改吃外部輸入,改用 defusedxml 再解析。
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ID_MIN, ID_MAX = 24150, 24199


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def check_dialect(path: Path) -> list[str]:
    """回傳違規清單;空清單 = 通過。"""
    errors: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:  # XML 壞掉直接單條錯誤返回
        return [f"XML 解析失敗:{exc}"]

    version = root.findtext("version")
    if version is None or not version.strip().isdigit() or int(version) < 1:
        errors.append(f"<version> 缺失或非正整數:{version!r}")

    seen_msg_ids: dict[int, str] = {}
    seen_msg_names: set[str] = set()
    for msg in root.iter("message"):
        name = msg.get("name", "?")
        raw_id = msg.get("id", "")
        if name in seen_msg_names:
            errors.append(f"訊息名重複:{name}")
        seen_msg_names.add(name)

        if not raw_id.isdigit():
            errors.append(f"{name}: id 非整數:{raw_id!r}")
            continue
        mid = int(raw_id)
        if not ID_MIN <= mid <= ID_MAX:
            errors.append(f"{name}: id {mid} 超出私有區段 {ID_MIN}–{ID_MAX}")
        if mid in seen_msg_ids:
            errors.append(f"{name}: id {mid} 與 {seen_msg_ids[mid]} 重複")
        seen_msg_ids[mid] = name

        field_names: set[str] = set()
        for field in msg.iter("field"):
            fname = field.get("name", "?")
            if fname in field_names:
                errors.append(f"{name}: 欄位名重複:{fname}")
            field_names.add(fname)

    seen_enum_names: set[str] = set()
    seen_entry_names: set[str] = set()
    for enum in root.iter("enum"):
        ename = enum.get("name", "?")
        if ename in seen_enum_names:
            errors.append(f"enum 名重複:{ename}")
        seen_enum_names.add(ename)

        is_bitmask = enum.get("bitmask") == "true"
        seen_values: set[int] = set()
        for entry in enum.iter("entry"):
            entry_name = entry.get("name", "?")
            if entry_name in seen_entry_names:
                errors.append(f"{ename}: entry 名全域重複:{entry_name}")
            seen_entry_names.add(entry_name)

            raw_value = entry.get("value", "")
            if not raw_value.lstrip("-").isdigit():
                errors.append(f"{ename}.{entry_name}: value 非整數:{raw_value!r}")
                continue
            value = int(raw_value)
            if value in seen_values:
                errors.append(f"{ename}.{entry_name}: value {value} 重複")
            seen_values.add(value)
            if is_bitmask and not _is_power_of_two(value):
                errors.append(
                    f"{ename}.{entry_name}: bitmask entry 值 {value} 非 2 的冪"
                )

    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"用法:{argv[0]} <dialect.xml>", file=sys.stderr)
        return 2
    errors = check_dialect(Path(argv[1]))
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    if errors:
        return 1
    print("dialect 檢查通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
