"""ota.py 單元測試:指令解析、SHA-256/Ed25519 驗簽、斷點續傳、A/B slot、健康檢查回滾、
進度回報、pause/resume/rollback。

全程 fake/注入(RangeFetcher、HealthCheck、記憶體公私鑰),不需真網路/真 flash/MQTT。
"""

import asyncio
import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from drone_agent import ota
from drone_agent.ota import (
    OtaAgent,
    OtaCommand,
    OtaError,
    SlotManager,
    download_resumable,
    load_public_key,
    parse_ota_command,
    progress_dict,
    sha256_file,
    sha256_hex,
    verify_artifact,
    verify_signature,
)

# ---------------------------------------------------------------------------
# 測試用 Ed25519 金鑰 + 簽章工具
# ---------------------------------------------------------------------------


def _keypair():
    sk = Ed25519PrivateKey.generate()
    return sk, sk.public_key()


def _sign_digest(sk, content: bytes) -> str:
    """對內容的 SHA-256 摘要(32 bytes)簽章,回 base64(對齊 verify_artifact 語意)。"""
    digest = hashlib.sha256(content).digest()
    return base64.b64encode(sk.sign(digest)).decode()


def _install_cmd(content: bytes, sk, update_id="ota-1", version="1.4.0", url="https://x/pkg"):
    return OtaCommand(
        action="install",
        update_id=update_id,
        component="onboard",
        version=version,
        url=url,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        signature=_sign_digest(sk, content),
    )


class WholeFetcher:
    """RangeFetcher fake:自 start 位移一次串流完內容(不模擬斷線)。"""

    def __init__(self, content: bytes, chunk: int = 8):
        self.content = content
        self.chunk = chunk
        self.calls: list[int] = []

    async def __call__(self, url, start):
        self.calls.append(start)
        pos = start
        while pos < len(self.content):
            piece = self.content[pos : pos + self.chunk]
            yield piece
            pos += len(piece)


class FlakyFetcher:
    """RangeFetcher fake:第一次串到 fail_at 位元組即拋 ConnectionError(模擬斷線),
    後續呼叫自 start 續傳到完成。calls 記錄每次的 start offset。"""

    def __init__(self, content: bytes, fail_at: int, fail_times: int = 1, chunk: int = 8):
        self.content = content
        self.fail_at = fail_at
        self.fail_times = fail_times
        self.chunk = chunk
        self.calls: list[int] = []

    async def __call__(self, url, start):
        self.calls.append(start)
        pos = start
        while pos < len(self.content):
            if self.fail_times > 0 and pos >= self.fail_at:
                self.fail_times -= 1
                raise ConnectionError("模擬下載斷線")
            piece = self.content[pos : pos + self.chunk]
            yield piece
            pos += len(piece)


def _agent(tmp_path, sk_pub, report, fetch, health=None, **kw):
    slots = SlotManager(tmp_path / "ota")
    slots.ensure_layout()
    kwargs = dict(
        drone_id="dev-1",
        work_dir=tmp_path / "work",
        slots=slots,
        public_key=sk_pub,
        report=report,
        fetch_range=fetch,
    )
    if health is not None:
        kwargs["health_check"] = health
    kwargs.update(kw)
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)
    return OtaAgent(**kwargs), slots


def _recorder():
    events: list[dict] = []

    async def report(ev: dict) -> None:
        events.append(ev)

    return events, report


def _states(events):
    return [e["state"] for e in events]


# ---------------------------------------------------------------------------
# parse_ota_command
# ---------------------------------------------------------------------------


def test_parse_install_full():
    sk, _ = _keypair()
    content = b"pkg-bytes"
    payload = json.dumps(
        {
            "action": "install",
            "update_id": "ota-1",
            "component": "onboard",
            "version": "1.4.0",
            "url": "https://m/pkg",
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "signature": _sign_digest(sk, content),
        }
    )
    cmd = parse_ota_command(payload.encode())
    assert cmd.action == "install"
    assert cmd.update_id == "ota-1"
    assert cmd.component == "onboard"
    assert cmd.version == "1.4.0"


