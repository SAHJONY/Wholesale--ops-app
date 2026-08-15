'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';

type NavItem = { href: string; label: string; icon: string; hint?: string };

const command: NavItem[] = [
  { href: '/owner', label: 'Command Center', icon: '⌂', hint: 'Money + next actions' },
  { href: '/owner/deal-factory', label: 'Deal Factory', icon: '✦', hint: 'Nationwide source-backed deal analysis' },
  { href: '/owner/attention', label: 'Action Inbox', icon: '!', hint: 'Approvals + blockers' },
  { href: '/owner/acquisition', label: 'Prospects', icon: '↗', hint: 'Discover + qualify' },
  { href: '/owner/real-deals', label: 'Real Deals', icon: '$', hint: 'Verified $10K+ spread' },
  { href: '/owner/buyer-intake', label: 'Buyers', icon: '◎', hint: 'Buy boxes + proof of funds' },
];

const execution: NavItem[] = [
  { href: '/owner/properties', label: 'Property Workspace', icon: '▣' },
  { href: '/owner/communications', label: 'Seller Conversations', icon: '◌' },
  { href: '/owner/disposition', label: 'Disposition', icon: '◇' },
  { href: '/owner/closing', label: 'Closings', icon: '□' },
];

const intelligence: NavItem[] = [
  { href: '/owner/deal-intelligence', label: 'Underwriting', icon: '⌘' },
  { href: '/owner/lead-verification', label: 'Verification', icon: '⛨' },
  { href: '/owner/markets', label: 'Markets', icon: '⌖' },
  { href: '/owner/live-data', label: 'Data Sources', icon: '◉' },
  { href: '/owner/jobs', label: 'AI Workforce', icon: '↻' },
];

const system: NavItem[] = [
  { href: '/owner/integrations', label: 'Integrations', icon: '+' },
  { href: '/owner/system-health', label: 'System Health', icon: '●' },
  { href: '/owner/audit', label: 'Audit Trail', icon: '≡' },
  { href: '/owner/security', label: 'Admin & Security', icon: '⌾' },
];

const advanced: NavItem[] = [
  { href: '/owner/start', label: 'Start Here', icon: '➤' },
  { href: '/owner/deals', label: 'Legacy Deals View', icon: '◇' },
  { href: '/owner/nationwide-acquisition', label: 'Nationwide Acquisition', icon: '★' },
  { href: '/owner/acquisition-automation', label: 'Acquisition Automation', icon: '↯' },
  { href: '/owner/sms-acquisition', label: 'AI SMS Acquisition', icon: '✦' },
  { href: '/owner/nationwide-data', label: 'Nationwide Data', icon: '✓' },
  { href: '/owner/national-intelligence', label: 'National Intelligence', icon: '◫' },
  { href: '/owner/real-estate-intelligence', label: 'Property Intelligence', icon: '◆' },
  { href: '/owner/county', label: 'County Verification', icon: '▤' },
  { href: '/owner/public-data', label: 'Public Data Providers', icon: '◎' },
  { href: '/owner/provider-activation', label: 'Provider Activation', icon: '⊕' },
  { href: '/owner/intelligence', label: 'Canonical Intelligence', icon: '◈' },
  { href: '/owner/data-intake', label: 'Data Intake', icon: '⇩' },
  { href: '/owner/business', label: 'Business OS', icon: '▦' },
  { href: '/owner/operations', label: 'Operations Console', icon: '⚙' },
  { href: '/owner/activate', label: 'Activation Console', icon: '△' },
  { href: '/owner/events', label: 'Event Core', icon: '⌁' },
  { href: '/owner/go-live', label: 'Go-Live Readiness', icon: '▷' },
  { href: '/owner/launch-validation', label: 'Launch Validation', icon: '✓' },
  { href: '/owner/continuity', label: 'Business Continuity', icon: '∞' },
  { href: '/owner/sessions', label: 'Active Sessions', icon: '⌁' },
  { href: '/owner/test-deal', label: 'Deal Rehearsal', icon: '◇' },
];

function LinkGroup({ label, items, pathname, onNavigate }: { label: string; items: NavItem[]; pathname: string; onNavigate: () => void }) {
  return <section className="ownerNavGroup">
    <span>{label}</span>
    {items.map(item => {
      const active = item.href === '/owner'
        ? pathname === '/owner' || pathname === '/owner/ceo-command'
        : pathname === item.href || pathname.startsWith(`${item.href}/`);
      return <Link key={item.href} href={item.href} className={active ? 'active' : ''} aria-current={active ? 'page' : undefined} onClick={onNavigate} title={item.hint}>
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
      <Link href="/owner" className="ownerBrand"><span>S</span><div><b>SAHJONY</b><small>Wholesale Operating System</small></div></Link>
      <nav aria-label="Owner workspace">
        <LinkGroup label="Operate" items={command} pathname={pathname} onNavigate={() => setOpen(false)} />
        <LinkGroup label="Execute" items={execution} pathname={pathname} onNavigate={() => setOpen(false)} />
        <LinkGroup label="Intelligence" items={intelligence} pathname={pathname} onNavigate={() => setOpen(false)} />
        <LinkGroup label="System" items={system} pathname={pathname} onNavigate={() => setOpen(false)} />
        <details className="ownerNavAdvanced">
          <summary>Advanced tools</summary>
          <LinkGroup label="" items={advanced} pathname={pathname} onNavigate={() => setOpen(false)} />
        </details>
      </nav>
      <footer><span className="ownerLiveDot"/><div><b>Supervised autonomy</b><small>AI prepares · humans authorize</small></div></footer>
    </aside>
  </>;
}
