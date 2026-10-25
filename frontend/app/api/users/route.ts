import { NextRequest, NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { fetchUsers } from "@/lib/users";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const params = request.nextUrl.searchParams;
  const page = Math.max(1, Number(params.get("page")) || 1);
  const pageSize = Math.min(100, Math.max(1, Number(params.get("pageSize")) || 25));
  try {
    return NextResponse.json(
      await fetchUsers(params.get("q") || "", params.get("access") || "", page, pageSize),
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json({ error: "Account service unavailable" }, { status: 502 });
  }
}
