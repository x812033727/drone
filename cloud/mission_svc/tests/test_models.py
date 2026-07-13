"""模型驗證純單元測試。"""

import pytest
from mission_svc.models import RouteCreate, Waypoint
from pydantic import ValidationError


def test_waypoint_valid():
    w = Waypoint(lat_deg=25.0, lon_deg=121.5, rel_alt_m=30)
    assert w.rel_alt_m == 30
    assert w.hold_s == 0.0


def test_waypoint_lat_out_of_range():
    with pytest.raises(ValidationError):
        Waypoint(lat_deg=91, lon_deg=0)


def test_waypoint_lon_out_of_range():
    with pytest.raises(ValidationError):
        Waypoint(lat_deg=0, lon_deg=181)


def test_route_requires_waypoints():
    with pytest.raises(ValidationError):
        RouteCreate(name="空航線", waypoints=[])


def test_route_blank_name():
    with pytest.raises(ValidationError):
        RouteCreate(name="  ", waypoints=[Waypoint(lat_deg=0, lon_deg=0)])
