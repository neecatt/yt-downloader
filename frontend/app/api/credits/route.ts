import { NextRequest, NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { fetchCredits } from "@/lib/monetization-admin";
export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) { if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 }); const p=request.nextUrl.searchParams; try { return NextResponse.json(await fetchCredits(p.get("q")||"", Math.max(1,Number(p.get("page"))||1)), { headers: { "Cache-Control": "no-store" } }); } catch { return NextResponse.json({ error: "Credits service unavailable" }, { status: 502 }); } }
