import Link from 'next/link';
export default function NotFoundPage(){return <main className="systemState"><section><span>404 · ROUTE NOT FOUND</span><h1>This workspace does not exist.</h1><p>The requested operational route may have moved or may not be available to this workspace.</p><div><Link href="/owner">Command center</Link><Link href="/login">Secure sign in</Link></div></section></main>;}
