'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

type NavItem = { href: string; label: string; hint?: string };
type NavSpace = { id: string; href: string; label: string; icon: string; hint: string; children?: NavItem[] };

const actionInbox: NavItem = { href: '/owner/attention', label: 'Action Inbox', hint: 'Approvals + blockers' };

const spaces: NavSpace[] = [
  { id: 'command', href: '/owner', label: 'Command', icon: '⌂', hint: 'Money, risk and next actions' },
  {
    id: 'acquisition', href: '/owner/deal-factory', label: 'Acquisition', icon: '↗', hint: 'Source and verify opportunities',
    children: [
      { href: '/owner/acquisition', label: 'Prospects' },
      { href: '/owner/lead-verification', label: 'Verification' },
      { href: '/owner/properties', label: 'Property Workspace' },
    ],
  },
  {
    id: 'deals', href: '/owner/real-deals', label: 'Deals', icon: '$', hint: 'Verified economics and exit execution',
    children: [
      { href: '/owner/deal-intelligence', label: 'Underwriting' },
      { href: '/owner/disposition', label: 'Disposition' },
    ],
  },
  {
    id: 'communications', href: '/owner/phone-os', label: 'Communications', icon: '☎', hint: 'Seller calls, conversations and campaigns',
    children: [
      { href: '/owner/communications', label: 'Seller Conversations' },
      { href: '/owner/sms-acquisition', label: 'Campaigns' },
    ],
  },
  { id: 'buyers', href: '/owner/buyer-intake', label: 'Buyers', icon: '◎', hint: 'Buy boxes and proof of funds' },
  {
    id: 'closing', href: '/owner/closing', label: 'Closing', icon: '□', hint: 'Title, assignment and funding',
    children: [{ href: '/owner/title-companies', label: 'Title Companies' }],
  },
  {
    id: 'intelligence', href: '/owner/markets', label: 'Intelligence', icon: '⌖', hint: 'Markets and source reliability',
    children: [{ href: '/owner/live-data', label: 'Data Sources' }],
  },
  {
    id: 'ai', href: '/owner/jobs', label: 'AI', icon: 'AI', hint: 'Agent workforce and research tools',
    children: [{ href: '/owner/copilot', label: 'Wholesale Copilot' }],
  },
  {
    id: 'system', href: '/owner/system-health', label: 'System', icon: '●', hint: 'Integrations, audit and security',
    children: [
      { href: '/owner/integrations', label: 'Integrations' },
      { href: '/owner/audit', label: 'Audit Trail' },
      { href: '/owner/security', label: 'Admin & Security' },
    ],
  },
];

function routeIsActive(pathname: string, href: string) {
  if (href === '/owner') return pathname === '/owner' || pathname === '/owner/ceo-command';
  return pathname === href || pathname.startsWith(`${href}/`);
}

function spaceIsActive(pathname: string, space: NavSpace) {
  return routeIsActive(pathname, space.href) || Boolean(space.children?.some(item => routeIsActive(pathname, item.href)));
}

export default function OwnerNavigation() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const activeSpace = useMemo(() => spaces.find(space => spaceIsActive(pathname, space))?.id ?? null, [pathname]);
  const [expanded, setExpanded] = useState<string | null>(activeSpace);

  useEffect(() => {
    setOpen(false);
    if (activeSpace) setExpanded(activeSpace);
  }, [pathname, activeSpace]);

  return <>
    <header className="ownerMobileBar">
      <Link href="/owner" className="ownerMobileBrand"><span>S</span><b>SAHJONY</b></Link>
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} aria-controls="owner-navigation">
        <span className="srOnly">Toggle navigation</span><i/><i/><i/>
      </button>
    </header>
    {open ? <button className="ownerNavScrim" aria-label="Close navigation" onClick={() => setOpen(false)} /> : null}
    <aside id="owner-navigation" className={`ownerNav ownerNavV3 ${open ? 'open' : ''}`}>
      <Link href="/owner" className="ownerBrand"><span>S</span><div><b>SAHJONY</b><small>Wholesale Operating System</small></div></Link>

      <Link href={actionInbox.href} className={routeIsActive(pathname, actionInbox.href) ? 'ownerNavUtility active' : 'ownerNavUtility'} onClick={() => setOpen(false)}>
        <i aria-hidden="true">!</i><span><b>{actionInbox.label}</b><small>{actionInbox.hint}</small></span><em>→</em>
      </Link>

      <nav aria-label="Owner workspace" className="ownerNavSpaces">
        <span className="ownerNavSectionLabel">Operating spaces</span>
        {spaces.map(space => {
          const active = spaceIsActive(pathname, space);
          const showChildren = Boolean(space.children?.length) && (expanded === space.id || active);
          return <section className={`ownerNavSpace ${active ? 'active' : ''}`} key={space.id}>
            <div className="ownerNavSpaceRow">
              <Link href={space.href} className="ownerNavSpaceLink" aria-current={routeIsActive(pathname, space.href) ? 'page' : undefined} onClick={() => setOpen(false)} title={space.hint}>
                <i aria-hidden="true">{space.icon}</i><span><b>{space.label}</b><small>{space.hint}</small></span>
              </Link>
              {space.children?.length ? <button type="button" className="ownerNavSpaceToggle" aria-label={`${showChildren ? 'Collapse' : 'Expand'} ${space.label}`} aria-expanded={showChildren} onClick={() => setExpanded(current => current === space.id && !active ? null : space.id)}>
                <span aria-hidden="true">⌄</span>
              </button> : null}
            </div>
            {showChildren ? <div className="ownerNavChildren">
              {space.children?.map(item => {
                const childActive = routeIsActive(pathname, item.href);
                return <Link key={item.href} href={item.href} className={childActive ? 'active' : ''} aria-current={childActive ? 'page' : undefined} onClick={() => setOpen(false)}>
                  <span>{item.label}</span><i aria-hidden="true">→</i>
                </Link>;
              })}
            </div> : null}
          </section>;
        })}
      </nav>

      <footer><span className="ownerLiveDot"/><div><b>Supervised autonomy</b><small>AI prepares · humans authorize</small></div></footer>
    </aside>
  </>;
}
