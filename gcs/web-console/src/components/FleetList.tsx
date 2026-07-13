import type { DeviceStatusView } from "../types";

type Props = {
  devices: DeviceStatusView[];
  selected: string | null;
  onSelect: (serial: string) => void;
};

function fmtSeen(last: string | null): string {
  if (!last) return "無遙測";
  const s = Math.round((Date.now() - new Date(last).getTime()) / 1000);
  if (s < 60) return `${s} 秒前`;
  if (s < 3600) return `${Math.round(s / 60)} 分前`;
  return `${Math.round(s / 3600)} 時前`;
}

export function FleetList({ devices, selected, onSelect }: Props) {
  if (devices.length === 0) {
    return <div className="empty">尚無裝置。用 fleet-svc 建立裝置或灌遙測後即會出現。</div>;
  }
  return (
    <div>
      {devices.map((d) => {
        const low = d.battery_pct != null && d.battery_pct < 20;
        return (
          <div
            key={d.serial}
            className="device"
            style={selected === d.serial ? { background: "#222b35" } : undefined}
            onClick={() => onSelect(d.serial)}
          >
            <div className="row1">
              <span className={`dot ${d.online ? "on" : "off"}`} />
              <span className="serial">{d.serial}</span>
              <span className="mode">{d.flight_mode ?? "—"}</span>
            </div>
            <div className="row2">
              <span className={low ? "battery low" : "battery"}>
                🔋 {d.battery_pct != null ? `${d.battery_pct.toFixed(0)}%` : "—"}
              </span>
              <span>⬆ {d.rel_alt_m != null ? `${d.rel_alt_m.toFixed(0)}m` : "—"}</span>
              <span>{fmtSeen(d.last_seen)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
