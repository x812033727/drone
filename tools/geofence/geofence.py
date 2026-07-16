#!/usr/bin/env python3
"""禁航區 GeoJSON → PX4 圍欄轉換器(韌體軌 F7;firmware.md §2 GeoFence 客製項)。

輸入:GeoJSON FeatureCollection——
- Polygon / MultiPolygon:禁航區(→ PX4 **exclusion** 多邊形圍欄);
  properties.inclusion=true 時轉 inclusion(作業範圍框)
- Point + properties.radius_m:圓形禁航區(→ exclusion circle)

輸出兩種目標:
- ``to_fence_items()``:MAV_CMD_NAV_FENCE_* 項目序列(MISSION_TYPE_FENCE 上傳用,
  座標 int 1e7;pymavlink 上傳/回讀見 firmware 軌 F8)
- ``to_qgc_geofence()``:QGC ``.plan`` 的 geoFence 區塊(操作人可視化/編輯)

容量規劃(firmware.md 口徑:≥32 多邊形 / 128 頂點級,rev A 實測定容):
``budget_report()`` 檢查;超限可用 ``simplify_polygon()``(Douglas-Peucker,
經緯度平面近似——禁航區屬公里級小範圍,球面誤差可忽略)壓頂點後重驗。

只用標準庫。GeoJSON 慣例:座標 [lon, lat];環首尾重複頂點會去重。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# MAVLink 圍欄命令(common.xml)
MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION = 5001
MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION = 5002
MAV_CMD_NAV_FENCE_CIRCLE_INCLUSION = 5003
MAV_CMD_NAV_FENCE_CIRCLE_EXCLUSION = 5004
MAV_FRAME_GLOBAL = 0
MAV_MISSION_TYPE_FENCE = 1

# firmware.md §2 設計口徑(SITL 代理量測見 F8;實機容量 rev A 定容)
BUDGET_MAX_POLYGONS = 32
BUDGET_MAX_VERTICES = 128


class Circle:
    """圓形圍欄(lat/lon 度、半徑公尺)。"""

    __slots__ = ("lat", "lon", "radius_m", "inclusion")

    def __init__(self, lat: float, lon: float, radius_m: float, inclusion: bool = False):
        if radius_m <= 0:
            raise ValueError(f"半徑須為正:{radius_m}")
        self.lat, self.lon, self.radius_m, self.inclusion = lat, lon, radius_m, inclusion


class Polygon:
    """多邊形圍欄(頂點 [(lat, lon), ...],已去除首尾重複)。"""

    __slots__ = ("vertices", "inclusion")

    def __init__(self, vertices: list[tuple[float, float]], inclusion: bool = False):
        if len(vertices) < 3:
            raise ValueError(f"多邊形至少 3 頂點:{len(vertices)}")
        self.vertices, self.inclusion = vertices, inclusion


def load_geojson(path: str | Path) -> tuple[list[Polygon], list[Circle]]:
    """解析 GeoJSON FeatureCollection;不支援的 geometry 直接報錯(不臆測)。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"僅支援 FeatureCollection(type={data.get('type')!r})")

    polygons: list[Polygon] = []
    circles: list[Circle] = []
    for idx, feat in enumerate(data.get("features", [])):
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        inclusion = bool(props.get("inclusion", False))
        gtype = geom.get("type")
        if gtype == "Polygon":
            polygons.append(Polygon(_ring_to_vertices(geom["coordinates"], idx), inclusion))
        elif gtype == "MultiPolygon":
            for poly_coords in geom["coordinates"]:
                polygons.append(Polygon(_ring_to_vertices(poly_coords, idx), inclusion))
        elif gtype == "Point":
            radius = props.get("radius_m")
            if radius is None:
                raise ValueError(f"feature {idx}: Point 需 properties.radius_m(公尺)")
            lon, lat = geom["coordinates"][:2]
            circles.append(Circle(lat, lon, float(radius), inclusion))
        else:
            raise ValueError(f"feature {idx}: 不支援 geometry {gtype!r}")
    if not polygons and not circles:
        raise ValueError("無任何圍欄 feature")
    return polygons, circles


def _ring_to_vertices(coordinates: list, idx: int) -> list[tuple[float, float]]:
    """取外環([0];內環/孔洞 PX4 圍欄不支援,存在即報錯),GeoJSON [lon,lat]→(lat,lon)。"""
    if len(coordinates) > 1:
        raise ValueError(f"feature {idx}: 多邊形含內環(孔洞),PX4 圍欄不支援")
    ring = coordinates[0]
    verts = [(float(lat), float(lon)) for lon, lat in ring]
    if len(verts) >= 2 and verts[0] == verts[-1]:  # GeoJSON 閉環慣例
        verts = verts[:-1]
    return verts


