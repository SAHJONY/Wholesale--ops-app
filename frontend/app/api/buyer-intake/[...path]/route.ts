import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

async function handler(request:NextRequest,context:{params:Promise<{path:string[]}>}){
  const {path}=await context.params;
  const route=path.join('/');
  if(!['snapshot','preview','commit'].includes(route)) return NextResponse.json({detail:'Unsupported route'},{status:404});
  const auth=request.headers.get('authorization');
  if(!auth) return NextResponse.json({detail:'Owner session required'},{status:401});
  const body=request.method==='GET'?undefined:await request.text();
  try{
    const response=await fetch(`${BACKEND}/buyer-intake/${route}`,{method:request.method,headers:{Authorization:auth,'Content-Type':'application/json'},body,cache:'no-store',signal:AbortSignal.timeout(30000)});
    if(response.status===404&&route==='snapshot') return NextResponse.json({status:'setup',required_columns:['name','phone','zip_codes'],optional_columns:[],max_rows:5000,texas_excluded:true,imports:[]});
    if(response.status===404) return NextResponse.json({detail:'Buyer Intake API is not deployed yet. Redeploy the latest backend.'},{status:503});
    const text=await response.text();
    return new NextResponse(text||null,{status:response.status,headers:{'Content-Type':response.headers.get('content-type')||'application/json'}});
  }catch(error){
    return NextResponse.json({detail:`Buyer Intake backend unavailable: ${error instanceof Error?error.message:'request failed'}`},{status:502});
  }
}

export const GET=handler;
export const POST=handler;
