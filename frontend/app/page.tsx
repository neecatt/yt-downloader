import { redirect } from "next/navigation";
import { Dashboard } from "@/components/dashboard";
import { fetchActivity } from "@/lib/activity";
import { hasValidSession, isDashboardConfigured } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function Page() {
  if (!isDashboardConfigured()) {
    return <main className="center-page"><section className="login-card"><p className="eyebrow">Downloader admin</p><h1>Dashboard setup required</h1><p>Set <code>ADMIN_DASHBOARD_TOKEN</code> in the frontend service before opening the dashboard.</p></section></main>;
  }
  if (!(await hasValidSession())) redirect("/login");
  let initialData;
  try { initialData = await fetchActivity(); } catch { initialData = null; }
  return <Dashboard initialData={initialData} />;
}
