#!/usr/bin/env python3
"""ULog 飛行日誌摘要工具:每次飛行後產出健康摘要,異常提前浮現。

分析項目:飛行時間、最大高度/速度、電池電壓窗、GPS 品質、振動水準。
這是 docs/20-software/cloud-fleet.md 中 log-svc 異常規則的雛形,
Phase 0 先以 CLI 形式在每個飛行日結束時人工執行。

用法:
    python ulog_report.py flight.ulg

依賴:pip install -r requirements.txt(pyulog, numpy)
"""

import argparse
import sys

import numpy as np
from pyulog import ULog

# 異常門檻(依 docs/01-requirements.md 與 PX4 社群經驗值,隨機隊數據修正)
VIBRATION_WARN_MS2 = 30.0   # 加速度計高頻振動 RMS 警告值
VOLTAGE_SAG_WARN = 3.2      # 單芯最低電壓警告(V/cell)


def dataset(ulog: ULog, name: str):
    try:
        return ulog.get_dataset(name)
    except (KeyError, IndexError, ValueError):
        return None


def report(path: str) -> int:
    ulog = ULog(path)
    warnings: list[str] = []

    duration_s = (ulog.last_timestamp - ulog.start_timestamp) / 1e6
    print(f"=== ULog 摘要:{path} ===")
    print(f"記錄長度:{duration_s / 60:.1f} 分鐘")

    # 高度與速度(NED 本地座標,z 向下)
    lpos = dataset(ulog, "vehicle_local_position")
    if lpos:
        alt = -lpos.data["z"]
        vel = np.sqrt(
            lpos.data["vx"] ** 2 + lpos.data["vy"] ** 2 + lpos.data["vz"] ** 2
        )
        print(f"最大相對高度:{alt.max():.1f} m;最大速度:{vel.max():.1f} m/s")

    # 電池
    batt = dataset(ulog, "battery_status")
    if batt:
        v = batt.data["voltage_v"]
        v = v[v > 1.0]  # 去除未上電雜訊
        if v.size:
            cells = int(batt.data["cell_count"].max()) or 1
            vmin_cell = v.min() / cells
            print(
                f"電池:{v.max():.1f} → {v.min():.1f} V"
                f"({cells}S,最低 {vmin_cell:.2f} V/cell)"
            )
            if vmin_cell < VOLTAGE_SAG_WARN:
                warnings.append(
                    f"單芯最低電壓 {vmin_cell:.2f} V 低於 {VOLTAGE_SAG_WARN} V,"
                    "檢查電池健康度或降低負載"
                )

    # GPS 品質
    gps = dataset(ulog, "vehicle_gps_position")
    if gps:
        nsats = gps.data["satellites_used"]
        fix = gps.data["fix_type"]
        print(
            f"GPS:平均衛星數 {nsats.mean():.0f},"
            f"fix_type≥3 佔比 {(fix >= 3).mean() * 100:.0f}%"
        )
        if (fix >= 3).mean() < 0.95:
            warnings.append("GPS 3D fix 佔比低於 95%,檢查天線佈局或干擾")

    # 振動(加速度計高通後 RMS;槳/馬達/結構問題的第一指標)
    imu = dataset(ulog, "sensor_combined")
    if imu:
        acc = np.column_stack(
            [imu.data[f"accelerometer_m_s2[{i}]"] for i in range(3)]
        )
        acc_hp = acc - np.apply_along_axis(
            lambda a: np.convolve(a, np.ones(50) / 50, mode="same"), 0, acc
        )
        vib_rms = float(np.sqrt((acc_hp**2).sum(axis=1)).std())
        print(f"振動指標(高頻 RMS):{vib_rms:.1f} m/s²")
        if vib_rms > VIBRATION_WARN_MS2:
            warnings.append(
                f"振動 {vib_rms:.1f} m/s² 超過 {VIBRATION_WARN_MS2},"
                "檢查槳平衡、馬達軸承、隔震"
            )

    # 韌體端訊息(錯誤/警告等級)
    logged = [
        m for m in ulog.logged_messages if m.log_level_str() in ("ERROR", "WARNING")
    ]
    if logged:
        print(f"\n飛控訊息(WARNING/ERROR,共 {len(logged)} 則,前 10 則):")
        for m in logged[:10]:
            print(f"  [{m.log_level_str()}] {m.message}")

    print()
    if warnings:
        print("⚠ 異常提示:")
        for w in warnings:
            print(f"  - {w}")
        return 1
    print("✓ 未觸發異常規則")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ulog", help="ULog 檔路徑(.ulg)")
    args = parser.parse_args()
    sys.exit(report(args.ulog))


if __name__ == "__main__":
    main()
