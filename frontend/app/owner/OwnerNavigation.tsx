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
    id: 'find', href: '/owner/deal-factory', label: 'Find Deals', icon: '↗', hint: 'Source, qualify and verify opportunities',
    children: [
      { href: '/owner/market-intelligence', label: 'Market Intelligence', hint: 'Nationwide cash-buyer heat map' },
      { href: '/owner/acquisition', label: 'Off-Market Prospects' },
      { href: '/owner/market-leads', label: 'Market Leads + Lots', hint: 'On-market motivated listings + vacant land' },
      { href: '/owner/owner-resolution', label: 'Owner Resolution', hint: 'Owner + contact evidence desk' },
      { href: '/owner/lead-verification', label: 'Verification' },
      { href: '/owner/properties', label: 'Property Evidence' },
    ],
  },
  {
    id: 'deal-room', href: '/owner/real-deals', label: 'Deal Room', icon: '$', hint: 'Economics, gates, contracts and execution',
    children: [
      { href: '/owner/deal-intelligence', label: 'Underwriting' },
      { href: '/owner/deals', label: 'Contracts & Dossier' },
      { href: '/owner/joint-ventures', label: 'Joint Ventures', hint: 'Wholesaler JV intake + disposition' },
    ],
  },
  {
    id: 'sellers', href: '/owner/phone-os', label: 'Sellers', icon: '☎', hint: 'Qualification, conversations and follow-up',
    children: [
      { href: '/owner/communications', label: 'Conversations' },
      { href: '/owner/sms-acquisition', label: 'Campaigns' },
    ],
  },
  {
    id: 'buyers', href: '/owner/buyer-intake', label: 'Buyers', icon: '◎', hint: 'Buyer coverage, proof of funds and disposition',
    children: [{ href: '/owner/disposition', label: 'Disposition' }],
  },
  {
    id: 'closing', href: '/owner/closing', label: 'Closing', icon: '□', hint: 'Title, assignment, funding and close',
    children: [{ href: '/owner/title-companies', label: 'Title Companies' }],
  },
  {
    id: 'control', href: '/owner/system-health', label: 'Control', icon: '●', hint: 'System health and owner diagnostics' },
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
      <Link href="/owner" className="ownerBrand"><span>S</span><div><b>SAHJONY</b><small>Deal Operating System</small></div></Link>

      <Link href={actionInbox.href} className={routeIsActive(pathname, actionInbox.href) ? 'ownerNavUtility active' : 'ownerNavUtility'} onClick={() => setOpen(false)}>
        <i aria-hidden="true">!</i><span><b>{actionInbox.label}</b><small>{actionInbox.hint}</small></span><em>→</em>
      </Link>

      <nav aria-label="Deal workflow" className="ownerNavSpaces">
        <span className="ownerNavSectionLabel">Deal workflow</span>
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
