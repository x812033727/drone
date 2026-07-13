"""驗證單一 client 憑證能否連上 mTLS broker(供 CRL 吊銷測試)。

引數:port ca cert key expect(ok|reject)
被 CRL 吊銷的憑證於 TLS 握手即被拒 → 連不上。exit 0=符合預期。
"""

import ssl
import sys
import time
from typing import Any

import paho.mqtt.client as mqtt

PORT, CA, CERT, KEY, EXPECT = (
    int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
)

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
c.tls_set(ca_certs=CA, certfile=CERT, keyfile=KEY, tls_version=ssl.PROTOCOL_TLS_CLIENT)
rc: dict[str, Any] = {}
c.on_connect = lambda cl, u, f, reason, p: rc.setdefault("r", reason)

connected = False
try:
    c.connect("localhost", PORT)
    c.loop_start()
    t0 = time.time()
    while "r" not in rc and time.time() - t0 < 4:
        time.sleep(0.05)
    connected = "r" in rc and not rc["r"].is_failure
except Exception:
    connected = False
finally:
    try:
        c.loop_stop()
    except Exception:
        pass

ok = (connected and EXPECT == "ok") or (not connected and EXPECT == "reject")
name = CERT.rsplit("/", 1)[-1]
mark = "✓" if ok else "✗"
print(f"{mark} cert={name} expect={EXPECT} connected={connected}")
sys.exit(0 if ok else 1)
