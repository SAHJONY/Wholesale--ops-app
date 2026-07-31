'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import OwnerNavigation from './OwnerNavigation';

const SESSION = 'sahjony_owner_session';

export default function OwnerShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    const sync = () => setAuthenticated(Boolean(window.localStorage.getItem(SESSION)));
    sync();
    window.addEventListener('storage', sync);
    const interval = window.setInterval(sync, 750);
    return () => { window.removeEventListener('storage', sync); window.clearInterval(interval); };
  }, []);

  const showNavigation = authenticated || pathname !== '/owner';
  return <div className={showNavigation ? 'ownerAppShell' : 'ownerAppShell ownerSignedOut'}>
    {showNavigation && <OwnerNavigation />}
    <div className="ownerAppContent">{children}</div>
  </div>;
}
