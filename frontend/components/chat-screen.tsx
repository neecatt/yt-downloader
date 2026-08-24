"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AdminLayout } from "@/components/admin-layout";
import type { ChatMessage, Conversation } from "@/lib/chats";

function when(value: string | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

export function ChatScreen() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);

  const refreshConversations = useCallback(async () => {
    const response = await fetch(`/api/chats?q=${encodeURIComponent(query)}`, { cache: "no-store" });
    if (response.status === 401) { window.location.href = "/login"; return; }
    if (!response.ok) throw new Error("Could not load conversations");
    const data = await response.json() as { conversations: Conversation[] };
    setConversations(data.conversations);
    setSelected((current) => current ?? data.conversations[0]?.chatId ?? null);
    setLoading(false);
  }, [query]);

  const refreshMessages = useCallback(async () => {
    if (selected === null) return;
    const response = await fetch(`/api/chats/${encodeURIComponent(selected)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load messages");
    const data = await response.json() as { messages: ChatMessage[] };
    setMessages(data.messages);
    await fetch(`/api/chats/${encodeURIComponent(selected)}/read`, { method: "POST" });
  }, [selected]);

  useEffect(() => {
    let active = true;
    refreshConversations().catch(() => active && setError("Chat service is unavailable."));
    const timer = window.setInterval(() => refreshConversations().catch(() => undefined), 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [refreshConversations]);

  useEffect(() => {
    setMessages([]);
    refreshMessages().catch(() => setError("Could not load this conversation."));
    if (selected === null) return;
    const timer = window.setInterval(() => refreshMessages().catch(() => undefined), 3000);
    return () => window.clearInterval(timer);
  }, [selected, refreshMessages]);

  const current = useMemo(() => conversations.find((item) => item.chatId === selected) || null, [conversations, selected]);

  async function send(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null || !draft.trim()) return;
    setSending(true); setError("");
    const response = await fetch(`/api/chats/${encodeURIComponent(selected)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: draft }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) setError(data?.error || "Could not send message.");
    else { setDraft(""); await refreshMessages(); await refreshConversations(); }
    setSending(false);
  }

  return <AdminLayout><main className="dashboard-shell chat-shell">
    <header className="topbar"><div><p className="eyebrow">Bot messaging</p><h1>Chats</h1><p className="page-intro">Reply to people who have contacted the bot.</p></div></header>
    <section className="chat-layout panel">
      <aside className="conversation-list">
        <div className="chat-search"><input aria-label="Search chats" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search chats…" /></div>
        {loading && <p className="chat-empty">Loading chats…</p>}
        {!loading && !conversations.length && <p className="chat-empty">No conversations yet.</p>}
        {conversations.map((conversation) => <button key={conversation.chatId} className={`conversation-item${selected === conversation.chatId ? " active" : ""}`} onClick={() => setSelected(conversation.chatId)}>
          <span className="conversation-top"><strong>{conversation.username || conversation.displayName || "Unnamed user"}</strong>{conversation.unreadCount > 0 && <b>{conversation.unreadCount}</b>}</span>
          <span className="muted">{conversation.lastText || "No messages"}</span><small>{when(conversation.lastMessageAt)}</small>
        </button>)}
      </aside>
      <div className="chat-panel">
        {current ? <>
          <header className="chat-header"><div><strong>{current.username || current.displayName || "Unnamed user"}</strong><span>{current.displayName && current.username ? current.displayName : "Private bot chat"}</span></div><small>{when(current.lastMessageAt)}</small></header>
          <div className="chat-messages">{messages.map((message) => <div key={message.id} className={`chat-bubble ${message.direction}`}><p>{message.text}</p><small>{when(message.createdAt)}{!message.delivered && " · failed"}</small></div>)}</div>
          <form className="chat-compose" onSubmit={send}><textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Write a reply…" maxLength={4096} rows={2} /><button className="button" type="submit" disabled={sending || !draft.trim()}>{sending ? "Sending…" : "Send"}</button></form>
        </> : <div className="chat-empty large">Select a conversation to view messages.</div>}
        {error && <p className="form-error chat-error">{error}</p>}
      </div>
    </section>
  </main></AdminLayout>;
}
