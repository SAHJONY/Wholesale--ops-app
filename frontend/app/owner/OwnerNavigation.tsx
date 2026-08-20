'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

type NavItem = { href: string; label: string; hint?: string };
type NavSpace = { id: string; href: string; label: string; icon: string; hint: string; children?: NavItem[] };

const actionInbox: NavItem = { href: '/owner/attention', label: 'Action Inbox', hint: 'Approvals, exceptions and blockers' };

const spaces: NavSpace[] = [
  { id: 'command', href: '/owner', label: 'Command', icon: '⌂', hint: 'Revenue, pipeline, risk and next actions' },
  {
    id: 'leads', href: '/owner/deal-factory', label: 'Leads', icon: '↗', hint: 'Source, score, verify and qualify opportunities',
    children: [
      { href: '/owner/market-intelligence', label: 'Market Intelligence', hint: 'Nationwide cash-buyer and distress signals' },
      { href: '/owner/acquisition', label: 'Lead Pipeline', hint: 'Off-market prospects and outreach stages' },
      { href: '/owner/market-leads', label: 'Market Leads + Lots', hint: 'On-market motivated listings and vacant land' },
      { href: '/owner/owner-resolution', label: 'Owner Resolution', hint: 'Ownership and contact evidence' },
      { href: '/owner/lead-verification', label: 'Lead Verification', hint: 'Evidence gates before underwriting' },
      { href: '/owner/properties', label: 'Property Evidence', hint: 'Property facts, comps and source records' },
    ],
  },
  {
    id: 'deals', href: '/owner/real-deals', label: 'Deals', icon: '$', hint: 'Underwrite, negotiate, contract and manage economics',
    children: [
      { href: '/owner/deal-intelligence', label: 'Underwriting', hint: 'ARV, repairs, MAO and offer tiers' },
      { href: '/owner/deals', label: 'Contracts & Dossier', hint: 'Contract status, documents and deal file' },
      { href: '/owner/joint-ventures', label: 'Joint Ventures', hint: 'JV intake and shared disposition' },
    ],
  },
  {
    id: 'sellers', href: '/owner/communications', label: 'Sellers', icon: '☎', hint: 'Conversations, qualification and follow-up',
    children: [
      { href: '/owner/communications', label: 'Bland Phone System', hint: 'Inbound/outbound voice operations and readiness' },
      { href: '/owner/phone-os', label: 'Seller Conversations', hint: 'Motivation, timeline, condition, price and memory' },
      { href: '/owner/sms-acquisition', label: 'SMS Campaigns', hint: 'Supervised seller follow-up campaigns' },
    ],
  },
  {
    id: 'buyers', href: '/owner/buyer-intake', label: 'Buyers', icon: '◎', hint: 'Cash buyers, buying boxes, POF and disposition',
    children: [
      { href: '/owner/buyer-intake', label: 'Buyer Network', hint: 'Buyer profiles, proof of funds and buy boxes' },
      { href: '/owner/disposition', label: 'Disposition', hint: 'Deal matching, buyer offers and assignment spread' },
    ],
  },
  {
    id: 'closing', href: '/owner/closing', label: 'Closing', icon: '□', hint: 'Title, assignment, funding and revenue realization',
    children: [
      { href: '/owner/closing', label: 'Closing Pipeline', hint: 'Title, EMD, funding and closing status' },
      { href: '/owner/title-companies', label: 'Title Companies', hint: 'Wholesale-friendly closing partners' },
    ],
  },
];

const controls: NavItem[] = [
  { href: '/owner/system-health', label: 'System Health', hint: 'Production readiness and diagnostics' },
  { href: '/owner/jobs', label: 'AI Workforce', hint: 'Agent health and task execution' },
  { href: '/owner/integrations', label: 'Integrations', hint: 'Providers and credentials status' },
  { href: '/owner/audit', label: 'Audit Trail', hint: 'Consequential action history' },
  { href: '/owner/security', label: 'Security', hint: 'Owner access and controls' },
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
  const [controlsOpen, setControlsOpen] = useState(controls.some(item => routeIsActive(pathname, item.href)));

  useEffect(() => {
    setOpen(false);
    if (activeSpace) setExpanded(activeSpace);
    if (controls.some(item => routeIsActive(pathname, item.href))) setControlsOpen(true);
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
      <Link href="/owner" className="ownerBrand"><span>S</span><div><b>SAHJONY</b><small>Private Wholesale OS</small></div></Link>
      <Link href={actionInbox.href} className={routeIsActive(pathname, actionInbox.href) ? 'ownerNavUtility active' : 'ownerNavUtility'} onClick={() => setOpen(false)}>
        <i aria-hidden="true">!</i><span><b>{actionInbox.label}</b><small>{actionInbox.hint}</small></span><em>→</em>
      </Link>
      <nav aria-label="Wholesale operating system" className="ownerNavSpaces">
        <span className="ownerNavSectionLabel">Business workflow</span>
        {spaces.map(space => {
          const active = spaceIsActive(pathname, space);
          const showChildren = Boolean(space.children?.length) && (expanded === space.id || active);
          return <section className={`ownerNavSpace ${active ? 'active' : ''}`} key={space.id}>
            <div className="ownerNavSpaceRow">
              <Link href={space.href} className="ownerNavSpaceLink" aria-current={routeIsActive(pathname, space.href) ? 'page' : undefined} onClick={() => setOpen(false)} title={space.hint}>
                <i aria-hidden="true">{space.icon}</i><span><b>{space.label}</b><small>{space.hint}</small></span>
              </Link>
              {space.children?.length ? <button type="button" className="ownerNavSpaceToggle" aria-label={`${showChildren ? 'Collapse' : 'Expand'} ${space.label}`} aria-expanded={showChildren} onClick={() => setExpanded(current => current === space.id && !active ? null : space.id)}><span aria-hidden="true">⌄</span></button> : null}
            </div>
            {showChildren ? <div className="ownerNavChildren">{space.children?.map(item => {
              const childActive = routeIsActive(pathname, item.href);
              return <Link key={item.href} href={item.href} className={childActive ? 'active' : ''} aria-current={childActive ? 'page' : undefined} onClick={() => setOpen(false)} title={item.hint}><span>{item.label}</span><i aria-hidden="true">→</i></Link>;
            })}</div> : null}
          </section>;
        })}
        <section className="ownerNavSpace ownerNavControlSpace">
          <div className="ownerNavSpaceRow">
            <button type="button" className="ownerNavSpaceLink ownerNavControlToggle" onClick={() => setControlsOpen(value => !value)} aria-expanded={controlsOpen}>
              <i aria-hidden="true">●</i><span><b>Control</b><small>System, agents, integrations and security</small></span>
            </button>
            <button type="button" className="ownerNavSpaceToggle" aria-label={`${controlsOpen ? 'Collapse' : 'Expand'} Control`} aria-expanded={controlsOpen} onClick={() => setControlsOpen(value => !value)}><span aria-hidden="true">⌄</span></button>
          </div>
          {controlsOpen ? <div className="ownerNavChildren">{controls.map(item => {
            const childActive = routeIsActive(pathname, item.href);
            return <Link key={item.href} href={item.href} className={childActive ? 'active' : ''} aria-current={childActive ? 'page' : undefined} onClick={() => setOpen(false)} title={item.hint}><span>{item.label}</span><i aria-hidden="true">→</i></Link>;
          })}</div> : null}
        </section>
      </nav>
      <footer><span className="ownerLiveDot"/><div><b>Owner-controlled autonomy</b><small>AI prepares · owner authorizes consequential actions</small></div></footer>
    </aside>
  </>;
}
