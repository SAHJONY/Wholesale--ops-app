'use client';

import { usePathname } from 'next/navigation';
import OwnerNavigation from './OwnerNavigation';

export default function OwnerShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const showNavigation = pathname === '/owner' || pathname.startsWith('/owner/');
  return <div className={showNavigation ? 'ownerAppShell' : 'ownerAppShell ownerSignedOut'}>
    {showNavigation && <OwnerNavigation />}
    <div className="ownerAppContent">{children}</div>
  </div>;
}
