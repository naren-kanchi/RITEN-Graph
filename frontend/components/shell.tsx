"use client";
import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api, Row, useApi } from "@/lib/api";

type Session = { user: Row | null; includeSynthetic: boolean };
const SessionContext = createContext<Session>({ user: null, includeSynthetic: true });
export const useSession = () => useContext(SessionContext);

const NAV: { group?: string; href: string; label: string; admin?: boolean }[] = [
  { href: "/", label: "Overview" },
  { group: "Explore", href: "/actors", label: "Actors" },
  { href: "/trade", label: "Trade flows" },
  { href: "/restrictions", label: "Restrictions" },
  { href: "/infrastructure", label: "AI infrastructure" },
  { href: "/companies", label: "Companies" },
  { group: "Analyse", href: "/graph", label: "Graph explorer" },
  { href: "/reports", label: "Reports" },
  { group: "Work", href: "/curation", label: "Curation" },
  { href: "/admin", label: "Administration", admin: true },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const me = useApi<Row>(pathname === "/login" ? null : "/auth/me");
  const [includeSynthetic, setIncludeSynthetic] = useState(true);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("riten_include_synthetic");
      if (stored !== null) setIncludeSynthetic(stored === "true");
    } catch { /* storage may be blocked; the default still works */ }
  }, []);

  if (pathname === "/login") return <>{children}</>;

  function toggle(value: boolean) {
    setIncludeSynthetic(value);
    try { localStorage.setItem("riten_include_synthetic", String(value)); } catch { /* per-viewer convenience only */ }
  }

  async function signOut() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.assign("/login");
  }

  const user = me.data;
  return (
    <SessionContext.Provider value={{ user, includeSynthetic }}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <strong>RITEN-GRAPH</strong>
            <span>Historical data, 2015–2025. Not live.</span>
          </div>
          <nav className="nav" aria-label="Main">
            {NAV.filter((item) => !item.admin || user?.role === "admin").map((item) => (
              <span key={item.href} style={{ display: "contents" }}>
                {item.group && <span className="nav-group">{item.group}</span>}
                <Link href={item.href} aria-current={pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href)) ? "page" : undefined}>
                  {item.label}
                </Link>
              </span>
            ))}
          </nav>
          <div className="side-foot">
            <label className="check" style={{ color: "var(--sidebar-ink)" }}>
              <input type="checkbox" checked={includeSynthetic} onChange={(e) => toggle(e.target.checked)} />
              Include synthetic rows
            </label>
            {user && <span>{user.username} · {user.role === "admin" ? "Administrator" : "Analyst"}</span>}
            <button onClick={signOut}>Sign out</button>
          </div>
        </aside>
        <main className="main">{children}</main>
      </div>
    </SessionContext.Provider>
  );
}