def test_parse_control_needs_only_action_and_id():
    cmd = parse_ota_command(b'{"action": "pause", "update_id": "ota-1"}')
    assert cmd.action == "pause"
    assert cmd.update_id == "ota-1"


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",  # 非物件
        b'{"action": "install", "update_id": "x"}',  # install 缺欄位
        b'{"action": "bogus", "update_id": "x"}',  # 未知 action
        b'{"action": "pause"}',  # 缺 update_id
        b'{"action": "install", "update_id": "x", "component": "o", "version": "1",'
        b' "url": "u", "sha256": "zz", "signature": "s"}',  # sha256 非 hex
    ],
)
def test_parse_rejects(payload):
    with pytest.raises(ValueError):
        parse_ota_command(payload)


def test_parse_rejects_non_utf8():
    with pytest.raises(ValueError, match="UTF-8"):
        parse_ota_command(b"\xff\xfe")


# ---------------------------------------------------------------------------
# SHA-256 + Ed25519 驗簽
# ---------------------------------------------------------------------------


def test_sha256_hex_and_file(tmp_path):
    data = b"hello ota"
    p = tmp_path / "a.bin"
    p.write_bytes(data)
    assert sha256_hex(data) == hashlib.sha256(data).hexdigest()
    assert sha256_file(p) == hashlib.sha256(data).hexdigest()


def test_verify_signature_good_and_bad():
    sk, pk = _keypair()
    digest = hashlib.sha256(b"content").digest()
    good = base64.b64encode(sk.sign(digest)).decode()
    assert verify_signature(digest, good, pk) is True
    # 換一把公鑰驗 → 失敗
    _, other_pub = _keypair()
    assert verify_signature(digest, good, other_pub) is False


def test_verify_signature_bad_base64_returns_false_not_raises():
    _, pk = _keypair()
    digest = hashlib.sha256(b"content").digest()
    assert verify_signature(digest, "!!!not-base64!!!", pk) is False


def test_verify_signature_tampered_digest_rejected():
    sk, pk = _keypair()
    good = base64.b64encode(sk.sign(hashlib.sha256(b"orig").digest())).decode()
    tampered = hashlib.sha256(b"tampered").digest()
    assert verify_signature(tampered, good, pk) is False


def test_verify_artifact_good(tmp_path):
    sk, pk = _keypair()
    content = b"a-real-package"
    p = tmp_path / "pkg"
    p.write_bytes(content)
    # 不應拋出
    verify_artifact(p, hashlib.sha256(content).hexdigest(), _sign_digest(sk, content), pk)


def test_verify_artifact_bad_sha256_rejected(tmp_path):
    sk, pk = _keypair()
    content = b"a-real-package"
    p = tmp_path / "pkg"
    p.write_bytes(content)
    with pytest.raises(OtaError) as ei:
        verify_artifact(p, "0" * 64, _sign_digest(sk, content), pk)
    assert ei.value.state == ota.STATE_REJECTED


def test_verify_artifact_bad_signature_rejected(tmp_path):
    sk, pk = _keypair()
    other_sk, _ = _keypair()
    content = b"a-real-package"
    p = tmp_path / "pkg"
    p.write_bytes(content)
    # sha256 正確但簽章由別把私鑰簽 → 驗簽失敗
    with pytest.raises(OtaError) as ei:
        verify_artifact(
            p, hashlib.sha256(content).hexdigest(), _sign_digest(other_sk, content), pk
        )
    assert ei.value.state == ota.STATE_REJECTED


def test_load_public_key_roundtrip(tmp_path):
    sk, pk = _keypair()
    pem = pk.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    f = tmp_path / "pub.pem"
    f.write_bytes(pem)
    loaded = load_public_key(f)
    digest = hashlib.sha256(b"x").digest()
    sig = base64.b64encode(sk.sign(digest)).decode()
    assert verify_signature(digest, sig, loaded) is True


# ---------------------------------------------------------------------------
# 斷點續傳下載
# ---------------------------------------------------------------------------


