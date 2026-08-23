"use client";

import { FormEvent, useState } from "react";
import { AdminLayout } from "@/components/admin-layout";

type ComposerMode = "broadcast" | "user";

export function MessageComposer({ mode }: { mode: ComposerMode }) {
  const isBroadcast = mode === "broadcast";
  const [username, setUsername] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setResult("");
    setSending(true);
    const response = await fetch(isBroadcast ? "/api/broadcast" : "/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(isBroadcast ? { message } : { username, message }),
    });
    const data = await response.json().catch(() => null);
    if (response.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (!response.ok) {
      setError(data?.error || "The message could not be sent.");
      setSending(false);
      return;
    }
    setResult(isBroadcast
      ? `Sent to ${data.sent} of ${data.targeted} users${data.failed ? ` · ${data.failed} failed` : ""}.`
      : `Message sent to ${data.username}${data.failed ? ` · ${data.failed} delivery failed` : ""}.`);
    setMessage("");
    setSending(false);
  }

  return <AdminLayout><main className="dashboard-shell narrow-shell">
    <header className="topbar"><div><p className="eyebrow">Bot messaging</p><h1>{isBroadcast ? "Broadcast" : "Message a user"}</h1><p className="page-intro">{isBroadcast ? "Send one message to every private chat known to the bot." : "Send a private message to a user who has interacted with the bot."}</p></div></header>
    <section className="composer-card panel">
      <div className="composer-heading"><div><span className="section-kicker">{isBroadcast ? "Reach your audience" : "Direct conversation"}</span><h2>{isBroadcast ? "Compose broadcast" : "Compose direct message"}</h2></div><span className="safe-badge">Admin only</span></div>
      {isBroadcast && <div className="notice"><strong>Before sending</strong><span>Broadcasts go to all recorded private chats. Users who have never started the bot cannot be contacted.</span></div>}
      <form className="composer-form" onSubmit={submit}>
        {!isBroadcast && <label>Telegram username<input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="@username" pattern="@?[A-Za-z0-9_]{5,32}" maxLength={33} required /></label>}
        <label>Message<textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder={isBroadcast ? "Write an update for your users…" : "Write your message…"} maxLength={4096} rows={8} required /><span className="character-count">{message.length} / 4096</span></label>
        {error && <p className="form-error">{error}</p>}
        {result && <p className="form-success">{result}</p>}
        <div className="composer-actions"><span className="muted">Messages are sent through Telegram.</span><button className="button" type="submit" disabled={sending}>{sending ? "Sending…" : isBroadcast ? "Send broadcast" : "Send message"}</button></div>
      </form>
    </section>
  </main></AdminLayout>;
}
