const securityHeaders=[
  {key:'X-Content-Type-Options',value:'nosniff'},
  {key:'X-Frame-Options',value:'DENY'},
  {key:'Referrer-Policy',value:'strict-origin-when-cross-origin'},
  {key:'Permissions-Policy',value:'camera=(), microphone=(), geolocation=(), payment=(), usb=()'},
  {key:'Cross-Origin-Opener-Policy',value:'same-origin'},
  {key:'Strict-Transport-Security',value:'max-age=63072000; includeSubDomains; preload'},
  {key:'Content-Security-Policy',value:"default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self' 'unsafe-inline' https://translate.google.com https://translate.googleapis.com; style-src 'self' 'unsafe-inline' https://translate.googleapis.com; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https://translate.googleapis.com https://*.google.com; frame-src https://translate.google.com; upgrade-insecure-requests"},
];
/** @type {import('next').NextConfig} */
const nextConfig={poweredByHeader:false,async headers(){return [{source:'/(.*)',headers:securityHeaders},{source:'/login',headers:[{key:'Cache-Control',value:'private, no-store, max-age=0'}]},{source:'/forgot-password',headers:[{key:'Cache-Control',value:'private, no-store, max-age=0'}]}];}};
export default nextConfig;
