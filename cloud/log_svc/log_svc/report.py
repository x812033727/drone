"""ULog 報告子程序執行與結果判讀(純邏輯與 I/O 分離,可單測)。

report_ok 判定沿用 tools/flight_ops/archive_flight.py 的準則:
ulog_report exit 0(無異常)與 1(有異常提示)都算「報告產出成功」,
只有腳本崩潰(stdout 無摘要標頭)或無法執行/逾時才算失敗——
失敗不擋落庫,report_ok=false 照記,供看板浮現壞檔。
"""

import asyncio
import os
import sys
from pathlib import Path

#: 報告工具路徑:容器內為 /app/tools/ulog_report.py(Dockerfile COPY 進來);
#: 本機直跑可用 ULOG_REPORT 環境變數指到 repo 的 tools/ulog_report.py
REPORT_SCRIPT = Path(
    os.environ.get("ULOG_REPORT", Path(__file__).resolve().parents[1] / "tools" / "ulog_report.py")
)

#: 報告輸出的摘要標頭;沒有它代表 ulog_report 崩潰(如非法 ULog)
REPORT_MARKER = "=== ULog 摘要"

#: flight_logs.report_excerpt 只留前 500 字(全文在 .report.txt)
EXCERPT_LEN = 500

#: 報告子程序逾時秒數(超大 ULog 防呆;逾時視為報告失敗)
REPORT_TIMEOUT_S = 300.0


def parse_report_output(stdout: str, stderr: str, returncode: int | None) -> tuple[bool, str]:
    """判讀 ulog_report 輸出:回傳 (report_ok, 報告全文)。

    報告全文 = stdout(+ stderr 附錄,若有);report_ok 見模組 docstring。
    """
    text = stdout
    if stderr:
        text += f"\n--- stderr ---\n{stderr}"
    ok = REPORT_MARKER in stdout
    if not ok and not text.strip():
        text = f"(ulog_report 無輸出,exit {returncode})\n"
    return ok, text


def excerpt(report_text: str, limit: int = EXCERPT_LEN) -> str:
    """報告摘要:前 limit 個字元(落 DB 供看板顯示;全文在 .report.txt)。"""
    return report_text[:limit]


async def run_report(ulog_path: Path, timeout_s: float = REPORT_TIMEOUT_S) -> tuple[bool, str]:
    """跑 tools/ulog_report.py 產報告,全文存同名 .report.txt;回傳 (report_ok, 全文)。

    任何失敗(崩潰/逾時/無法執行)不拋例外——report_ok=false + 錯誤說明照回傳,
    呼叫端照常落庫(報告失敗不擋回收)。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(REPORT_SCRIPT),
            str(ulog_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            ok, text = False, f"(ulog_report 逾時 {timeout_s:.0f} 秒,已終止)\n"
        else:
            ok, text = parse_report_output(
                out.decode("utf-8", errors="replace"),
                err.decode("utf-8", errors="replace"),
                proc.returncode,
            )
    except OSError as e:
        ok, text = False, f"(ulog_report 無法執行:{e})\n"

    report_path = ulog_path.with_name(ulog_path.name + ".report.txt")
    try:
        report_path.write_text(text, encoding="utf-8")
    except OSError:
        # 報告存檔失敗不影響落庫(DB 已有摘要)
        pass
    return ok, text
