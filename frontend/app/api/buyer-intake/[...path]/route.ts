import { NextRequest, NextResponse } from 'next/server';

async function handler(request:NextRequest,context:{params:Promise<{path:string[]}>}){
  const {path}=await context.params;
  const route=path.join('/');
  if(!['snapshot','preview','commit'].includes(route)) return NextResponse.json({detail:'Unsupported route'},{status:404});
  const auth=request.headers.get('authorization');
  if(!auth) return NextResponse.json({detail:'Owner session required'},{status:401});
  const body=request.method==='GET'?undefined:await request.text();
  try{
    const target=new URL(`/api/backend/buyer-intake/${route}`,request.nextUrl.origin);
    const response=await fetch(target,{method:request.method,headers:{Authorization:auth,'Content-Type':'application/json'},body,cache:'no-store',signal:AbortSignal.timeout(30000)});
    const text=await response.text();
    return new NextResponse(text||null,{status:response.status,headers:{'Content-Type':response.headers.get('content-type')||'application/json','Cache-Control':'no-store'}});
  }catch(error){
    return NextResponse.json({detail:`Buyer Intake backend unavailable: ${error instanceof Error?error.message:'request failed'}`},{status:502});
  }
}

export const GET=handler;
export const POST=handler;
