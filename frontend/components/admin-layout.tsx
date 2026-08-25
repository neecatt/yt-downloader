"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

const navigation = [
  { href: "/", label: "Activity", detail: "Usage and logs" },
  { href: "/broadcast", label: "Broadcast", detail: "Message everyone" },
  { href: "/message", label: "Message user", detail: "Contact one user" },
  { href: "/chats", label: "Chats", detail: "View and reply" },
  { href: "/feedback", label: "Feedback", detail: "Review suggestions" },
];

export function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return <div className="admin-app">
    <button className={`sidebar-backdrop${open ? " visible" : ""}`} aria-label="Close menu" onClick={() => setOpen(false)} />
    <aside className={`sidebar${open ? " open" : ""}`}>
      <div className="sidebar-brand"><span className="brand-mark">D</span><div><strong>Downloader</strong><span>Admin console</span></div></div>
      <nav aria-label="Admin navigation">{navigation.map((item) => <Link key={item.href} href={item.href} className={pathname === item.href ? "active" : ""} onClick={() => setOpen(false)}><span>{item.label}</span><small>{item.detail}</small></Link>)}</nav>
      <div className="sidebar-footer">Private workspace</div>
    </aside>
    <div className="admin-content">
      <header className="mobile-topbar"><button className="menu-button" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}><span /><span /><span /></button><span className="mobile-title">Downloader Admin</span></header>
      {children}
    </div>
  </div>;
}
