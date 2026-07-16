// 航線規劃小地圖(G5):點擊加航點、拖曳移動、與表單雙向同步。
// 兌現 MissionManager RouteForm 的「地圖點擊繪製航點」TODO。
import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import { config } from "../config";

// 與 FleetMap 同款預設樣式(私有部署以 runtime mapStyle 換離線 tile)。
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
const STYLE: string | maplibregl.StyleSpecification = config.mapStyle ?? DEFAULT_STYLE;

export type LatLon = { lat: number; lon: number };

type Props = {
  // 已知航點(lat/lon;非法/空值列跳過,由父層過濾後傳入)
  points: LatLon[];
  // 地圖點擊 → 新增航點(附到尾端)
  onAdd: (p: LatLon) => void;
  // 拖曳既有航點 → 更新該索引座標
  onMove: (index: number, p: LatLon) => void;
};

export function WaypointMap({ points, onAdd, onMove }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  // 最新 callback/points 以 ref 供地圖事件讀取(避免重建地圖)
  const onAddRef = useRef(onAdd);
  const onMoveRef = useRef(onMove);
  onAddRef.current = onAdd;
  onMoveRef.current = onMove;

  // 建圖一次
  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE,
      center: [121.5, 25.03],
      zoom: 11,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("click", (e) => onAddRef.current({ lat: e.lngLat.lat, lon: e.lngLat.lng }));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      markersRef.current = [];
    };
  }, []);

  // 航點變化 → 重繪標記 + 連線(GeoJSON line source)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    markersRef.current.forEach((m) => m.remove());
    markersRef.current = points.map((p, i) => {
      const el = document.createElement("div");
      el.className = "wp-marker";
      el.textContent = String(i + 1);
      const marker = new maplibregl.Marker({ element: el, draggable: true })
        .setLngLat([p.lon, p.lat])
        .addTo(map);
      marker.on("dragend", () => {
        const ll = marker.getLngLat();
        onMoveRef.current(i, { lat: ll.lat, lon: ll.lng });
      });
      return marker;
    });

    const line = {
      type: "Feature" as const,
      properties: {},
      geometry: {
        type: "LineString" as const,
        coordinates: points.map((p) => [p.lon, p.lat]),
      },
    };
    const drawLine = () => {
      const src = map.getSource("wp-line") as maplibregl.GeoJSONSource | undefined;
      if (src) {
        src.setData(line);
      } else {
        map.addSource("wp-line", { type: "geojson", data: line });
        map.addLayer({
          id: "wp-line",
          type: "line",
          source: "wp-line",
          paint: { "line-color": "#3b82f6", "line-width": 2 },
        });
      }
    };
    if (map.isStyleLoaded()) drawLine();
    else map.once("load", drawLine);
  }, [points]);

  return <div ref={containerRef} className="wp-map" />;
}
