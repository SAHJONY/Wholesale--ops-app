import { redirect } from 'next/navigation';
import type { ReactNode } from 'react';

export default function SmsAcquisitionDisabledLayout({ children: _children }: { children: ReactNode }) {
  redirect('/owner/communications');
}