def test_download_no_interruption(tmp_path):
    content = b"0123456789" * 5  # 50 bytes
    dest = tmp_path / "d.pkg"
    fetch = WholeFetcher(content, chunk=8)

    async def scenario():
        total = await download_resumable("u", dest, fetch)
        assert total == len(content)
        assert dest.read_bytes() == content
        assert sha256_file(dest) == hashlib.sha256(content).hexdigest()
        assert not dest.with_suffix(".pkg.part").exists()  # .part 已 rename
        assert fetch.calls == [0]  # 一次下載完成

    asyncio.run(scenario())


def test_download_resumes_after_disconnect(tmp_path, monkeypatch):
    monkeypatch.setattr(ota, "RETRY_DELAY_S", 0)
    """斷線後自已收位元組續傳,不重頭來;最終內容/雜湊正確。"""
    content = bytes(range(256)) * 4  # 1024 bytes
    dest = tmp_path / "d.pkg"
    fetch = FlakyFetcher(content, fail_at=400, fail_times=1, chunk=64)

    async def scenario():
        total = await download_resumable("u", dest, fetch, max_retries=3)
        assert total == len(content)
        assert dest.read_bytes() == content
        # 第一次 start=0(斷線),第二次自已收位元組續傳(start > 0,非 0 = 沒重頭)
        assert fetch.calls[0] == 0
        assert len(fetch.calls) == 2
        assert fetch.calls[1] > 0
        # fail_at=400:pos 檢查在 yield 前,pos=448(7*64)時才 >=400 拋,故已收 448 bytes
        assert fetch.calls[1] == 448

    asyncio.run(scenario())


def test_download_gives_up_after_max_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(ota, "RETRY_DELAY_S", 0)
    content = b"x" * 200
    dest = tmp_path / "d.pkg"
    fetch = FlakyFetcher(content, fail_at=50, fail_times=99, chunk=25)  # 每次都斷

    async def scenario():
        with pytest.raises(OtaError) as ei:
            await download_resumable("u", dest, fetch, max_retries=2)
        assert ei.value.state == ota.STATE_FAILED

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# A/B slot(SlotManager)
# ---------------------------------------------------------------------------


def test_slot_layout_and_active_standby(tmp_path):
    sm = SlotManager(tmp_path / "ota")
    sm.ensure_layout()
    assert sm.active_slot() == "a"
    assert sm.standby_slot() == "b"
    assert (sm.slots_dir / "a").is_dir()
    assert (sm.slots_dir / "b").is_dir()
    assert sm.current_link.is_symlink()


def test_slot_stage_commit_switches_active(tmp_path):
    sm = SlotManager(tmp_path / "ota")
    sm.ensure_layout()
    artifact = tmp_path / "pkg.bin"
    artifact.write_bytes(b"new-version-bytes")
    standby = sm.standby_slot()  # "b"
    dest = sm.stage(artifact, "1.4.0")
    assert (dest / "VERSION").read_text() == "1.4.0"
    assert (dest / "pkg.bin").read_bytes() == b"new-version-bytes"
    sm.commit(standby)
    assert sm.active_slot() == "b"
    assert sm.standby_slot() == "a"
    # current symlink 實指向 slots/b
    assert (sm.current_link / "VERSION").read_text() == "1.4.0"


def test_slot_rollback_switches_back(tmp_path):
    sm = SlotManager(tmp_path / "ota")
    sm.ensure_layout()
    sm.commit("b")
    assert sm.active_slot() == "b"
    sm.rollback("a")
    assert sm.active_slot() == "a"


def test_slot_stage_clears_previous_standby_content(tmp_path):
    sm = SlotManager(tmp_path / "ota")
    sm.ensure_layout()
    stale = sm.slots_dir / "b" / "stale.txt"
    stale.write_text("old")
    (sm.slots_dir / "b" / "subdir").mkdir()
    (sm.slots_dir / "b" / "subdir" / "nested").write_text("x")
    artifact = tmp_path / "pkg.bin"
    artifact.write_bytes(b"fresh")
    sm.stage(artifact, "2.0.0")
    assert not stale.exists()
    assert not (sm.slots_dir / "b" / "subdir").exists()
    assert (sm.slots_dir / "b" / "VERSION").read_text() == "2.0.0"


