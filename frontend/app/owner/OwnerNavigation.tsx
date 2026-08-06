'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';

type NavItem = { href: string; label: string; icon: string };

const primary: NavItem[] = [
  { href: '/owner/start', label: 'Start here', icon: '➤' },
  { href: '/owner', label: 'CEO command center', icon: '⌂' },
  { href: '/owner/nationwide-acquisition', label: 'Nationwide acquisition', icon: '★' },
  { href: '/owner/acquisition', label: 'Acquisition pipeline', icon: '↗' },
  { href: '/owner/deals', label: 'Deals', icon: '◇' },
  { href: '/owner/communications', label: 'Seller communications', icon: '◌' },
  { href: '/owner/disposition', label: 'Buyer disposition', icon: '◎' },
];

const intelligence: NavItem[] = [
  { href: '/owner/deal-intelligence', label: 'Deal intelligence', icon: '⌘' },
  { href: '/owner/markets', label: 'Market selection', icon: '⌖' },
  { href: '/owner/lead-verification', label: 'Lead verification', icon: '⛨' },
  { href: '/owner/nationwide-data', label: 'Nationwide data', icon: '✓' },
  { href: '/owner/buyer-intake', label: 'Buyer network', icon: '♢' },
];

const operations: NavItem[] = [
  { href: '/owner/operations', label: 'Business operations', icon: '⚙' },
  { href: '/owner/closing', label: 'Closings', icon: '□' },
  { href: '/owner/jobs', label: 'AI workforce', icon: '↻' },
  { href: '/owner/system-health', label: 'System health', icon: '●' },
  { href: '/owner/security', label: 'Administration & security', icon: '⌾' },
];

const advanced: NavItem[] = [
  { href: '/owner/acquisition-automation', label: 'Acquisition automation', icon: '↯' },
  { href: '/owner/audit', label: 'Audit trail', icon: '≡' },
  { href: '/owner/county', label: 'County verification', icon: '▤' },
  { href: '/owner/data-intake', label: 'Data intake', icon: '⇩' },
  { href: '/owner/go-live', label: 'Go-live readiness', icon: '▷' },
  { href: '/owner/intelligence', label: 'Canonical intelligence', icon: '◈' },
  { href: '/owner/launch-validation', label: 'Launch validation', icon: '✓' },
  { href: '/owner/public-data', label: 'Public data providers', icon: '◎' },
  { href: '/owner/sessions', label: 'Active sessions', icon: '⌁' },
];

function LinkGroup({ label, items, pathname, onNavigate }: { label: string; items: NavItem[]; pathname: string; onNavigate: () => void }) {
  return <section className="ownerNavGroup">
    <span>{label}</span>
    {items.map(item => {
      const active = item.href === '/owner' ? pathname === '/owner' : pathname === item.href || pathname.startsWith(`${item.href}/`);
      return <Link key={item.href} href={item.href} className={active ? 'active' : ''} aria-current={active ? 'page' : undefined} onClick={onNavigate}>
        <i aria-hidden="true">{item.icon}</i><span>{item.label}</span>
      </Link>;
    })}
  </section>;
}

export default function OwnerNavigation() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [pathname]);

  return <>
    <header className="ownerMobileBar">
      <Link href="/owner" className="ownerMobileBrand"><span>S</span><b>SAHJONY</b></Link>
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} aria-controls="owner-navigation">
        <span className="srOnly">Toggle navigation</span><i/><i/><i/>
      </button>
    </header>
    {open && <button className="ownerNavScrim" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <aside id="owner-navigation" className={`ownerNav ${open ? 'open' : ''}`}>
      <Link href="/owner" className="ownerBrand"><span>S</span><div><b>SAHJONY</b><small>Wholesale OS</small></div></Link>
      <nav aria-label="Owner workspace">
        <LinkGroup label="Executive workspace" items={primary} pathname={pathname} onNavigate={() => setOpen(false)} />
        <LinkGroup label="Intelligence" items={intelligence} pathname={pathname} onNavigate={() => setOpen(false)} />
        <LinkGroup label="Business operations" items={operations} pathname={pathname} onNavigate={() => setOpen(false)} />
        <LinkGroup label="Advanced & setup" items={advanced} pathname={pathname} onNavigate={() => setOpen(false)} />
      </nav>
      <footer><span className="ownerLiveDot"/><div><b>Supervised autonomy</b><small>Human approval enforced</small></div></footer>
    </aside>
  </>;
}