def to_fence_items(polygons: list[Polygon], circles: list[Circle]) -> list[dict[str, Any]]:
    """轉 MISSION_TYPE_FENCE 項目序列(MISSION_ITEM_INT 欄位語意,座標 1e7)。

    多邊形:每頂點一個 NAV_FENCE_POLYGON_VERTEX_*,param1 = 該多邊形頂點總數。
    圓形:一個 NAV_FENCE_CIRCLE_*,param1 = 半徑(公尺)。
    """
    items: list[dict[str, Any]] = []
    seq = 0
    for poly in polygons:
        cmd = (MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION if poly.inclusion
               else MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION)
        n = len(poly.vertices)
        for lat, lon in poly.vertices:
            items.append(_item(seq, cmd, param1=float(n), lat=lat, lon=lon))
            seq += 1
    for c in circles:
        cmd = (MAV_CMD_NAV_FENCE_CIRCLE_INCLUSION if c.inclusion
               else MAV_CMD_NAV_FENCE_CIRCLE_EXCLUSION)
        items.append(_item(seq, cmd, param1=c.radius_m, lat=c.lat, lon=c.lon))
        seq += 1
    return items


def _item(seq: int, command: int, param1: float, lat: float, lon: float) -> dict[str, Any]:
    return {
        "seq": seq,
        "frame": MAV_FRAME_GLOBAL,
        "command": command,
        "param1": param1,
        "param2": 0.0, "param3": 0.0, "param4": 0.0,
        "x": int(round(lat * 1e7)),
        "y": int(round(lon * 1e7)),
        "z": 0.0,
        "mission_type": MAV_MISSION_TYPE_FENCE,
    }


def to_qgc_geofence(polygons: list[Polygon], circles: list[Circle]) -> dict[str, Any]:
    """轉 QGC .plan 的 geoFence 區塊(可直接取代範本內的 geoFence 鍵)。"""
    return {
        "version": 2,
        "polygons": [
            {"inclusion": p.inclusion, "polygon": [[lat, lon] for lat, lon in p.vertices],
             "version": 1}
            for p in polygons
        ],
        "circles": [
            {"inclusion": c.inclusion,
             "circle": {"center": [c.lat, c.lon], "radius": c.radius_m}, "version": 1}
            for c in circles
        ],
    }


def budget_report(
    polygons: list[Polygon], circles: list[Circle],
    max_polygons: int = BUDGET_MAX_POLYGONS, max_vertices: int = BUDGET_MAX_VERTICES,
) -> dict[str, Any]:
    """容量預算:多邊形數與總頂點數對門檻;ok=False 時列超限細目。"""
    n_poly = len(polygons)
    n_verts = sum(len(p.vertices) for p in polygons)
    violations = []
    if n_poly > max_polygons:
        violations.append(f"多邊形 {n_poly} > {max_polygons}")
    if n_verts > max_vertices:
        violations.append(f"總頂點 {n_verts} > {max_vertices}")
    return {
        "polygons": n_poly, "vertices": n_verts, "circles": len(circles),
        "max_polygons": max_polygons, "max_vertices": max_vertices,
        "ok": not violations, "violations": violations,
    }


def simplify_polygon(poly: Polygon, tolerance_deg: float) -> Polygon:
    """Douglas-Peucker 簡化(閉環;經緯度平面近似,公里級禁航區誤差可忽略)。

    tolerance_deg 約略換算:1e-5 度 ≈ 1.1 m(緯度向)。保底輸出 ≥3 頂點。
    """
    verts = poly.vertices
    if len(verts) <= 3:
        return poly
    # 閉環處理:以首頂點切開成開放折線(首尾各保留)再簡化
    line = verts + [verts[0]]
    kept = _dp(line, tolerance_deg)[:-1]  # 移掉補上的閉合點
    if len(kept) < 3:
        kept = verts[:3]
    return Polygon(kept, poly.inclusion)


def _dp(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        d = _point_seg_dist(points[i], a, b)
        if d > dmax:
            dmax, idx = d, i
    if dmax <= eps:
        return [a, b]
    left = _dp(points[: idx + 1], eps)
    right = _dp(points[idx:], eps)
    return left[:-1] + right


def _point_seg_dist(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geojson", help="禁航區 GeoJSON(FeatureCollection)")
    parser.add_argument("--format", choices=["fence-json", "qgc-geofence"],
                        default="fence-json")
    parser.add_argument("--simplify", type=float, default=None, metavar="DEG",
                        help="Douglas-Peucker 容差(度;1e-5 ≈ 1.1 m)")
    parser.add_argument("--max-polygons", type=int, default=BUDGET_MAX_POLYGONS)
    parser.add_argument("--max-vertices", type=int, default=BUDGET_MAX_VERTICES)
    parser.add_argument("--output", "-o", default=None, help="輸出檔(預設 stdout)")
    args = parser.parse_args()

    polygons, circles = load_geojson(args.geojson)
    if args.simplify is not None:
        polygons = [simplify_polygon(p, args.simplify) for p in polygons]

    report = budget_report(polygons, circles, args.max_polygons, args.max_vertices)
    import sys
    print(
        f"[geofence] 多邊形 {report['polygons']}/{report['max_polygons']},"
        f"頂點 {report['vertices']}/{report['max_vertices']},圓 {report['circles']}",
        file=sys.stderr,
    )
    if not report["ok"]:
        for v in report["violations"]:
            print(f"[geofence] 超限:{v}(可用 --simplify 壓頂點)", file=sys.stderr)
        return 1

    out = (to_fence_items(polygons, circles) if args.format == "fence-json"
           else to_qgc_geofence(polygons, circles))
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
