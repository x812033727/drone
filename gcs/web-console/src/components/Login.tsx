import { useState } from "react";

type Props = { onSubmit: (token: string) => void };

// 極簡登入:貼上 JWT(dev)。生產 OIDC 可換成 IdP redirect。
export function Login({ onSubmit }: Props) {
  const [token, setLocalToken] = useState("");
  return (
    <div className="login-overlay">
      <form
        className="login-box"
        onSubmit={(e) => {
          e.preventDefault();
          if (token.trim()) onSubmit(token.trim());
        }}
      >
        <h2>需要登入</h2>
        <p>此環境已啟用 API 認證。貼上具 viewer 以上角色的 JWT:</p>
        <textarea
          value={token}
          onChange={(e) => setLocalToken(e.target.value)}
          placeholder="eyJhbGciOi..."
          rows={4}
          autoFocus
        />
        <button type="submit" disabled={!token.trim()}>
          登入
        </button>
      </form>
    </div>
  );
}
