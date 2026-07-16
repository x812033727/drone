"""geofence 轉換器:GeoJSON 解析/兩種輸出/預算/DP 簡化(純函式,全覆蓋)。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "geofence"))

from geofence import (  # noqa: E402
    BUDGET_MAX_VERTICES,
    MAV_CMD_NAV_FENCE_CIRCLE_EXCLUSION,
    MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION,
    MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION,
    Polygon,
    budget_report,
    load_geojson,
    simplify_polygon,
    to_fence_items,
    to_qgc_geofence,
)


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _poly_feature(ring: list[list[float]], **props) -> dict:
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


# 台北附近 100m 級方形(GeoJSON [lon, lat],閉環)
SQUARE = [[121.5650, 25.0330], [121.5660, 25.0330], [121.5660, 25.0340],
          [121.5650, 25.0340], [121.5650, 25.0330]]


def _write(tmp_path: Path, obj: dict) -> Path:
    p = tmp_path / "zones.geojson"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_polygon_parse_dedups_closing_vertex(tmp_path):
    polys, circles = load_geojson(_write(tmp_path, _fc([_poly_feature(SQUARE)])))
    assert len(polys) == 1 and not circles
    assert len(polys[0].vertices) == 4  # 閉環重複頂點去除
    assert polys[0].vertices[0] == (25.0330, 121.5650)  # [lon,lat] → (lat,lon)
    assert polys[0].inclusion is False  # 預設禁航 = exclusion


def test_fence_items_polygon_and_circle(tmp_path):
    fc = _fc([
        _poly_feature(SQUARE),
        {"type": "Feature", "properties": {"radius_m": 200},
         "geometry": {"type": "Point", "coordinates": [121.57, 25.04]}},
    ])
    polys, circles = load_geojson(_write(tmp_path, fc))
    items = to_fence_items(polys, circles)
    assert len(items) == 5  # 4 頂點 + 1 圓
    poly_items = items[:4]
    assert all(i["command"] == MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION for i in poly_items)
    assert all(i["param1"] == 4.0 for i in poly_items)  # param1 = 頂點總數
    assert poly_items[0]["x"] == int(25.0330 * 1e7)
    circle = items[4]
    assert circle["command"] == MAV_CMD_NAV_FENCE_CIRCLE_EXCLUSION
    assert circle["param1"] == 200.0
    assert [i["seq"] for i in items] == list(range(5))
    assert all(i["mission_type"] == 1 for i in items)


def test_inclusion_property(tmp_path):
    polys, _ = load_geojson(
        _write(tmp_path, _fc([_poly_feature(SQUARE, inclusion=True)]))
    )
    items = to_fence_items(polys, [])
    assert all(i["command"] == MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION for i in items)


def test_qgc_geofence_block(tmp_path):
    fc = _fc([
        _poly_feature(SQUARE),
        {"type": "Feature", "properties": {"radius_m": 150.0},
         "geometry": {"type": "Point", "coordinates": [121.57, 25.04]}},
    ])
    polys, circles = load_geojson(_write(tmp_path, fc))
    block = to_qgc_geofence(polys, circles)
    assert block["version"] == 2
    assert block["polygons"][0]["inclusion"] is False
    assert len(block["polygons"][0]["polygon"]) == 4
    assert block["circles"][0]["circle"]["radius"] == 150.0


def test_budget_violation():
    big = Polygon([(25.0 + i * 1e-4, 121.5) for i in range(BUDGET_MAX_VERTICES + 1)])
    report = budget_report([big], [])
    assert not report["ok"]
    assert any("總頂點" in v for v in report["violations"])


def test_budget_ok(tmp_path):
    polys, circles = load_geojson(_write(tmp_path, _fc([_poly_feature(SQUARE)])))
    assert budget_report(polys, circles)["ok"]


def test_simplify_reduces_collinear_vertices():
    # 方形每邊插 10 個共線點 → DP 應收斂回 4 頂點
    corners = [(25.0330, 121.5650), (25.0330, 121.5660),
               (25.0340, 121.5660), (25.0340, 121.5650)]
    dense: list[tuple[float, float]] = []
    for i, c in enumerate(corners):
        nxt = corners[(i + 1) % 4]
        for t in range(10):
            dense.append((c[0] + (nxt[0] - c[0]) * t / 10, c[1] + (nxt[1] - c[1]) * t / 10))
    poly = simplify_polygon(Polygon(dense), tolerance_deg=1e-7)
    assert len(poly.vertices) == 4
    assert set(poly.vertices) == set(corners)


def test_holes_rejected(tmp_path):
    ring_outer = SQUARE
    ring_inner = [[121.5653, 25.0333], [121.5657, 25.0333], [121.5657, 25.0337],
                  [121.5653, 25.0333]]
    feat = {
        "type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [ring_outer, ring_inner]},
    }
    with pytest.raises(ValueError, match="孔洞"):
        load_geojson(_write(tmp_path, _fc([feat])))


def test_point_without_radius_rejected(tmp_path):
    feat = {"type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [121.5, 25.0]}}
    with pytest.raises(ValueError, match="radius_m"):
        load_geojson(_write(tmp_path, _fc([feat])))


def test_unsupported_geometry_rejected(tmp_path):
    feat = {"type": "Feature", "properties": {},
            "geometry": {"type": "LineString", "coordinates": [[121.5, 25.0], [121.6, 25.1]]}}
    with pytest.raises(ValueError, match="LineString"):
        load_geojson(_write(tmp_path, _fc([feat])))
