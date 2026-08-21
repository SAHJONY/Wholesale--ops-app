'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import OwnerNavigation from './OwnerNavigation';

const labels: Record<string, string> = {
  '/owner': 'Command Center',
  '/owner/copilot': 'Wholesale Copilot',
  '/owner/deal-factory': 'Leads Command Center',
  '/owner/attention': 'Action Inbox',
  '/owner/acquisition': 'Lead Pipeline',
  '/owner/real-deals': 'Deal Room',
  '/owner/deals': 'Contracts & Dossier',
  '/owner/buyer-intake': 'Buyer Network',
  '/owner/properties': 'Property Evidence',
  '/owner/phone-os': 'Seller Conversations',
  '/owner/communications': 'Seller Command',
  '/owner/sms-acquisition': 'SMS Campaigns',
  '/owner/disposition': 'Disposition',
  '/owner/closing': 'Closing Command',
  '/owner/title-companies': 'Title Companies',
  '/owner/deal-intelligence': 'Underwriting',
  '/owner/lead-verification': 'Lead Verification',
  '/owner/markets': 'Markets',
  '/owner/market-intelligence': 'Market Intelligence',
  '/owner/market-leads': 'Market Leads + Lots',
  '/owner/owner-resolution': 'Owner Resolution',
  '/owner/live-data': 'Data Sources',
  '/owner/jobs': 'AI Workforce',
  '/owner/integrations': 'Integrations',
  '/owner/system-health': 'System Health',
  '/owner/audit': 'Audit Trail',
  '/owner/security': 'Admin & Security',
  '/owner/joint-ventures': 'Joint Ventures',
};

type WorkspaceHealth = 'checking' | 'live' | 'degraded' | 'offline';
type VersionPayload = { status?: string; backend_transport?: string; detail?: string | null };

function currentLabel(pathname: string) {
  if (labels[pathname]) return labels[pathname];
  const match = Object.keys(labels)
    .filter(path => path !== '/owner' && pathname.startsWith(`${path}/`))
    .sort((a, b) => b.length - a.length)[0];
  return match ? labels[match] : 'Owner Workspace';
}

function healthLabel(health: WorkspaceHealth) {
  if (health === 'live') return 'Live';
  if (health === 'degraded') return 'Degraded';
  if (health === 'offline') return 'Offline';
  return 'Checking';
}

export default function OwnerShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const showNavigation = pathname === '/owner' || pathname.startsWith('/owner/');
  const label = currentLabel(pathname);
  const [health, setHealth] = useState<WorkspaceHealth>('checking');
  const [healthDetail, setHealthDetail] = useState('Verifying frontend/backend synchronization');

  useEffect(() => {
    if (!showNavigation) return;
    const handleOwnerLink = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest('a[href]') as HTMLAnchorElement | null;
      if (!anchor || anchor.target || anchor.hasAttribute('download')) return;
      const href = anchor.getAttribute('href');
      if (!href || !href.startsWith('/owner')) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      event.preventDefault();
      router.push(`${url.pathname}${url.search}${url.hash}`);
    };
    document.addEventListener('click', handleOwnerLink);
    return () => document.removeEventListener('click', handleOwnerLink);
  }, [router, showNavigation]);

  useEffect(() => {
    if (!showNavigation) return;
    let cancelled = false;

    async function checkHealth() {
      try {
        const response = await fetch('/api/version', { cache: 'no-store' });
        const payload = await response.json().catch(() => ({})) as VersionPayload;
        if (cancelled) return;
        if (response.ok && payload.status === 'in_sync' && payload.backend_transport === 'vercel_service_binding') {
          setHealth('live');
          setHealthDetail('Frontend and backend are synchronized through Vercel Services');
          return;
        }
        if (response.ok && payload.status !== 'backend_unreachable') {
          setHealth('degraded');
          setHealthDetail(payload.detail || 'Workspace is reachable but release synchronization is not fully proven');
          return;
        }
        setHealth('offline');
        setHealthDetail(payload.detail || 'Backend health is unavailable');
      } catch (error) {
        if (cancelled) return;
        setHealth('offline');
        setHealthDetail(error instanceof Error ? error.message : 'Workspace health request failed');
      }
    }

    void checkHealth();
    const timer = window.setInterval(() => void checkHealth(), 60_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [showNavigation]);

  return <div className={showNavigation ? 'ownerAppShell' : 'ownerAppShell ownerSignedOut'}>
    {showNavigation ? <>
      <OwnerNavigation />
      <header className="ownerTopRail" aria-label="Workspace status">
        <div className="ownerTopRailPath"><small>SAHJONY / PRIVATE WHOLESALE OS</small><strong>{label}</strong></div>
        <Link href="/owner/system-health" className={`ownerTopRailStatus ${health}`} title={healthDetail} aria-label={`Workspace status: ${healthLabel(health)}. ${healthDetail}`}>
          <i aria-hidden="true"/><span>{healthLabel(health)} workspace</span>
        </Link>
      </header>
    </> : null}
    <div className="ownerAppContent">{children}</div>
  </div>;
}
