import { NextRequest, NextResponse } from "next/server";
import { deleteFeedback, updateFeedback } from "@/lib/feedback";
import { hasValidSession } from "@/lib/auth";

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const id = (await params).id;
  if (!/^[a-f0-9]{32}$/.test(id)) return NextResponse.json({ error: "Invalid feedback" }, { status: 400 });
  try {
    const body = await request.json();
    if (body?.status !== "new" && body?.status !== "reviewed") return NextResponse.json({ error: "Invalid status" }, { status: 400 });
    await updateFeedback(id, body.status);
    return NextResponse.json({ updated: true });
  } catch { return NextResponse.json({ error: "Could not update feedback" }, { status: 502 }); }
}

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const id = (await params).id;
  if (!/^[a-f0-9]{32}$/.test(id)) return NextResponse.json({ error: "Invalid feedback" }, { status: 400 });
  try { await deleteFeedback(id); return NextResponse.json({ deleted: true }); }
  catch { return NextResponse.json({ error: "Could not delete feedback" }, { status: 502 }); }
}