# ---------------------------------------------------------------------------
# OtaAgent 全流程:install 成功 / 健康檢查失敗回滾 / 驗簽拒絕 / fail-closed / 去重 / 暫停
# ---------------------------------------------------------------------------


def test_install_success_commits_and_reports(tmp_path):
    sk, pk = _keypair()
    content = b"good-package-payload"
    events, report = _recorder()
    fetch = WholeFetcher(content)
    agent, slots = _agent(tmp_path, pk, report, fetch)  # 預設 health_check 檢查 VERSION

    async def scenario():
        cmd = _install_cmd(content, sk)
        await agent.handle(json.dumps(cmd.__dict__).encode())
        assert slots.active_slot() == "b"  # 切到新 slot 並提交
        assert (slots.current_link / "VERSION").read_text() == "1.4.0"
        st = _states(events)
        assert st[0] == ota.STATE_RECEIVED
        assert ota.STATE_COMPLETED == st[-1]
        assert ota.STATE_DOWNLOADING in st
        assert ota.STATE_VERIFYING in st
        assert ota.STATE_HEALTH_CHECK in st
        assert agent.current_update_id is None  # 互斥釋放
        assert agent.last_terminal == "ota-1"

    asyncio.run(scenario())


def test_health_check_failure_triggers_rollback(tmp_path):
    sk, pk = _keypair()
    content = b"payload"
    events, report = _recorder()

    async def failing_health(cmd, slot_path):
        return False

    agent, slots = _agent(tmp_path, pk, report, WholeFetcher(content), health=failing_health)

    async def scenario():
        assert slots.active_slot() == "a"
        cmd = _install_cmd(content, sk)
        await agent.handle(json.dumps(cmd.__dict__).encode())
        # 健康檢查失敗 → current 切回舊 slot a
        assert slots.active_slot() == "a"
        assert _states(events)[-1] == ota.STATE_ROLLED_BACK

    asyncio.run(scenario())


def test_bad_signature_rejected_never_touches_slot(tmp_path):
    sk, pk = _keypair()
    other_sk, _ = _keypair()
    content = b"payload"
    events, report = _recorder()
    agent, slots = _agent(tmp_path, pk, report, WholeFetcher(content))

    async def scenario():
        # sha256 正確但簽章來自別把私鑰
        cmd = OtaCommand(
            action="install",
            update_id="ota-bad",
            component="onboard",
            version="9.9.9",
            url="https://m/pkg",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            signature=_sign_digest(other_sk, content),
        )
        await agent.handle(json.dumps(cmd.__dict__).encode())
        assert _states(events)[-1] == ota.STATE_REJECTED
        assert slots.active_slot() == "a"  # 未切換、未套用
        assert not (slots.slots_dir / "b" / "VERSION").exists()

    asyncio.run(scenario())


def test_fail_closed_when_no_public_key(tmp_path):
    sk, _ = _keypair()
    content = b"payload"
    events, report = _recorder()
    agent, slots = _agent(tmp_path, None, report, WholeFetcher(content))  # 無公鑰

    async def scenario():
        cmd = _install_cmd(content, sk)
        await agent.handle(json.dumps(cmd.__dict__).encode())
        assert _states(events) == [ota.STATE_REJECTED]  # 直接拒絕,不下載
        assert slots.active_slot() == "a"

    asyncio.run(scenario())


def test_install_resumes_download_then_completes(tmp_path, monkeypatch):
    monkeypatch.setattr(ota, "RETRY_DELAY_S", 0)
    """全流程含斷點續傳:下載中斷 → 續傳 → 驗簽 → 套用 → 提交。"""
    sk, pk = _keypair()
    content = bytes(range(256)) * 8  # 2048 bytes
    events, report = _recorder()
    fetch = FlakyFetcher(content, fail_at=500, fail_times=1, chunk=128)
    agent, slots = _agent(tmp_path, pk, report, fetch, max_retries=3)

    async def scenario():
        cmd = _install_cmd(content, sk, version="3.1.0")
        await agent.handle(json.dumps(cmd.__dict__).encode())
        assert _states(events)[-1] == ota.STATE_COMPLETED
        assert len(fetch.calls) == 2  # 斷一次、續傳一次
        assert (slots.current_link / "VERSION").read_text() == "3.1.0"

    asyncio.run(scenario())


