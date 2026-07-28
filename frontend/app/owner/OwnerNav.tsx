'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import styles from './owner.module.css';

const SESSION_STORAGE = 'sahjony_owner_session';

/**
 * Every owner route, grouped by what the operator is doing.
 *
 * Nine of these previously had no inbound link from anywhere in the app and
 * were reachable only by typing the URL, including the console's own control
 * plane at /owner, which linked to none of its sub-pages.
 */
const SECTIONS: { title: string; links: { href: string; label: string }[] }[] = [
  {
    title: 'Command',
    links: [
      { href: '/owner', label: 'Control Plane' },
      { href: '/owner/attention', label: 'Needs Attention' },
      { href: '/owner/operations', label: 'Operations' },
    ],
  },
  {
    title: 'Acquisition',
    links: [
      { href: '/owner/acquisition', label: 'Lead Intake' },
      { href: '/owner/acquisition-automation', label: 'Acquisition Automation' },
      { href: '/owner/data-intake', label: 'Data Intake' },
      { href: '/owner/buyer-intake', label: 'Buyer Intake' },
      { href: '/owner/county', label: 'Ownership Verification' },
      { href: '/owner/lead-verification', label: 'Lead Verification' },
    ],
  },
  {
    title: 'Deals',
    links: [
      { href: '/owner/deals', label: 'Deals' },
      { href: '/owner/disposition', label: 'Disposition' },
      { href: '/owner/closing', label: 'Closing' },
      { href: '/owner/test-deal', label: 'Deal Rehearsal' },
    ],
  },
  {
    title: 'Intelligence & Data',
    links: [
      { href: '/owner/markets', label: 'Market Selection' },
      { href: '/owner/intelligence', label: 'Intelligence' },
      { href: '/owner/national-intelligence', label: 'Property Network' },
      { href: '/owner/real-estate-intelligence', label: 'Integrated Platform' },
      { href: '/owner/nationwide-data', label: 'Nationwide Context' },
      { href: '/owner/public-data', label: 'Public & Open Data' },
      { href: '/owner/provider-activation', label: 'Provider Activation' },
    ],
  },
  {
    title: 'Operations',
    links: [
      { href: '/owner/jobs', label: 'Jobs' },
      { href: '/owner/events', label: 'Events' },
      { href: '/owner/communications', label: 'Communications' },
      { href: '/owner/continuity', label: 'Backup & Recovery' },
    ],
  },
  {
    title: 'Platform',
    links: [
      { href: '/owner/system-health', label: 'System Health' },
      { href: '/owner/security', label: 'Security' },
      { href: '/owner/sessions', label: 'Device Sessions' },
      { href: '/owner/audit', label: 'Audit' },
      { href: '/owner/integrations', label: 'Integrations' },
      { href: '/owner/go-live', label: 'Go-Live' },
      { href: '/owner/launch-validation', label: 'Launch Validation' },
      { href: '/owner/activate', label: 'Activation' },
    ],
  },
];

export default function OwnerNav() {
  const pathname = usePathname();
  // localStorage is read after mount so the server-rendered markup matches the
  // first client render; the nav is hidden until we know a session exists,
  // which keeps it off the sign-in card.
  const [signedIn, setSignedIn] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      setSignedIn(Boolean(window.localStorage.getItem(SESSION_STORAGE)));
    } catch {
      setSignedIn(false);
    }
  }, [pathname]);

  if (!signedIn) return null;

  const current = SECTIONS.flatMap(section => section.links).find(link => link.href === pathname);

  return (
    <nav className={styles.ownerNav} aria-label="Owner console">
      <div className={styles.ownerNavBar}>
        <button
          type="button"
          className={styles.ownerNavToggle}
          onClick={() => setOpen(value => !value)}
          aria-expanded={open}
        >
          {open ? 'Close' : 'All pages'}
        </button>
        <span className={styles.ownerNavCurrent}>{current?.label ?? 'Owner Console'}</span>
      </div>

      {open && (
        <div className={styles.ownerNavPanel}>
          {SECTIONS.map(section => (
            <div key={section.title} className={styles.ownerNavGroup}>
              <h2>{section.title}</h2>
              <ul>
                {section.links.map(link => (
                  <li key={link.href}>
                    <a
                      href={link.href}
                      className={link.href === pathname ? styles.ownerNavActive : undefined}
                      aria-current={link.href === pathname ? 'page' : undefined}
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </nav>
  );
}
