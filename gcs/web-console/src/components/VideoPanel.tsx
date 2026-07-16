// 即時影像面板:原生 WHEP(WebRTC-HTTP Egress)訂閱 MediaMTX 的 drone/<serial> 流。
// 刻意零依賴(RTCPeerConnection + fetch);串流命名慣例 drone/<serial> 見
// cloud/deploy/compose/mediamtx/mediamtx.yml。
// 認證:Phase 0 internal-users 模式用 config.videoAuth(user:pass,dev 用途);
// fleet JWT 認證橋(authMethod http)由後續 PR 接上後改帶 token。
import { useCallback, useEffect, useRef, useState } from "react";
import { config } from "../config";

interface Props {
  serial: string | null;
}

type PlayState = "idle" | "connecting" | "playing" | "error";

export function VideoPanel({ serial }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const sessionRef = useRef<string | null>(null); // WHEP session URL(DELETE 用)
  const [state, setState] = useState<PlayState>("idle");
  const [error, setError] = useState<string | null>(null);

  const stop = useCallback(() => {
    pcRef.current?.close();
    pcRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    const session = sessionRef.current;
    sessionRef.current = null;
    if (session) {
      // best-effort 收尾;失敗無妨(mediamtx 會以 ICE 逾時回收 session)
      fetch(session, { method: "DELETE", headers: authHeaders() }).catch(() => {});
    }
    setState("idle");
  }, []);

  // 換機或卸載時自動停播
  useEffect(() => stop, [serial, stop]);

  const play = useCallback(async () => {
    if (!serial) return;
    setError(null);
    setState("connecting");
    try {
      const pc = new RTCPeerConnection();
      pcRef.current = pc;
      pc.addTransceiver("video", { direction: "recvonly" });
      pc.ontrack = (ev) => {
        if (videoRef.current) videoRef.current.srcObject = ev.streams[0];
      };
      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "connected") setState("playing");
        if (pc.connectionState === "failed") {
          setError("媒體連線失敗(ICE);跨機觀看需 webrtcAdditionalHosts,見 runbook");
          setState("error");
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitIceComplete(pc);

      const whepUrl = `${videoBase()}/drone/${encodeURIComponent(serial)}/whep`;
      const resp = await fetch(whepUrl, {
        method: "POST",
        headers: { "Content-Type": "application/sdp", ...authHeaders() },
        body: pc.localDescription?.sdp ?? offer.sdp,
      });
      if (resp.status !== 201) {
        throw new Error(
          resp.status === 401 || resp.status === 400
            ? `影像認證失敗(HTTP ${resp.status})`
            : `WHEP 信令失敗(HTTP ${resp.status};機上未推流時為 404)`,
        );
      }
      // Location 為 mediamtx 根路徑相對值;經反代後以 videoBase 前綴解析
      const loc = resp.headers.get("Location");
      if (loc) {
        sessionRef.current = loc.startsWith("http")
          ? loc
          : `${videoBase()}${loc.startsWith("/") ? "" : "/"}${loc}`;
      }
      await pc.setRemoteDescription({ type: "answer", sdp: await resp.text() });
    } catch (e) {
      pcRef.current?.close();
      pcRef.current = null;
      setError(e instanceof Error ? e.message : String(e));
      setState("error");
    }
  }, [serial]);

  if (!serial) return null;

  return (
    <div className="video-panel">
      <div className="video-panel-header">
        <span>即時影像 — {serial}</span>
        {state === "playing" || state === "connecting" ? (
          <button onClick={stop}>停止</button>
        ) : (
          <button onClick={play}>播放</button>
        )}
      </div>
      {state !== "idle" && (
        <video ref={videoRef} autoPlay playsInline muted className="video-panel-video" />
      )}
      {state === "connecting" && <div className="video-panel-hint">連線中…</div>}
      {state === "error" && <div className="video-panel-error">{error}</div>}
    </div>
  );
}

function videoBase(): string {
  return (config.videoBase ?? "/video").replace(/\/$/, "");
}

function authHeaders(): Record<string, string> {
  // Phase 0(internal users):dev 部署可經 runtime config 注入讀取帳密。
  // JWT 認證橋接上後,這裡改為附掛 fleet token(?jwt= / Bearer)。
  if (config.videoAuth) return { Authorization: `Basic ${btoa(config.videoAuth)}` };
  return {};
}

function waitIceComplete(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const check = () => {
      if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", check);
    // 保險:2 秒後直接送(non-trickle 下 mediamtx 也接受部分 candidate)
    setTimeout(() => {
      pc.removeEventListener("icegatheringstatechange", check);
      resolve();
    }, 2000);
  });
}
