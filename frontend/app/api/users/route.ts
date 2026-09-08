import { NextRequest, NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { fetchUsers } from "@/lib/users";
export const dynamic="force-dynamic";
export async function GET(request:NextRequest){if(!(await hasValidSession()))return NextResponse.json({error:"Unauthorized"},{status:401});const p=request.nextUrl.searchParams;try{return NextResponse.json(await fetchUsers(p.get("q")||"",p.get("access")||"",Math.max(1,Number(p.get("page"))||1),Math.min(100,Math.max(1,Number(p.get("pageSize"))||25))),{headers:{"Cache-Control":"no-store"}})}catch{return NextResponse.json({error:"Account service unavailable"},{status:502})}}
