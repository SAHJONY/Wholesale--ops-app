'use client';

import { usePathname } from 'next/navigation';
import OwnerNavigation from './OwnerNavigation';

const labels: Record<string, string> = {
  '/owner': 'Command Center',
  '/owner/copilot': 'Wholesale Copilot',
  '/owner/deal-factory': 'Deal Factory',
  '/owner/attention': 'Action Inbox',
  '/owner/acquisition': 'Prospects',
  '/owner/real-deals': 'Real Deals',
  '/owner/buyer-intake': 'Buyers',
  '/owner/properties': 'Property Workspace',
  '/owner/phone-os': 'Phone OS',
  '/owner/communications': 'Seller Conversations',
  '/owner/sms-acquisition': 'Campaigns',
  '/owner/disposition': 'Disposition',
  '/owner/closing': 'Closings',
  '/owner/title-companies': 'Title Companies',
  '/owner/deal-intelligence': 'Underwriting',
  '/owner/lead-verification': 'Verification',
  '/owner/markets': 'Markets',
  '/owner/live-data': 'Data Sources',
  '/owner/jobs': 'AI Workforce',
  '/owner/integrations': 'Integrations',
  '/owner/system-health': 'System Health',
  '/owner/audit': 'Audit Trail',
  '/owner/security': 'Admin & Security',
};

function currentLabel(pathname: string) {
  if (labels[pathname]) return labels[pathname];
  const match = Object.keys(labels)
    .filter(path => path !== '/owner' && pathname.startsWith(`${path}/`))
    .sort((a, b) => b.length - a.length)[0];
  return match ? labels[match] : 'Owner Workspace';
}

export default function OwnerShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const showNavigation = pathname === '/owner' || pathname.startsWith('/owner/');
  const label = currentLabel(pathname);

  return <div className={showNavigation ? 'ownerAppShell' : 'ownerAppShell ownerSignedOut'}>
    {showNavigation && <>
      <OwnerNavigation />
      <header className="ownerTopRail" aria-label="Workspace status">
        <div className="ownerTopRailPath">
          <small>SAHJONY / OPERATIONS</small>
          <strong>{label}</strong>
        </div>
        <div className="ownerTopRailStatus"><i aria-hidden="true"/>Live workspace</div>
      </header>
    </>}
    <div className="ownerAppContent">{children}</div>
  </div>;
}
