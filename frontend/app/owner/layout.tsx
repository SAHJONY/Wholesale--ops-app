import OwnerNav from './OwnerNav';

/**
 * Wraps every owner route so the page directory is reachable from all of them,
 * rather than each page hardcoding a couple of ad-hoc links to its neighbours.
 */
export default function OwnerLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <OwnerNav />
      {children}
    </>
  );
}
