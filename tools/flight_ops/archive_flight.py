#!/usr/bin/env python3
"""飛行後 ULog 歸檔:建目錄、拷 ULog、跑 ulog_report、生成架次紀錄底稿。

對應 docs/50-project/phase0/flight-test-plan.md:
- §1 每架次必附四件套(任務檔、ULog、ulog_report 報告、飛測簡報紀錄)——缺一不計數
- §3 架次紀錄模板 → sortie-record.md(可預填欄位已填,其餘留空待飛測簡報補齊)

用法(於 tools/ 目錄執行):
    python -m flight_ops.archive_flight --ulog <path>.ulg --sortie F05 --drone DEV-01 \
        [--root flight-logs] [--result 通過|不通過|事故] [--date YYYY-MM-DD]

歸檔結構:{root}/{YYYY-MM-DD}/{sortie}-{drone}/(ULog 保留原檔名 + report.txt +
sortie-record.md)。ulog_report 失敗不擋歸檔,記註後照常完成。
"""

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

#: 既有報告工具(tools/ulog_report.py),subprocess 呼叫沿用其 CLI
ULOG_REPORT = Path(__file__).resolve().parents[1] / "ulog_report.py"

#: flight-test-plan.md §3 模板連結(寫入 sortie-record.md 供追溯)
TEMPLATE_REF = "docs/50-project/phase0/flight-test-plan.md §3"


def run_ulog_report(ulog: Path, out: Path) -> tuple[bool, str]:
    """跑 tools/ulog_report.py 並把輸出存 out;回傳 (是否產出可用報告, 附註)。

    ulog_report exit 0=無異常、1=有異常提示,兩者都算「報告產出成功」;
    只有腳本崩潰(無摘要輸出)或無法執行才視為失敗——失敗不擋歸檔。
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(ULOG_REPORT), str(ulog)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        out.write_text(f"(ulog_report 執行失敗:{e})\n", encoding="utf-8")
        return False, f"ulog_report 執行失敗:{e}"
    text = proc.stdout
    if proc.stderr:
        text += f"\n--- stderr ---\n{proc.stderr}"
    out.write_text(text, encoding="utf-8")
    if "=== ULog 摘要" not in proc.stdout:
        return False, f"ulog_report 崩潰(exit {proc.returncode}),輸出已存 {out.name} 供排查"
    if proc.returncode == 1:
        return True, "ulog_report 有異常提示(見 report.txt),記得開異常追蹤單"
    return True, ""


def sortie_record_md(
    sortie: str, drone: str, date: str, ulog_name: str, result: str | None
) -> str:
    """依 flight-test-plan §3 模板生成架次紀錄;可預填欄位已填,其餘留空待填。"""
    result_cell = result if result else "通過 / 不通過(原因:__)/ 事故"
    return f"""# 架次紀錄 {sortie} / {drone} / {date}

> 依 [{TEMPLATE_REF}] 模板生成;空欄請於飛測簡報時補齊並簽名(缺一不計數)。

| 欄位 | 內容 |
|------|------|
| 架次編號 / 日期 / 機號 | {sortie} / {date} / {drone} |
| 天候 | 風速實測(m/s):__ / 溫度:__ / 天況:__ |
| 任務檔 / 參數表版本 | __(檔名 + hash)/ v__ |
| ULog 檔名 | {ulog_name}(本目錄) |
| 結果 | {result_cell} |
| 異常單 | __(無異常填「無」) |
| 操手 / GCS / 觀察員 | __ / __ / __ |
"""


def archive(
    ulog: Path,
    sortie: str,
    drone: str,
    root: Path,
    result: str | None = None,
    date: str | None = None,
    report_runner=run_ulog_report,
) -> Path:
    """執行歸檔,回傳歸檔目錄。report_runner 可注入(測試用)。"""
    if not ulog.is_file():
        raise FileNotFoundError(f"找不到 ULog:{ulog}")
    date = date or dt.date.today().isoformat()
    dest = root / date / f"{sortie}-{drone}"
    dest.mkdir(parents=True, exist_ok=True)

    dest_ulog = dest / ulog.name
    shutil.copy2(ulog, dest_ulog)

    report_path = dest / "report.txt"
    report_ok, note = report_runner(dest_ulog, report_path)

    record_path = dest / "sortie-record.md"
    record_path.write_text(
        sortie_record_md(sortie, drone, date, ulog.name, result), encoding="utf-8"
    )

    print(f"=== 歸檔完成:{dest} ===")
    if note:
        print(f"(註){note}")
    print("四件套 checklist(flight-test-plan §1:缺一不計數):")
    print(f"  [v] ULog:{dest_ulog.name}")
    print(f"  [{'v' if report_ok else 'x'}] ulog_report 報告:report.txt"
          + ("" if report_ok else "(產出失敗,請人工重跑)"))
    print("  [ ] 任務檔:請拷入本目錄,檔名 + hash 記入 sortie-record.md")
    print("  [ ] 飛測簡報紀錄:sortie-record.md 空欄補齊並簽名")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ulog", required=True, help="ULog 檔路徑(.ulg)")
    parser.add_argument("--sortie", required=True, help="架次編號(如 F05)")
    parser.add_argument("--drone", required=True, help="機號(如 DEV-01)")
    parser.add_argument("--root", default="flight-logs", help="歸檔根目錄(預設 flight-logs)")
    parser.add_argument(
        "--result", choices=["通過", "不通過", "事故"], help="架次結果(可留待簡報再填)"
    )
    parser.add_argument("--date", help="飛行日期 YYYY-MM-DD(預設今日)")
    args = parser.parse_args()
    archive(
        ulog=Path(args.ulog),
        sortie=args.sortie,
        drone=args.drone,
        root=Path(args.root),
        result=args.result,
        date=args.date,
    )


if __name__ == "__main__":
    main()
