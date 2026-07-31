import OwnerShell from './OwnerShell';

export default function OwnerLayout({ children }: { children: React.ReactNode }) {
  return <OwnerShell>{children}</OwnerShell>;
}
