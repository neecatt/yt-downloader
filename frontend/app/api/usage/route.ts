import { NextRequest, NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { fetchUsage } from "@/lib/monetization-admin";
export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) { if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 }); try { return NextResponse.json(await fetchUsage(Number(request.nextUrl.searchParams.get("days")) || 30), { headers: { "Cache-Control": "no-store" } }); } catch { return NextResponse.json({ error: "Usage service unavailable" }, { status: 502 }); } }
