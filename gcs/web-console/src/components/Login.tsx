import { useState } from "react";
import { beginLogin, oidcEnabled } from "../oidc";

type Props = { onSubmit: (token: string) => void };

// 登入:OIDC SSO(授權碼+PKCE,VITE_OIDC_* 設定時)或貼上 JWT(dev/後援)。
export function Login({ onSubmit }: Props) {
  const [token, setLocalToken] = useState("");
  return (
    <div className="login-overlay">
      <div className="login-box">
        <h2>需要登入</h2>
        {oidcEnabled() && (
          <>
            <p>用單一登入(SSO)認證:</p>
            <button type="button" onClick={() => void beginLogin()}>
              以 SSO 登入
            </button>
            <p className="or">或貼上具 viewer 以上角色的 JWT:</p>
          </>
        )}
        {!oidcEnabled() && <p>此環境已啟用 API 認證。貼上具 viewer 以上角色的 JWT:</p>}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (token.trim()) onSubmit(token.trim());
          }}
        >
          <textarea
            value={token}
            onChange={(e) => setLocalToken(e.target.value)}
            placeholder="eyJhbGciOi..."
            rows={4}
          />
          <button type="submit" disabled={!token.trim()}>
            登入
          </button>
        </form>
      </div>
    </div>
  );
}
