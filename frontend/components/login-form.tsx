"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export function LoginForm() {
  const [token, setToken] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError("");
    const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, remember }) });
    if (!response.ok) { setError("Invalid token."); return; }
    router.replace("/"); router.refresh();
  }
  return <form onSubmit={submit} className="login-form"><label htmlFor="token">Admin token</label><input id="token" type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="current-password" required /><label className="checkbox-label"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> <span>Remember this device for 30 days</span></label><button className="button" type="submit">Open dashboard</button>{error && <p className="form-error">{error}</p>}</form>;
}
