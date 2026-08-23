import { redirect } from "next/navigation";
import { MessageComposer } from "@/components/message-composer";
import { hasValidSession, isDashboardConfigured } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function MessagePage() {
  if (!isDashboardConfigured()) redirect("/login");
  if (!(await hasValidSession())) redirect("/login");
  return <MessageComposer mode="user" />;
}
