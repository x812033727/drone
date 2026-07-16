#!/usr/bin/env bash
# drone_spray 斷藥觸發條件斷言(F9,確定性,免飛行):
# 讀 spray_flags(滿箱=0)→ pxh `drone_spray empty` → 斷言 TANK_EMPTY 位(bit2)。
# 證明「藥箱空 → 觸發旗標」;實際 RTL vehicle_command 由 armed 守門(不在地面
# 誤觸 RTL,安全設計),armed-飛行 → 觀察 RTL 屬 nightly gazebo 行為層。
set -euo pipefail
BIN="$1"; LISTENER="${BIN}/px4-listener"; SPRAY="${BIN}/px4-drone_spray"

flags() { "${LISTENER}" drone_spray_status 2>/dev/null | grep -oE 'spray_flags: [0-9]+' | grep -oE '[0-9]+$' | head -1; }

before="$(flags || echo -1)"
echo "[spray-empty] 滿箱 spray_flags=${before}(應 0)"
"${SPRAY}" empty >/dev/null 2>&1 || true
sleep 2
after="$(flags || echo -1)"
echo "[spray-empty] 觸發後 spray_flags=${after}"
# TANK_EMPTY = bit1(值 2);after & 2 應非 0
if [[ "${after}" -lt 0 ]] || (( (after & 2) == 0 )); then
    echo "[spray-empty] FAIL:未觀察到 TANK_EMPTY 旗標" >&2
    exit 1
fi
echo "[spray-empty] PASS:藥箱空 → TANK_EMPTY 旗標(RTL vehicle_command 由 armed 守門)"
