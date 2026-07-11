"""ULog 自動回收:disarm 觸發 → MAVLink 下載最新日誌 → HTTP 上傳 log-svc。

S20 閉環的機上端(雲端見 cloud/log_svc/):main 組裝時把 LogUploader.trigger
掛到 TelemetryState.disarm_callback,armed True→False 邊緣即背景啟動:

    disarm → log_files.get_entries()(取 date 最新一筆)
           → download_log_file()(MAVLink 下載到暫存;SITL 檔小、實機大檔慢,
             加總逾時 --log-download-timeout 預設 300 s,逾時放棄記 log)
           → POST multipart 至 {--log-svc-url}/api/v1/logs/{drone_id}

Phase 0 邊界(README「ULog 自動回收」節):
- 預設關閉:未給 --log-svc-url 整個功能不啟動;
- 全程獨立 task,絕不阻塞遙測(trigger 只 create_task 就返回);
- 上傳進行中再次 disarm:忽略並記 log(單一回收互斥,不排隊);
- 任何失敗(下載/上傳)記 log 後放棄,無重試佇列。
"""

import asyncio
import logging
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

#: MAVLink 日誌下載加總逾時預設(秒);實機大檔經數傳可能極慢,逾時放棄
DEFAULT_DOWNLOAD_TIMEOUT_S = 300.0

#: HTTP 上傳逾時(秒);log-svc 在同內網,收檔為串流寫入
UPLOAD_TIMEOUT_S = 60.0


def pick_latest(entries: list) -> object | None:
    """從 log_files.get_entries() 結果挑最新一筆(依 date;ISO 8601 字串可字典序比較)。"""
    if not entries:
        return None
    return max(entries, key=lambda e: e.date)


def local_filename(drone_id: str, entry_date: str) -> str:
    """暫存/上傳檔名:{drone_id}_{entry date 換掉冒號}.ulg(原始 entry 無檔名,只有 date)。"""
    return f"{drone_id}_{entry_date.replace(':', '-')}.ulg"


class LogUploader:
    """disarm 觸發的 ULog 下載+上傳(單一回收互斥;失敗放棄無重試)。"""

    def __init__(
        self,
        drone,
        drone_id: str,
        log_svc_url: str,
        download_timeout_s: float = DEFAULT_DOWNLOAD_TIMEOUT_S,
        work_dir: str | Path | None = None,
    ) -> None:
        self._drone = drone
        self._drone_id = drone_id
        self._base_url = log_svc_url.rstrip("/")
        self._download_timeout_s = download_timeout_s
        self._work_dir = Path(work_dir) if work_dir is not None else Path(tempfile.gettempdir())
        self._task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        """是否有回收進行中(互斥判定)。"""
        return self._task is not None and not self._task.done()

    def trigger(self) -> asyncio.Task | None:
        """disarm 回呼:背景啟動回收後立即返回(不阻塞遙測)。

        進行中再次觸發:忽略並記 log(Phase 0 不排隊)。回傳建立的 task
        (被忽略時 None),供測試/關機收尾用。
        """
        if self.busy:
            logger.warning("ULog 回收進行中,忽略此次 disarm 觸發(Phase 0 不排隊)")
            return None
        self._task = asyncio.create_task(self._run(), name="ulog-upload")
        return self._task

    async def _run(self) -> None:
        """回收主流程;任何失敗記 log 後放棄(絕不外拋炸掉事件迴圈)。"""
        try:
            await self._collect_and_upload()
        except Exception:
            logger.exception("ULog 回收失敗,放棄本次(Phase 0 無重試佇列)")

    async def _collect_and_upload(self) -> None:
        entries = await self._drone.log_files.get_entries()
        entry = pick_latest(entries)
        if entry is None:
            logger.warning("飛控無日誌 entry,略過本次回收")
            return
        local_path = self._work_dir / local_filename(self._drone_id, entry.date)
        logger.info(
            "下載 ULog:entry id=%s date=%s size=%d bytes → %s",
            entry.id,
            entry.date,
            entry.size_bytes,
            local_path,
        )
        try:
            await asyncio.wait_for(
                self._download(entry, local_path), timeout=self._download_timeout_s
            )
        except asyncio.TimeoutError:
            logger.error(
                "ULog 下載逾時(%.0f 秒,已下載部分丟棄),放棄本次回收",
                self._download_timeout_s,
            )
            local_path.unlink(missing_ok=True)
            return
        size = local_path.stat().st_size
        logger.info("ULog 下載完成:%s(%d bytes),開始上傳", local_path.name, size)
        try:
            await self._upload(local_path)
        finally:
            local_path.unlink(missing_ok=True)

    async def _download(self, entry, path: Path) -> None:
        """消化 MAVSDK 下載進度流直到完成(download_log_file 是 async generator)。"""
        async for _progress in self._drone.log_files.download_log_file(entry, str(path)):
            pass

    async def _upload(self, path: Path) -> None:
        url = f"{self._base_url}/api/v1/logs/{self._drone_id}"
        async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT_S) as client:
            with path.open("rb") as fh:
                response = await client.post(
                    url, files={"file": (path.name, fh, "application/octet-stream")}
                )
            response.raise_for_status()
        logger.info("ULog 已上傳:%s → %s(HTTP %d)", path.name, url, response.status_code)
