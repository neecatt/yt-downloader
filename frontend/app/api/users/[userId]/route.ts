import { NextRequest, NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { updateUser } from "@/lib/users";
export async function PATCH(request:NextRequest,{params}:{params:Promise<{userId:string}>}){if(!(await hasValidSession()))return NextResponse.json({error:"Unauthorized"},{status:401});const userId=Number((await params).userId);if(!Number.isSafeInteger(userId)||userId<=0)return NextResponse.json({error:"Invalid user"},{status:400});try{return NextResponse.json(await updateUser(userId,await request.json()),{headers:{"Cache-Control":"no-store"}})}catch(error){return NextResponse.json({error:error instanceof Error?error.message:"Update failed"},{status:502})}}
