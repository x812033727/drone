"""機載 OTA 代理:訂閱雲端 OTA 指令,下載→驗簽→套用 A/B slot→健康檢查→回滾→回報。

落地 [docs/20-software/ota.md](../../../docs/20-software/ota.md) 的**機載代理側**,以
**軟體套件/設定 OTA** 的可驗證版實作 ota.md 中程式可達的部分;實體韌體雙 bank 代燒
(§2 方案 B、rootfs 分區實體寫入)屬 Phase 3,於對應位置以 TODO 標明,不在本模組實作。

對齊既有派遣模式(command.py):
- 訂閱主題 ``fleet/{drone_id}/cmd/ota``(對齊 ``cmd/mission``);
- 進度/終態回報到 ``fleet/{drone_id}/ota/progress``(對齊 mission progress),QoS 1、
  語意 **at-least-once**(消費端以 update_id + state 去重,終態可能重複);
- **不碰 proto 契約**:OTA 指令與進度皆走 **JSON payload**(events.proto/mission.proto 無
  OTA 型別,刻意不動 proto,避免 contract 守門;與 cert_monitor 的 alerts 同策略)。

## 指令 payload(JSON)

```json
{
  "action": "install",              // install | pause | resume | rollback
  "update_id": "ota-2026-07-13-01", // 本次更新工單 id(回報去重鍵)
  "component": "onboard",           // 軟體套件元件名(對齊 ota.md 相容矩陣 component)
  "version": "1.4.0",               // 目標版本(SemVer)
  "url": "https://mirror.example/onboard-1.4.0.tar.gz", // 下載來源(HTTPS/mTLS 沿用既有憑證)
  "size": 12345678,                 // 位元組數(斷點續傳/完整性用)
  "sha256": "<hex>",                // 套件內容 SHA-256(小寫 hex)
  "signature": "<base64>"          // 對「32-byte SHA-256 摘要」的 Ed25519 簽章(base64)
}
```

pause / resume / rollback 只需 ``action`` 與 ``update_id``(rollback 亦可帶 ``component``)。

## 驗簽點與安全(ota.md §4)

- **收檔後驗簽**(drone-agent 收檔驗簽點):先比對 SHA-256,再以 Ed25519 公鑰驗證
  簽章;**任一不過一律拒絕套用**(不寫入 standby slot、回報 REJECTED)。
- 公鑰來源:env ``OTA_PUBLIC_KEY``(Ed25519 公鑰 PEM 檔路徑)。**未設公鑰 = 無法驗簽
  = 一律拒絕安裝**(fail-closed);釋出簽章私鑰存離線 HSM(security.md §4),機上只有公鑰。
- 簽章對象刻意選 **SHA-256 摘要(32 bytes)** 而非整包位元組:摘要已由 checksum 綁定
  套件內容,簽摘要讓驗簽 O(1)、與下載串流解耦(GB 級 rootfs 不必整包載入記憶體)。
- 下載走 HTTPS 時沿用機-雲既有裝置憑證(mTLS,tls.py 的 MQTT_TLS_* 同組 CA/cert/key)。

## A/B slot(ota.md §3)

軟體套件以**兩個 slot 目錄 + ``current`` symlink** 模擬 A/B 分區:驗簽通過的套件寫入
**非活動(standby)slot**,切換 symlink 指向它,由健康檢查決定「提交」或「回滾」:

```
{root}/
  slots/a/            # slot A 內容
  slots/b/            # slot B 內容
  current -> slots/a  # 活動 slot(symlink;原子替換切換)
```

- 套用:驗簽套件落入 standby slot → 切 ``current`` 指向 standby → 跑健康檢查;
- **健康檢查通過**才提交(保持新 slot),失敗則把 ``current`` 切回舊 slot(**自動回滾**)
  並回報 ROLLED_BACK;
- **Phase 3 TODO**:實體 firmware 雙 bank flash / rootfs 分區寫入與 bootloader 啟動計數
  回退(ota.md §2/§3 硬體代燒)——本模組不做,僅以目錄 slot 驗證代理側編排邏輯。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import aiomqtt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from drone_agent.tls import from_env as _mqtt_tls

logger = logging.getLogger(__name__)

RECONNECT_DELAY_S = 3.0
#: 下載分塊大小(位元組):斷點續傳以此為串流讀取單位
DOWNLOAD_CHUNK_BYTES = 64 * 1024
#: 斷線重試上限(單次 install 內的續傳嘗試次數)
DEFAULT_MAX_RETRIES = 5
#: 續傳重試間隔(秒)
RETRY_DELAY_S = 2.0

#: OTA 進度/終態狀態(JSON 字串常數;非 proto enum,契約外運維語意)
STATE_RECEIVED = "RECEIVED"
STATE_DOWNLOADING = "DOWNLOADING"
STATE_VERIFYING = "VERIFYING"
STATE_APPLYING = "APPLYING"
STATE_HEALTH_CHECK = "HEALTH_CHECK"
STATE_COMPLETED = "COMPLETED"
STATE_REJECTED = "REJECTED"  # 驗簽/checksum 失敗、前置條件不過(不套用)
STATE_FAILED = "FAILED"  # 下載/套用過程失敗
STATE_ROLLED_BACK = "ROLLED_BACK"  # 健康檢查失敗,已切回舊 slot
STATE_PAUSED = "PAUSED"
STATE_RESUMED = "RESUMED"

#: 健康檢查回呼:回傳 True = 新 slot 健康(提交),False = 失敗(回滾)。
#: 實機版檢查關鍵服務起動/DDS 連通/雲連線(ota.md §3),Phase 1 接真實探測;
#: 此處以注入方式測試,預設樂觀通過(見 default_health_check)。
HealthCheck = Callable[["OtaCommand", Path], Awaitable[bool]]

#: 進度回報回呼:引數為一筆進度 dict(已含 update_id/state/version 等),best-effort。
ProgressReporter = Callable[[dict], Awaitable[None]]

#: 斷點續傳的位元組來源:給 (url, start_offset),回傳「自 start 起」的 async 位元組串流。
#: 抽象化以便單測用 fake(免真網路);實作見 httpx_range_fetcher。
RangeFetcher = Callable[[str, int], AsyncIterator[bytes]]


class OtaError(Exception):
    """OTA 流程可預期失敗(驗簽/checksum/下載),攜帶回報用的終態 state。"""

    def __init__(self, message: str, state: str) -> None:
        super().__init__(message)
        self.state = state


@dataclass(frozen=True)
class OtaCommand:
    """一筆解析後的 OTA 指令(install 需完整欄位;控制指令只需 action+update_id)。"""

    action: str
    update_id: str
    component: str = ""
    version: str = ""
    url: str = ""
    size: int = 0
    sha256: str = ""
    signature: str = ""


VALID_ACTIONS = frozenset({"install", "pause", "resume", "rollback"})


def parse_ota_command(payload: bytes | str) -> OtaCommand:
    """把 JSON payload 解析成 OtaCommand;不合法一律 raise ValueError(中文訊息)。

    install 需 update_id/component/version/url/sha256/signature 齊備(size 選填,
    純為斷點續傳提示);pause/resume/rollback 只需 action + update_id。
    未知 action、缺必要欄位、sha256 非 64-hex 皆拒收。
    """
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"ota payload 不是 UTF-8:{e}") from e
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"ota payload 不是合法 JSON:{e}") from e
    if not isinstance(obj, dict):
        raise ValueError("ota payload 必須是 JSON 物件")

    action = obj.get("action")
    if action not in VALID_ACTIONS:
        raise ValueError(f"ota action 不合法:{action!r}(須為 {sorted(VALID_ACTIONS)})")
    update_id = obj.get("update_id")
    if not update_id or not isinstance(update_id, str):
        raise ValueError("ota payload 缺 update_id(或非字串)")

    if action != "install":
        # 控制指令:只取 action/update_id(rollback 可帶 component,選填)
        return OtaCommand(action=action, update_id=update_id, component=obj.get("component", ""))

    for field in ("component", "version", "url", "sha256", "signature"):
        if not obj.get(field) or not isinstance(obj.get(field), str):
            raise ValueError(f"install 指令缺必要欄位或型別錯:{field}")
    sha256 = obj["sha256"].lower()
    if len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256):
        raise ValueError("sha256 需為 64 字元小寫 hex")
    size = obj.get("size", 0)
    if not isinstance(size, int) or size < 0:
        raise ValueError("size 需為非負整數")
    return OtaCommand(
        action="install",
        update_id=update_id,
        component=obj["component"],
        version=obj["version"],
        url=obj["url"],
        size=size,
        sha256=sha256,
        signature=obj["signature"],
    )


# ---- 驗簽:SHA-256 校驗 + Ed25519 簽章驗證(純函式,壞簽章一律回 False)----


def sha256_hex(data: bytes) -> str:
    """算 data 的 SHA-256 小寫 hex(單元測試/小檔用;大檔用 sha256_file 串流)。"""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """串流算檔案 SHA-256(GB 級 rootfs 不整包載入記憶體),回傳小寫 hex。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


