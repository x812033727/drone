import { createContext, useCallback, useContext, useRef, useState } from "react";
import type { ReactNode } from "react";

// 輕量 toast/告警系統:低電量、離線、任務 FAILED 等事件的視覺提示。
// 沿用現有 hooks 風格,不引入外部狀態庫。

export type ToastKind = "info" | "warn" | "error";

type Toast = { id: number; kind: ToastKind; message: string };

type ToastApi = {
  // 推一則 toast;dedupeKey 相同者在存活期間不重複(避免每次輪詢刷屏)。
  push: (kind: ToastKind, message: string, dedupeKey?: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

const AUTO_DISMISS_MS = 6000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const liveKeys = useRef<Set<string>>(new Set());

  const remove = useCallback((id: number, key?: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    if (key) liveKeys.current.delete(key);
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string, dedupeKey?: string) => {
      if (dedupeKey) {
        if (liveKeys.current.has(dedupeKey)) return;
        liveKeys.current.add(dedupeKey);
      }
      const id = nextId.current++;
      setToasts((prev) => [...prev, { id, kind, message }]);
      setTimeout(() => remove(id, dedupeKey), AUTO_DISMISS_MS);
    },
    [remove],
  );

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="toast-stack">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} onClick={() => remove(t.id)}>
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToasts(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToasts 必須在 ToastProvider 內使用");
  return ctx;
}
