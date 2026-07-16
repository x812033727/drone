#!/usr/bin/env python3
"""批次寫入 / 核對 PX4 參數(QGC .params 檔 → MAVSDK param plugin)。

對應 docs/50-project/phase0/build-and-first-flight.md:
- §3 失效保護參數表 v1 → params/dev-machine-v1.params(寫入後凍結,改動走差異記錄)
- §7 飛行日「圍欄與 RTL 高度參數核對」→ `--dry-run` 只讀現值比對,不寫入

用法(於 tools/ 目錄執行;--file 預設為套件內 dev-machine-v1.params):
    python -m flight_ops.apply_params --url udpin://0.0.0.0:14540
    python -m flight_ops.apply_params --dry-run
    python -m flight_ops.apply_params --file flight_ops/params/dev-machine-v1.params

結果:逐項輸出 參數/寫入值/回讀值/OK-DIFF 表格;全 OK → exit 0,任一 DIFF → exit 1。
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 執行期延遲匯入(connect 內):parse_params_file 的消費端
    from mavsdk import System  # (firmware 煙霧)不需要 mavsdk/grpc 重依賴

#: 套件內建參數檔(--file 預設值)
DEFAULT_PARAMS_FILE = Path(__file__).resolve().parent / "params" / "dev-machine-v1.params"

#: MAV_PARAM_TYPE 數字 → 本工具型別名(QGC .params 第 5 欄)
MAV_PARAM_TYPES = {6: "INT32", 9: "REAL32"}

#: REAL32 回讀比對容差(float32 量化誤差遠小於此)
FLOAT_TOLERANCE = 1e-4


@dataclass(frozen=True)
class Param:
    """一筆 .params 檔參數:名稱、期望值、型別("INT32" / "REAL32")。"""

    name: str
    value: float
    ptype: str


@dataclass(frozen=True)
class Row:
    """一筆寫入/核對結果:期望值、回讀值與是否一致。"""

    param: Param
    readback: float
    ok: bool


def parse_params_file(path: Path) -> list[Param]:
    """解析 QGC 標準 .params 檔(tab 分隔 5 欄;容忍 # 註解與空行,壞行 raise)。"""
    params: list[Param] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 5:
            raise ValueError(f"{path}:{lineno}: 欄位數 {len(fields)} != 5(tab 分隔):{raw!r}")
        _vid, _cid, name, value_s, type_s = (f.strip() for f in fields)
        try:
            type_code = int(type_s)
        except ValueError as e:
            raise ValueError(f"{path}:{lineno}: type 欄非整數:{type_s!r}") from e
        ptype = MAV_PARAM_TYPES.get(type_code)
        if ptype is None:
            raise ValueError(
                f"{path}:{lineno}: 不支援的 MAV_PARAM_TYPE {type_code}(僅 6=INT32、9=REAL32)"
            )
        try:
            value = int(value_s) if ptype == "INT32" else float(value_s)
        except ValueError as e:
            raise ValueError(f"{path}:{lineno}: value 欄與型別 {ptype} 不符:{value_s!r}") from e
        params.append(Param(name=name, value=float(value), ptype=ptype))
    if not params:
        raise ValueError(f"{path}: 無任何參數行")
    return params


def value_ok(expected: float, actual: float, ptype: str, tol: float = FLOAT_TOLERANCE) -> bool:
    """期望值/回讀值比對:INT32 精確相等,REAL32 容差 tol。"""
    if ptype == "INT32":
        return int(round(actual)) == int(round(expected))
    return abs(actual - expected) <= tol


async def apply_and_verify(param_plugin, params: list[Param], *, dry_run: bool) -> list[Row]:
    """逐項 set(dry_run 跳過)→ 回讀 → 比對;param_plugin 為 MAVSDK 的 drone.param。"""
    rows: list[Row] = []
    for p in params:
        if not dry_run:
            if p.ptype == "INT32":
                await param_plugin.set_param_int(p.name, int(p.value))
            else:
                await param_plugin.set_param_float(p.name, p.value)
        if p.ptype == "INT32":
            readback = float(await param_plugin.get_param_int(p.name))
        else:
            readback = float(await param_plugin.get_param_float(p.name))
        rows.append(Row(param=p, readback=readback, ok=value_ok(p.value, readback, p.ptype)))
    return rows


def format_value(value: float, ptype: str) -> str:
    return str(int(round(value))) if ptype == "INT32" else f"{value:g}"


def print_table(rows: list[Row], *, dry_run: bool) -> None:
    written_hdr = "期望值" if dry_run else "寫入值"
    header = f"{'參數':<20} {'型別':<7} {written_hdr:>8} {'回讀值':>8}  結果"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r.param.name:<20} {r.param.ptype:<7} "
            f"{format_value(r.param.value, r.param.ptype):>8} "
            f"{format_value(r.readback, r.param.ptype):>8}  {'OK' if r.ok else 'DIFF'}"
        )
    n_diff = sum(1 for r in rows if not r.ok)
    print("-" * len(header))
    print(f"共 {len(rows)} 項,OK {len(rows) - n_diff}、DIFF {n_diff}")


async def connect(url: str, grpc_port: int, timeout_s: float = 60.0) -> "System":
    from mavsdk import System  # 延遲匯入:僅寫入/核對飛控時需要

    drone = System(port=grpc_port)
    print(f"連線中:{url}(gRPC {grpc_port})", flush=True)

    async def _wait() -> None:
        await drone.connect(system_address=url)
        async for state in drone.core.connection_state():
            if state.is_connected:
                return

    await asyncio.wait_for(_wait(), timeout=timeout_s)
    print("已連線", flush=True)
    return drone


async def run(args: argparse.Namespace) -> int:
    params = parse_params_file(Path(args.file))
    drone = await connect(args.url, args.grpc_port)
    rows = await apply_and_verify(drone.param, params, dry_run=args.dry_run)
    mode = "核對(--dry-run,未寫入)" if args.dry_run else "寫入+回讀"
    print(f"\n=== 參數{mode}:{args.file} ===")
    print_table(rows, dry_run=args.dry_run)
    return 0 if all(r.ok for r in rows) else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--file",
        default=str(DEFAULT_PARAMS_FILE),
        help=f"QGC .params 參數檔(預設 {DEFAULT_PARAMS_FILE.name})",
    )
    parser.add_argument("--url", default="udpin://0.0.0.0:14540", help="MAVSDK 連線 URL")
    parser.add_argument(
        "--grpc-port", type=int, default=50610, help="mavsdk_server gRPC 埠(多實例錯開)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只讀現值比對不寫入(飛行日參數核對)"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
