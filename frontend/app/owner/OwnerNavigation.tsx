'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';

type NavItem = { href: string; label: string; icon: string };

const primary: NavItem[] = [
  { href: '/owner', label: 'CEO command center', icon: '⌂' },
  { href: '/owner/attention', label: 'Attention', icon: '!' },
  { href: '/owner/acquisition', label: 'Acquisition pipeline', icon: '↗' },
  { href: '/owner/deals', label: 'Deals', icon: '◇' },
  { href: '/owner/communications', label: 'Seller communications', icon: '◌' },
  { href: '/owner/disposition', label: 'Buyer disposition', icon: '◎' },
];

const intelligence: NavItem[] = [
  { href: '/owner/real-estate-intelligence', label: 'Property intelligence', icon: '◆' },
  { href: '/owner/nationwide-data', label: 'Nationwide data', icon: '✓' },
  { href: '/owner/national-intelligence', label: 'Market intelligence', icon: '◫' },
  { href: '/owner/buyer-intake', label: 'Buyer network', icon: '♢' },
];

const operations: NavItem[] = [
  { href: '/owner/operations', label: 'Business operations', icon: '⚙' },
  { href: '/owner/closing', label: 'Closings', icon: '□' },
  { href: '/owner/jobs', label: 'AI workforce', icon: '↻' },
  { href: '/owner/integrations', label: 'Integrations', icon: '+' },
  { href: '/owner/system-health', label: 'System health', icon: '●' },
  { href: '/owner/security', label: 'Administration & security', icon: '⌾' },
];

function LinkGroup({ label, items, pathname, onNavigate }: { label: string; items: NavItem[]; pathname: string; onNavigate: () => void }) {
  return <section className="ownerNavGroup">
    <span>{label}</span>
    {items.map(item => {
      const active = item.href === '/owner' ? pathname === '/owner' || pathname === '/owner/ceo-command' : pathname === item.href || pathname.startsWith(`${item.href}/`);
      return <a key={item.href} href={item.href} className={active ? 'active' : ''} aria-current={active ? 'page' : undefined} onClick={onNavigate}>
        <i aria-hidden="true">{item.icon}</i><span>{item.label}</span>
      </a>;
    })}
  </section>;
}

export default function OwnerNavigation() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [pathname]);

  return <>
    <header className="ownerMobileBar">
      <a href="/owner" className="ownerMobileBrand"><span>S</span><b>SAHJONY</b></a>
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} aria-controls="owner-navigation">
        <span className="srOnly">Toggle navigation</span><i/><i/><i/>
      </button>
    </header>
    {open && <button className="ownerNavScrim" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <aside id="owner-navigation" className={`ownerNav ${open ? 'open' : ''}`}>
      <a href="/owner" className="ownerBrand"><span>S</span><div><b>SAHJONY</b><small>Wholesale OS</small></div></a>
      <nav aria-label="Owner workspace">
        <LinkGroup label="Executive workspace" items={primary} pathname={pathname} onNavigate={() => setOpen(false)} />
        <LinkGroup label="Intelligence" items={intelligence} pathname={pathname} onNavigate={() => setOpen(false)} />
        <LinkGroup label="Business operations" items={operations} pathname={pathname} onNavigate={() => setOpen(false)} />
      </nav>
      <footer><span className="ownerLiveDot"/><div><b>Supervised autonomy</b><small>Human approval enforced</small></div></footer>
    </aside>
  </>;
}
