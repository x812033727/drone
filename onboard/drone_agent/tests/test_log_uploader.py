"""log_uploader.py 單元測試(mock log_files 與 httpx):

- 最新 entry 選擇(依 date)與檔名淨化;
- happy path:下載 → multipart 上傳 → 暫存檔清掉;
- 下載逾時放棄(不上傳、不留殘檔、不拋例外);
- 上傳中互斥:再次 disarm 觸發被忽略;
- 未掛 disarm_callback(未設 --log-svc-url 的預設)= 功能不啟動;
  回呼例外不得炸掉 watch_armed。

不需 SITL,也不需 log-svc。
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from drone_agent import log_uploader as mod
from drone_agent.log_uploader import LogUploader, local_filename, pick_latest
from drone_agent.state import TelemetryState, watch_armed


def _entry(id_: int, date: str, size: int = 1024) -> SimpleNamespace:
    return SimpleNamespace(id=id_, date=date, size_bytes=size)


# ---- 純函式:最新 entry 選擇與檔名 ----


def test_pick_latest_by_date() -> None:
    entries = [
        _entry(0, "2026-07-11T01:00:00Z"),
        _entry(2, "2026-07-11T09:30:00Z"),
        _entry(1, "2026-07-11T05:00:00Z"),
    ]
    assert pick_latest(entries).id == 2


def test_pick_latest_empty_returns_none() -> None:
    assert pick_latest([]) is None


def test_local_filename_has_no_colons() -> None:
    name = local_filename("dev-1", "2026-07-11T09:30:00Z")
    assert ":" not in name
    assert name.endswith(".ulg")
    assert name.startswith("dev-1_")


# ---- 測試替身 ----


class _FakeLogFiles:
    """MAVSDK LogFiles 替身:get_entries 可加 gate;download 寫檔並可加延遲。"""

    def __init__(
        self,
        entries: list,
        content: bytes = b"FAKE-ULOG-BYTES",
        download_delay_s: float = 0.0,
        entries_gate: asyncio.Event | None = None,
    ) -> None:
        self.entries = entries
        self.content = content
        self.download_delay_s = download_delay_s
        self.entries_gate = entries_gate
        self.downloaded: list = []

    async def get_entries(self) -> list:
        if self.entries_gate is not None:
            await self.entries_gate.wait()
        return self.entries

    async def download_log_file(self, entry, path: str):
        await asyncio.sleep(self.download_delay_s)
        Path(path).write_bytes(self.content)
        self.downloaded.append(entry)
        yield SimpleNamespace(progress=1.0)


class _FakeResponse:
    status_code = 201

    def raise_for_status(self) -> None:
        pass


class _FakeAsyncClient:
    """httpx.AsyncClient 替身:記錄 post 的 URL 與 multipart 內容。"""

    posts: list = []

    def __init__(self, timeout=None) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url: str, files=None):
        filename, fh, content_type = files["file"]
        _FakeAsyncClient.posts.append((url, filename, fh.read(), content_type))
        return _FakeResponse()


def _make_uploader(log_files: _FakeLogFiles, tmp_path, **kwargs) -> LogUploader:
    drone = SimpleNamespace(log_files=log_files)
    return LogUploader(drone, "dev-1", "http://localhost:8090/", work_dir=tmp_path, **kwargs)


# ---- happy path:下載 → 上傳 → 清暫存 ----


def test_trigger_downloads_and_uploads_latest(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.posts = []
    log_files = _FakeLogFiles(
        [_entry(0, "2026-07-11T01:00:00Z"), _entry(1, "2026-07-11T09:30:00Z")]
    )
    uploader = _make_uploader(log_files, tmp_path)

    async def scenario() -> None:
        task = uploader.trigger()
        assert task is not None
        await task

    asyncio.run(scenario())

    assert [e.id for e in log_files.downloaded] == [1]  # 只下載最新一筆
    url, filename, body, content_type = _FakeAsyncClient.posts[0]
    assert url == "http://localhost:8090/api/v1/logs/dev-1"  # 末尾斜線已淨化
    assert body == b"FAKE-ULOG-BYTES"
    assert content_type == "application/octet-stream"
    assert list(tmp_path.iterdir()) == []  # 暫存檔已清


def test_no_entries_skips_without_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.posts = []
    uploader = _make_uploader(_FakeLogFiles([]), tmp_path)

    async def scenario() -> None:
        await uploader.trigger()

    asyncio.run(scenario())

    assert _FakeAsyncClient.posts == []


# ---- 下載逾時:放棄、不上傳、不留殘檔 ----


def test_download_timeout_gives_up(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.posts = []
    log_files = _FakeLogFiles([_entry(0, "2026-07-11T01:00:00Z")], download_delay_s=30.0)
    uploader = _make_uploader(log_files, tmp_path, download_timeout_s=0.05)

    async def scenario() -> None:
        await uploader.trigger()  # 不得拋例外

    asyncio.run(scenario())

    assert _FakeAsyncClient.posts == []
    assert list(tmp_path.iterdir()) == []


# ---- 互斥:回收進行中再次 disarm 被忽略 ----


def test_second_trigger_while_busy_is_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.posts = []
    gate = asyncio.Event()
    log_files = _FakeLogFiles([_entry(0, "2026-07-11T01:00:00Z")], entries_gate=gate)
    uploader = _make_uploader(log_files, tmp_path)

    async def scenario() -> None:
        first = uploader.trigger()
        await asyncio.sleep(0)  # 讓 task 跑到 get_entries 的 gate
        assert uploader.busy is True
        assert uploader.trigger() is None  # 進行中:忽略
        gate.set()
        await first
        assert uploader.busy is False
        second = uploader.trigger()  # 完成後可再次觸發
        assert second is not None
        await second

    asyncio.run(scenario())
    assert len(_FakeAsyncClient.posts) == 2  # 兩次有效觸發各上傳一次


# ---- disarm 回呼掛載行為(state.watch_armed 端) ----


class _FakeDrone:
    def __init__(self, values: list) -> None:
        async def stream():
            for value in values:
                yield value

        self.telemetry = SimpleNamespace(armed=stream)


def test_disarm_edge_fires_callback_only_on_true_to_false() -> None:
    calls: list[str] = []
    state = TelemetryState()
    state.disarm_callback = lambda: calls.append("disarm")

    asyncio.run(watch_armed(_FakeDrone([False, True, False, True]), state))

    assert calls == ["disarm"]  # 只有 True→False 邊緣;False→True 不觸發


def test_default_no_callback_feature_disabled() -> None:
    """未設 --log-svc-url 時 main 不掛回呼:disarm 邊緣僅產生事件,不觸發回收。"""
    state = TelemetryState()
    assert state.disarm_callback is None
    asyncio.run(watch_armed(_FakeDrone([True, False]), state))  # 不得拋例外
    assert [armed for armed, _ in state.pending_events] == [False]


def test_callback_exception_does_not_kill_watcher() -> None:
    state = TelemetryState()

    def boom() -> None:
        raise RuntimeError("boom")

    state.disarm_callback = boom
    asyncio.run(watch_armed(_FakeDrone([True, False, True]), state))  # 不得拋例外
    assert state.armed is True
