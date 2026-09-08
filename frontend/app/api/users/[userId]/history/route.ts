import { NextRequest, NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { fetchUserHistory } from "@/lib/users";
export async function GET(_:NextRequest,{params}:{params:Promise<{userId:string}>}){if(!(await hasValidSession()))return NextResponse.json({error:"Unauthorized"},{status:401});const userId=Number((await params).userId);if(!Number.isSafeInteger(userId)||userId<=0)return NextResponse.json({error:"Invalid user"},{status:400});try{return NextResponse.json(await fetchUserHistory(userId),{headers:{"Cache-Control":"no-store"}})}catch{return NextResponse.json({error:"History unavailable"},{status:502})}}
