import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { DeviceStatusView } from "../types";

// 預設內嵌 OSM raster 樣式(私有部署可用 VITE_MAP_STYLE 換成離線/自建 tile 伺服器)。
const DEFAULT_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

const STYLE: string | maplibregl.StyleSpecification =
  (import.meta.env.VITE_MAP_STYLE as string | undefined) ?? DEFAULT_STYLE;

type Props = {
  devices: DeviceStatusView[];
  selected: string | null;
  onSelect: (serial: string) => void;
};

export function FleetMap({ devices, selected, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<Map<string, maplibregl.Marker>>(new Map());
  const fittedRef = useRef(false);

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE,
      center: [121.5, 25.03],
      zoom: 9,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      markersRef.current.clear();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const markers = markersRef.current;
    const seen = new Set<string>();

    for (const d of devices) {
      if (d.lat_deg == null || d.lon_deg == null) continue;
      seen.add(d.serial);
      let marker = markers.get(d.serial);
      if (!marker) {
        const el = document.createElement("div");
        el.className = `marker ${d.online ? "on" : "off"}`;
        el.title = d.serial;
        el.addEventListener("click", () => onSelect(d.serial));
        marker = new maplibregl.Marker({ element: el }).setLngLat([d.lon_deg, d.lat_deg]);
        marker.setPopup(new maplibregl.Popup({ offset: 12 }));
        marker.addTo(map);
        markers.set(d.serial, marker);
      } else {
        marker.setLngLat([d.lon_deg, d.lat_deg]);
        const el = marker.getElement();
        el.className = `marker ${d.online ? "on" : "off"}`;
      }
      const popup = marker.getPopup();
      if (popup) {
        popup.setHTML(
          `<b>${d.serial}</b><br/>${d.flight_mode ?? "—"} · ` +
            `${d.battery_pct != null ? d.battery_pct.toFixed(0) + "%" : "—"} · ` +
            `${d.rel_alt_m != null ? d.rel_alt_m.toFixed(0) + "m" : "—"}`,
        );
      }
    }

    // 移除已不存在的 marker
    for (const [serial, marker] of markers) {
      if (!seen.has(serial)) {
        marker.remove();
        markers.delete(serial);
      }
    }

    // 首次有座標時自動框住全機隊
    if (!fittedRef.current) {
      const pts = devices.filter((d) => d.lat_deg != null && d.lon_deg != null);
      if (pts.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        for (const d of pts) bounds.extend([d.lon_deg as number, d.lat_deg as number]);
        map.fitBounds(bounds, { padding: 80, maxZoom: 14, duration: 0 });
        fittedRef.current = true;
      }
    }
  }, [devices, onSelect]);

  // 選取 → 該機 popup 開啟並置中
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selected) return;
    const marker = markersRef.current.get(selected);
    if (marker) {
      map.easeTo({ center: marker.getLngLat(), duration: 300 });
      marker.togglePopup();
    }
  }, [selected]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
