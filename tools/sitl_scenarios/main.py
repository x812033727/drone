"""sitl_scenarios CLI:對 PX4 SITL 跑 F09–F12 失效保護回歸場景。

用法(於 tools/ 目錄下,SITL 容器已啟動且 EKF/GPS lock):
    python -m sitl_scenarios --scenario f10 --url udpin://0.0.0.0:14540 --container px4-sitl
    python -m sitl_scenarios --all --container px4-sitl

--all 依序跑全部場景;場景會改參數/耗電/觸發失效保護,每場景之間的 SITL 重啟由
外部負責(CI 為每場景獨立容器)——單一容器連跑僅供開發便利,不保證狀態乾淨。
場景細節(注入法/通過準則/與試飛計畫的語義差異)見各 scenarios/*.py docstring 與 README。
"""

import argparse
import asyncio
import importlib
import sys

from sitl_scenarios.runner import ScenarioConfig, ScenarioError, print_result

SCENARIO_MODULES = {
    "f09": "sitl_scenarios.scenarios.f09_link_loss",
    "f10": "sitl_scenarios.scenarios.f10_low_battery",
    "f11": "sitl_scenarios.scenarios.f11_geofence",
    "f12": "sitl_scenarios.scenarios.f12_gps_degraded",
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", choices=sorted(SCENARIO_MODULES), help="跑單一場景")
    group.add_argument("--all", action="store_true", help="依序跑全部場景(SITL 重啟自理)")
    parser.add_argument(
        "--url",
        default="udpin://0.0.0.0:14540",
        help="MAVSDK 連線字串(預設 SITL:udpin://0.0.0.0:14540;此映像主動送 MAVLink"
        " 到 host,監聽即可,不需埠映射)",
    )
    parser.add_argument(
        "--container",
        default=None,
        help="SITL 容器名(F10 必要:docker exec px4-listener/px4-param;"
        "F09 必要:docker inspect 取源 IP 過濾)",
    )
    parser.add_argument(
        "--source-ip",
        default=None,
        help="F09 被動觀測(14550)的源 IP 過濾;未給則由 --container docker inspect 推導",
    )
    parser.add_argument(
        "--grpc-port",
        type=int,
        default=50600,
        help="mavsdk_server gRPC 基準埠(預設 50600;--all 時每場景 +1 避免相撞)",
    )
    args = parser.parse_args(argv)

    selected = sorted(SCENARIO_MODULES) if args.all else [args.scenario]
    failures = 0
    for i, name in enumerate(selected):
        module = importlib.import_module(SCENARIO_MODULES[name])
        cfg = ScenarioConfig(
            url=args.url,
            container=args.container,
            source_ip=args.source_ip,
            grpc_port=args.grpc_port + i,
        )
        print(f"\n########## {module.TITLE} ##########", flush=True)
        try:
            result = asyncio.run(module.run(cfg))
        except NotImplementedError as e:
            # 探測判定不可行的場景走此路(現四場景皆可行;保留誠實出口)
            print(f"RESULT: NOT-IMPLEMENTED scenario={name} 原因:{e}", flush=True)
            failures += 1
            continue
        except ScenarioError as e:
            print(f"場景環境錯誤:{e}", flush=True)
            print(f"RESULT: FAIL scenario={name}", flush=True)
            failures += 1
            continue
        print_result(result)
        if not result.passed:
            failures += 1
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
