import Link from 'next/link';
import type { ReactNode } from 'react';
import styles from './subnav.module.css';

export default function SmsAcquisitionLayout({ children }: { children: ReactNode }) {
  return <>
    <nav className={styles.subnav} aria-label="SAHJONY AI Acquisition">
      <strong>SAHJONY AI Acquisition</strong>
      <Link href="/owner/sms-acquisition">Overview</Link>
      <Link href="/owner/sms-acquisition/campaigns">Campaigns</Link>
      <Link href="/owner/sms-acquisition/scheduling">Scheduling</Link>
      <Link href="/owner/communications">Bland communications</Link>
    </nav>
    {children}
  </>;
}