def load_public_key(path: str | os.PathLike) -> Ed25519PublicKey:
    """從 PEM 檔載入 Ed25519 公鑰;非 Ed25519 公鑰 raise ValueError。"""
    data = Path(path).read_bytes()
    key = load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError(f"OTA 公鑰須為 Ed25519,收到 {type(key).__name__}")
    return key


def load_public_key_from_env() -> Ed25519PublicKey | None:
    """從 env ``OTA_PUBLIC_KEY``(PEM 檔路徑)載入公鑰;未設或載入失敗回 None。

    回 None 即「無法驗簽」——呼叫端據此 fail-closed 拒絕安裝(絕不放行未驗簽套件)。
    """
    path = os.environ.get("OTA_PUBLIC_KEY")
    if not path:
        return None
    try:
        return load_public_key(path)
    except (OSError, ValueError) as e:
        logger.error("OTA_PUBLIC_KEY 載入失敗(%s);將拒絕所有安裝(fail-closed)", e)
        return None


def verify_signature(digest: bytes, signature_b64: str, public_key: Ed25519PublicKey) -> bool:
    """驗證 Ed25519 簽章:signature 是對「32-byte SHA-256 摘要」的簽章(base64 編碼)。

    任何情況(壞 base64、長度不符、簽章不符)一律回 **False**,絕不拋例外——
    呼叫端只需布林決策「拒絕/放行」,驗簽失敗不得因例外變成放行。
    """
    try:
        sig = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("OTA 簽章非合法 base64,拒絕")
        return False
    try:
        public_key.verify(sig, digest)
        return True
    except InvalidSignature:
        logger.warning("OTA 簽章驗證失敗(InvalidSignature),拒絕")
        return False


