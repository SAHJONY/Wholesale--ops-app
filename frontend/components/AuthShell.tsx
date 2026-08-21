import Link from 'next/link';
import type { ReactNode } from 'react';

export default function AuthShell({ eyebrow, title, description, children, footer }: { eyebrow: string; title: string; description: string; children: ReactNode; footer?: ReactNode }) {
  return <main className="authExperience">
    <section className="authStory" aria-label="SAHJONY Wholesale OS">
      <div className="authBrand"><span>S</span><div><b>SAHJONY</b><small>WHOLESALE OPERATING SYSTEM</small></div></div>
      <div className="authStoryCopy">
        <span className="authKicker">SUPERVISED REAL ESTATE INTELLIGENCE</span>
        <h2>See the opportunity.<br/><em>Control every action.</em></h2>
        <p>A private command center for acquisition, underwriting, seller communications, buyer disposition, and closing execution.</p>
        <div className="authTrustGrid"><div><strong>Gated</strong><span>External actions</span></div><div><strong>Scoped</strong><span>Business data</span></div><div><strong>Audited</strong><span>Critical decisions</span></div></div>
      </div>
      <div className="authStoryFooter"><i/><span>Private owner workspace</span><b>Encrypted session</b></div>
    </section>
    <section className="authPanel"><div className="authPanelInner">
      <Link href="/login" className="authMobileBrand" aria-label="SAHJONY Wholesale OS"><span>S</span><b>SAHJONY</b></Link>
      <header className="authHeading"><span>{eyebrow}</span><h1>{title}</h1><p>{description}</p></header>
      {children}
      {footer ? <footer className="authPanelFooter">{footer}</footer> : null}
    </div></section>
  </main>;
}