def test_dedup_running_and_terminal(tmp_path):
    sk, pk = _keypair()
    content = b"payload"
    events, report = _recorder()
    agent, slots = _agent(tmp_path, pk, report, WholeFetcher(content))

    async def scenario():
        cmd = _install_cmd(content, sk)
        payload = json.dumps(cmd.__dict__).encode()
        await agent.handle(payload)  # 首次:完成
        assert agent.last_terminal == "ota-1"
        n = len(events)
        # 遲到重投同 id → 忽略,不再產生事件、不重裝
        await agent.handle(payload)
        assert len(events) == n

    asyncio.run(scenario())


def test_reject_when_another_update_running(tmp_path):
    sk, pk = _keypair()
    content = b"payload"
    events, report = _recorder()
    agent, slots = _agent(tmp_path, pk, report, WholeFetcher(content))

    async def scenario():
        # 手動把 agent 置於「進行中」狀態,模擬併發第二筆
        agent.current_update_id = "ota-running"
        cmd = _install_cmd(content, sk, update_id="ota-new")
        await agent.handle(json.dumps(cmd.__dict__).encode())
        assert _states(events) == [ota.STATE_REJECTED]
        assert events[-1]["update_id"] == "ota-new"

    asyncio.run(scenario())


def test_pause_resume_and_rollback_commands(tmp_path):
    sk, pk = _keypair()
    events, report = _recorder()
    agent, slots = _agent(tmp_path, pk, report, WholeFetcher(b"x"))

    async def scenario():
        await agent.handle(b'{"action": "pause", "update_id": "ota-1"}')
        assert agent.paused is True
        assert _states(events)[-1] == ota.STATE_PAUSED

        await agent.handle(b'{"action": "resume", "update_id": "ota-1"}')
        assert agent.paused is False
        assert _states(events)[-1] == ota.STATE_RESUMED

        # 先提交一個新 slot,再 rollback 應切回
        slots.commit("b")
        assert slots.active_slot() == "b"
        await agent.handle(b'{"action": "rollback", "update_id": "ota-1"}')
        assert slots.active_slot() == "a"
        assert _states(events)[-1] == ota.STATE_ROLLED_BACK

    asyncio.run(scenario())


def test_pause_aborts_in_flight_download(tmp_path):
    """暫停旗標於下載中生效:install 中途暫停 → 中止下載,回報 PAUSED(現場暫停下載)。"""
    sk, pk = _keypair()
    content = b"0123456789" * 20  # 200 bytes
    events, report = _recorder()

    # fetcher 在 yield 前把 agent 暫停,使 download_resumable 於下一塊中止
    agent_holder = {}

    class PausingFetcher:
        def __init__(self):
            self.calls = []

        async def __call__(self, url, start):
            self.calls.append(start)
            pos = start
            while pos < len(content):
                # 第一塊之後觸發暫停
                if pos >= 20:
                    agent_holder["agent"]._paused = True
                yield content[pos : pos + 10]
                pos += 10

    agent, slots = _agent(tmp_path, pk, report, PausingFetcher())
    agent_holder["agent"] = agent

    async def scenario():
        cmd = _install_cmd(content, sk)
        await agent.handle(json.dumps(cmd.__dict__).encode())
        assert _states(events)[-1] == ota.STATE_PAUSED
        assert slots.active_slot() == "a"  # 未套用

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# progress_dict
# ---------------------------------------------------------------------------


def test_progress_dict_shape():
    cmd = OtaCommand(action="install", update_id="ota-9", component="onboard", version="1.0.0")
    d = progress_dict(cmd, ota.STATE_COMPLETED, 1_752_000_000_000, detail="ok")
    assert d == {
        "update_id": "ota-9",
        "component": "onboard",
        "version": "1.0.0",
        "state": "COMPLETED",
        "unix_time_ms": 1_752_000_000_000,
        "detail": "ok",
    }