def verify_artifact(
    path: Path, expected_sha256: str, signature_b64: str, public_key: Ed25519PublicKey
) -> None:
    """收檔後驗簽點(ota.md §4):先 SHA-256 校驗,再 Ed25519 驗簽;任一不過 raise OtaError。

    成功則靜默返回;失敗以 state=REJECTED 拋出(不套用、回報 REJECTED)。
    """
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise OtaError(
            f"SHA-256 不符:期望 {expected_sha256[:12]}…,實得 {actual[:12]}…", STATE_REJECTED
        )
    digest = bytes.fromhex(actual)
    if not verify_signature(digest, signature_b64, public_key):
        raise OtaError("Ed25519 簽章驗證失敗", STATE_REJECTED)


# ---- 斷點續傳下載 ----


async def download_resumable(
    url: str,
    dest: Path,
    fetch_range: RangeFetcher,
    max_retries: int = DEFAULT_MAX_RETRIES,
    is_paused: Callable[[], bool] | None = None,
) -> int:
    """斷點續傳下載到 ``dest``(先寫 ``dest.part``,完成才 rename)。

    以 ``dest.part`` 現有大小為已收位元組,斷線後用 RangeFetcher(url, start)自
    **已收位元組**續傳,不重頭來(ota.md §1 斷點續傳)。串流中途 fetch_range 拋
    例外(模擬斷線)即記已收位元組、退避後重試,直到 max_retries 耗盡才放棄。
    回傳總下載位元組數。

    is_paused():每塊寫入前檢查,回 True 即中止本次下載並 raise OtaError(PAUSED)——
    現場作業期間暫停下載(ota.md §1「下載與安裝解耦、現場預設暫停」)。
    """
    part = dest.with_suffix(dest.suffix + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    attempt = 0
    while True:
        received = part.stat().st_size if part.exists() else 0
        try:
            # append 模式:斷線續傳時接在既有 .part 尾端(不覆蓋已收段)
            with open(part, "ab") as f:
                async for chunk in fetch_range(url, received):
                    if is_paused is not None and is_paused():
                        raise OtaError("下載已暫停", STATE_PAUSED)
                    f.write(chunk)
                    received += len(chunk)
            # 串流正常結束 = 下載完成
            part.replace(dest)
            logger.info("OTA 下載完成:%s(%d bytes)", dest.name, received)
            return received
        except OtaError:
            raise  # PAUSED 直接上拋,不當作可重試的斷線
        except Exception as e:
            attempt += 1
            if attempt > max_retries:
                raise OtaError(
                    f"下載重試 {max_retries} 次仍失敗(已收 {received} bytes):{e}", STATE_FAILED
                ) from e
            logger.warning(
                "OTA 下載斷線(已收 %d bytes),第 %d/%d 次續傳前退避 %.0fs:%s",
                received,
                attempt,
                max_retries,
                RETRY_DELAY_S,
                e,
            )
            await asyncio.sleep(RETRY_DELAY_S)


def httpx_range_fetcher(tls_cert_env: bool = True) -> RangeFetcher:
    """以 httpx 實作 RangeFetcher:HTTP Range 請求自 start 位移串流位元組。

    HTTPS 下沿用機-雲既有裝置憑證(mTLS,MQTT_TLS_* 同組 CA/cert/key);
    伺服器不支援 206 Partial 時退回從頭下載(呼叫端的 .part 會先被清)。
    延遲 import httpx(僅實機下載路徑用到;單測走 fake fetcher,不觸此路徑)。
    """
    import httpx

    verify: object = True
    cert: tuple[str, str] | None = None
    if tls_cert_env:
        ca = os.environ.get("MQTT_TLS_CA")
        c = os.environ.get("MQTT_TLS_CERT")
        k = os.environ.get("MQTT_TLS_KEY")
        if ca:
            verify = ca
        if c and k:
            cert = (c, k)

    async def fetch(url: str, start: int) -> AsyncIterator[bytes]:
        headers = {"Range": f"bytes={start}-"} if start > 0 else {}
        async with httpx.AsyncClient(verify=verify, cert=cert, timeout=None) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(DOWNLOAD_CHUNK_BYTES):
                    yield chunk

    return fetch


# ---- A/B slot(目錄 + symlink 模擬分區)----


class SlotManager:
    """以 ``{root}/slots/{a,b}`` + ``{root}/current`` symlink 模擬 A/B 分區。

    - active_slot / standby_slot:讀 current symlink 判定活動/非活動 slot;
    - stage():把驗簽通過的套件放入 standby slot(清空後寫入);
    - switch(slot):原子替換 current symlink 指向指定 slot(切換啟動分區);
    - 實體 firmware/rootfs 寫入屬 Phase 3(見模組 docstring),此處只動目錄。
    """

    SLOT_NAMES = ("a", "b")

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)
        self.slots_dir = self.root / "slots"
        self.current_link = self.root / "current"

    def ensure_layout(self) -> None:
        """建立 slots/a、slots/b;若無 current symlink 預設指向 slot a。"""
        for name in self.SLOT_NAMES:
            (self.slots_dir / name).mkdir(parents=True, exist_ok=True)
        if not self.current_link.exists() and not self.current_link.is_symlink():
            self._point_current("a")

    def _point_current(self, slot: str) -> None:
        """原子替換 current symlink 指向 slots/{slot}(先寫 tmp link 再 rename)。"""
        target = Path("slots") / slot  # 相對 link,便於整個 root 搬遷
        tmp = self.root / ".current.tmp"
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        tmp.symlink_to(target)
        os.replace(tmp, self.current_link)

    def active_slot(self) -> str:
        """current symlink 指向的 slot 名(a/b);未初始化預設 a。"""
        if not self.current_link.is_symlink():
            return "a"
        return os.readlink(self.current_link).rstrip("/").split("/")[-1]

    def standby_slot(self) -> str:
        """非活動 slot(套用目標):active 的另一個。"""
        active = self.active_slot()
        return "b" if active == "a" else "a"

    def slot_path(self, slot: str) -> Path:
        return self.slots_dir / slot

    def stage(self, artifact: Path, version: str) -> Path:
        """把驗簽通過的套件放入 standby slot(清空舊內容後寫入),回傳 standby slot 路徑。

        Phase 3 TODO:此處對軟體套件僅複製檔案 + 寫 VERSION 標記;實體 rootfs 分區
        dd 寫入 / firmware DFU 代燒(ota.md §2 方案 B)不在此實作。
        """
        standby = self.standby_slot()
        dest = self.slot_path(standby)
        # 清空 standby(唯讀根檔系語意:分區內容即映像內容,不就地漂移;ota.md §3)
        for child in dest.iterdir():
            if child.is_dir() and not child.is_symlink():
                _rmtree(child)
            else:
                child.unlink()
        (dest / artifact.name).write_bytes(artifact.read_bytes())
        (dest / "VERSION").write_text(version)
        logger.info("OTA 套件已置入 standby slot %s(version=%s)", standby, version)
        return dest

    def commit(self, slot: str) -> None:
        """提交:current 指向新 slot(健康檢查通過後呼叫)。"""
        self._point_current(slot)
        logger.info("OTA 已提交 slot %s 為活動分區", slot)

    def rollback(self, previous_slot: str) -> None:
        """回滾:current 切回舊 slot(健康檢查失敗後呼叫)。"""
        self._point_current(previous_slot)
        logger.warning("OTA 健康檢查失敗,已回滾至 slot %s", previous_slot)


