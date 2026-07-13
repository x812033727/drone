"""mosquitto mTLS + per-device ACL 驗證(paho,TLS client cert)。

由 verify_mtls.sh 起 mosquitto 容器後呼叫。引數:
  test_mtls.py <port> <ca> <certs_dir>
certs_dir 需含 dev-1.{cert,key}.pem、dev-2.{cert,key}.pem、backend.{cert,key}.pem。

ACL 以「訊息投遞」斷言(比 SUBACK 可靠:mosquitto 對被拒訂閱回 granted 但不投遞):
  ①無憑證連線被拒 ②讀隔離:dev-1 訂他機主題收不到、訂自己收得到
  ③寫隔離:dev-1 發他機主題後端收不到、發自己後端收得到(= mTLS 端到端亦通)
"""

import ssl
import sys
import time

import paho.mqtt.client as mqtt

PORT = int(sys.argv[1])
CA = sys.argv[2]
CERTS = sys.argv[3]


def connect(cid, cert=None, key=None, timeout=5):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid, protocol=mqtt.MQTTv5)
    if cert:
        c.tls_set(ca_certs=CA, certfile=cert, keyfile=key, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    else:
        c.tls_set(ca_certs=CA, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    rc = {}
    c.on_connect = lambda cl, u, f, reason, p: rc.setdefault("r", reason)
    c.connect("localhost", PORT, keepalive=10)
    c.loop_start()
    t0 = time.time()
    while "r" not in rc and time.time() - t0 < timeout:
        time.sleep(0.05)
    if "r" not in rc:
        c.loop_stop()
        raise TimeoutError(f"{cid} 連線逾時")
    if rc["r"].is_failure:
        c.loop_stop()
        raise ConnectionError(f"{cid} 連線被拒:{rc['r']}")
    return c


def cert(name):
    return (f"{CERTS}/{name}.cert.pem", f"{CERTS}/{name}.key.pem")


def fail(msg):
    print(f"✗ {msg}")
    sys.exit(1)


def received(sub_client, topic, pub_client, pub_topic, payload, wait=1.5):
    """sub_client 訂 topic,pub_client 發 pub_topic;回傳是否收到(投遞測 ACL)。"""
    box = {}
    sub_client.on_message = lambda cl, u, m: box.setdefault("p", m.payload.decode())
    sub_client.subscribe(topic, qos=1)
    time.sleep(0.3)
    pub_client.publish(pub_topic, payload, qos=1)
    t0 = time.time()
    while "p" not in box and time.time() - t0 < wait:
        time.sleep(0.05)
    sub_client.unsubscribe(topic)
    return box.get("p") == payload


# ① 無憑證 → 連線被拒
try:
    connect("no-cert")
    fail("無憑證竟然連上(應被 mTLS 拒絕)")
except Exception:
    print("✓ 無 client 憑證連線被拒")

d1 = connect("dev-1", *cert("dev-1"))
bk = connect("backend", *cert("backend"))

# ② 讀隔離:dev-1 訂「自己」cmd 收得到、訂「他機」cmd 收不到
if not received(d1, "fleet/dev-1/cmd/mission", bk, "fleet/dev-1/cmd/mission", "own-cmd"):
    fail("dev-1 訂自己 cmd 應收得到(backend 下行)")
print("✓ dev-1 訂自己 cmd 收得到")
if received(d1, "fleet/dev-2/cmd/mission", bk, "fleet/dev-2/cmd/mission", "other-cmd"):
    fail("dev-1 訂他機 cmd 竟收到(ACL 讀隔離破功)")
print("✓ dev-1 訂他機 cmd 收不到(ACL 讀隔離)")

# ③ 寫隔離:dev-1 發「自己」遙測後端收得到(mTLS e2e)、發「他機」遙測後端收不到
if not received(bk, "fleet/dev-1/telemetry", d1, "fleet/dev-1/telemetry", '{"droneId":"dev-1"}'):
    fail("dev-1 發自己遙測 backend 應收到(mTLS 端到端)")
print("✓ dev-1 發自己遙測 backend 收到(mTLS 端到端)")
if received(bk, "fleet/dev-2/telemetry", d1, "fleet/dev-2/telemetry", "spoof"):
    fail("dev-1 發他機遙測 backend 竟收到(ACL 寫隔離破功)")
print("✓ dev-1 發他機遙測被 ACL 拒(寫隔離,防冒名)")

for c in (d1, bk):
    c.loop_stop()
    c.disconnect()
print("\nRESULT: PASS — mosquitto mTLS + per-device ACL(讀寫機身隔離)全通過")
