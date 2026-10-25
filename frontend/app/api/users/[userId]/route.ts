import { NextRequest, NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { updateUser } from "@/lib/users";

type UserUpdate = Parameters<typeof updateUser>[1];

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ userId: string }> }) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const userId = Number((await params).userId);
  if (!Number.isSafeInteger(userId) || userId <= 0) return NextResponse.json({ error: "Invalid user" }, { status: 400 });
  let payload: UserUpdate;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }
  try {
    return NextResponse.json(await updateUser(userId, payload), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    // The admin API returns actionable validation details (for example a missing reason).
    return NextResponse.json({ error: error instanceof Error ? error.message : "Update failed" }, { status: 502 });
  }
}