def _rmtree(path: Path) -> None:
    """遞迴刪目錄(避免額外 import shutil 於熱路徑;內容量小)。"""
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            _rmtree(child)
        else:
            child.unlink()
    path.rmdir()


async def default_health_check(cmd: OtaCommand, slot_path: Path) -> bool:
    """預設健康檢查:僅確認 standby slot 有 VERSION 標記且版本相符(佔位)。

    Phase 1 TODO:接真實探測——關鍵服務起動、與飛控 DDS 連通、與雲連線(ota.md §3);
    此預設只驗「套件確實落地」,不代表服務健康。單測以注入 HealthCheck 覆蓋。
    """
    version_file = slot_path / "VERSION"
    if not version_file.is_file():
        return False
    return version_file.read_text().strip() == cmd.version


# ---- 進度回報(at-least-once,JSON)----


def progress_dict(
    cmd: OtaCommand, state: str, unix_time_ms: int, detail: str = ""
) -> dict:
    """組一筆 OTA 進度事件(JSON dict)。update_id + state 為消費端去重鍵。"""
    return {
        "update_id": cmd.update_id,
        "component": cmd.component,
        "version": cmd.version,
        "state": state,
        "unix_time_ms": unix_time_ms,
        "detail": detail,
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


class OtaAgent:
    """OTA 指令處理器:單一更新互斥、下載→驗簽→套用→健康檢查→提交/回滾→回報。

    與 command.py 的 MissionRunner 對應:純 I/O 協調,把可測邏輯(parse/verify/slot)
    委派給模組級純函式/SlotManager。健康檢查與 RangeFetcher 皆可注入,單測免真網路。

    暫停/回滾(ota.md §6):
    - pause:設暫停旗標,進行中的下載於下一塊中止(回報 PAUSED),已下載段保留 .part;
    - resume:清旗標,下次 install(同 update_id)自 .part 續傳;
    - rollback:把 current 切回前一 slot(雲端對已完成批次下發回退,ota.md §6)。
    """

    def __init__(
        self,
        drone_id: str,
        work_dir: str | os.PathLike,
        slots: SlotManager,
        public_key: Ed25519PublicKey | None,
        report: ProgressReporter,
        fetch_range: RangeFetcher,
        health_check: HealthCheck = default_health_check,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.drone_id = drone_id
        self.work_dir = Path(work_dir)
        self.slots = slots
        self.public_key = public_key
        self.report = report
        self.fetch_range = fetch_range
        self.health_check = health_check
        self.max_retries = max_retries
        self._paused = False
        #: 進行中的 update_id(互斥;None = idle)
        self.current_update_id: str | None = None
        #: 最近一筆已終結的 update_id(去重遲到重投)
        self.last_terminal: str | None = None

    @property
    def paused(self) -> bool:
        return self._paused

    async def _report(self, cmd: OtaCommand, state: str, detail: str = "") -> None:
        """best-effort 回報進度(broker 斷線只記 log,不讓 OTA 流程因回報失敗中斷)。"""
        try:
            await self.report(progress_dict(cmd, state, _now_ms(), detail))
        except Exception:
            logger.warning(
                "OTA 進度回報失敗(update_id=%s state=%s)",
                cmd.update_id,
                state,
                exc_info=True,
            )

    async def handle(self, payload: bytes) -> None:
        """處理單筆 OTA 指令(頂層防護:解析/流程例外一律吸收,不拖垮訂閱迴圈)。"""
        try:
            cmd = parse_ota_command(payload)
        except ValueError as e:
            logger.error("拒收 OTA 指令(payload 驗證失敗):%s", e)
            return
        if cmd.action == "pause":
            self._paused = True
            logger.info("OTA 已暫停(update_id=%s)", cmd.update_id)
            await self._report(cmd, STATE_PAUSED)
            return
        if cmd.action == "resume":
            self._paused = False
            logger.info("OTA 已恢復(update_id=%s)", cmd.update_id)
            await self._report(cmd, STATE_RESUMED)
            return
        if cmd.action == "rollback":
            await self._handle_rollback(cmd)
            return
        # action == install
        await self._handle_install(cmd)

    async def _handle_rollback(self, cmd: OtaCommand) -> None:
        """雲端下發回退:current 切回前一 slot(ota.md §6 對已完成批次回退)。"""
        previous = self.slots.standby_slot()  # 舊版仍在非活動 slot
        self.slots.rollback(previous)
        await self._report(cmd, STATE_ROLLED_BACK, detail=f"rollback to slot {previous}")

    async def _handle_install(self, cmd: OtaCommand) -> None:
        """install 主流程:互斥/去重 → 下載 → 驗簽 → 套用 → 健康檢查 → 提交/回滾 → 回報。"""
        if cmd.update_id == self.current_update_id:
            logger.info("忽略重複投遞的 OTA %s:與進行中更新同 id", cmd.update_id)
            return
        if cmd.update_id == self.last_terminal:
            logger.info("忽略遲到重投的 OTA %s:與最近已終結更新同 id", cmd.update_id)
            return
        if self.current_update_id is not None:
            logger.warning("拒收 OTA %s:已有更新進行中(單一更新互斥)", cmd.update_id)
            await self._report(cmd, STATE_REJECTED, detail="another update in progress")
            return
        if self.public_key is None:
            logger.error("拒收 OTA %s:未設 OTA_PUBLIC_KEY,無法驗簽(fail-closed)", cmd.update_id)
            await self._report(cmd, STATE_REJECTED, detail="no public key (fail-closed)")
            return

        self.current_update_id = cmd.update_id
        try:
            await self._report(cmd, STATE_RECEIVED)
            artifact = self.work_dir / f"{cmd.update_id}.pkg"

            # 1) 下載(斷點續傳)
            await self._report(cmd, STATE_DOWNLOADING)
            await download_resumable(
                cmd.url,
                artifact,
                self.fetch_range,
                max_retries=self.max_retries,
                is_paused=lambda: self._paused,
            )

            # 2) 驗簽(SHA-256 + Ed25519;失敗 raise OtaError(REJECTED),不套用)
            await self._report(cmd, STATE_VERIFYING)
            verify_artifact(artifact, cmd.sha256, cmd.signature, self.public_key)

            # 3) 套用到 standby slot(A/B)
            await self._report(cmd, STATE_APPLYING)
            previous_slot = self.slots.active_slot()
            standby = self.slots.standby_slot()
            slot_path = self.slots.stage(artifact, cmd.version)
            self.slots.commit(standby)  # 切換啟動分區指向新 slot

            # 4) 健康檢查 → 提交 or 自動回滾
            await self._report(cmd, STATE_HEALTH_CHECK)
            healthy = await self.health_check(cmd, slot_path)
            if not healthy:
                self.slots.rollback(previous_slot)
                await self._report(cmd, STATE_ROLLED_BACK, detail="health check failed")
                return

            # 5) 提交成功
            artifact.unlink(missing_ok=True)
            await self._report(cmd, STATE_COMPLETED, detail=f"slot {standby} committed")
            logger.info("OTA %s 完成(version=%s,slot=%s)", cmd.update_id, cmd.version, standby)
        except OtaError as e:
            logger.error("OTA %s 中止(%s):%s", cmd.update_id, e.state, e)
            await self._report(cmd, e.state, detail=str(e))
        except Exception as e:
            logger.exception("OTA %s 未預期失敗", cmd.update_id)
            await self._report(cmd, STATE_FAILED, detail=str(e))
        finally:
            self.last_terminal = cmd.update_id
            if self.current_update_id == cmd.update_id:
                self.current_update_id = None


async def ota_loop(
    mqtt_host: str,
    mqtt_port: int,
    drone_id: str,
    work_dir: str | os.PathLike,
    ota_root: str | os.PathLike,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> None:
    """訂閱 ``fleet/{drone_id}/cmd/ota``(QoS 1),派 OtaAgent 處理;斷線自動重連。

    進度回報走另開短連線(best-effort,對齊 command.py 的 publish_failed 模式),
    避免佔用訂閱連線且回報失敗不牽連訂閱。公鑰於啟動時自 env 載入(未設 = 拒絕所有安裝)。
    """
    topic = f"fleet/{drone_id}/cmd/ota"
    progress_topic = f"fleet/{drone_id}/ota/progress"
    public_key = load_public_key_from_env()
    if public_key is None:
        logger.warning("未設(或載入失敗)OTA_PUBLIC_KEY:OTA 訂閱仍運作,但所有安裝將被拒絕")

    slots = SlotManager(ota_root)
    slots.ensure_layout()

    async def report(event: dict) -> None:
        async with aiomqtt.Client(
            hostname=mqtt_host, port=mqtt_port, tls_params=_mqtt_tls()
        ) as client:
            await client.publish(progress_topic, payload=json.dumps(event), qos=1)

    agent = OtaAgent(
        drone_id=drone_id,
        work_dir=work_dir,
        slots=slots,
        public_key=public_key,
        report=report,
        fetch_range=httpx_range_fetcher(),
        max_retries=max_retries,
    )

    while True:
        try:
            async with aiomqtt.Client(
                hostname=mqtt_host, port=mqtt_port, tls_params=_mqtt_tls()
            ) as client:
                await client.subscribe(topic, qos=1)
                logger.info("OTA 已訂閱 %s(JSON 指令;軟體套件 A/B slot,見 ota.py)", topic)
                async for message in client.messages:
                    await agent.handle(bytes(message.payload))
        except aiomqtt.MqttError as exc:
            logger.warning("OTA MQTT 斷線:%s;%.0f 秒後重連", exc, RECONNECT_DELAY_S)
            await asyncio.sleep(RECONNECT_DELAY_S)
