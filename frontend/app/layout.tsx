import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "SAHJONY Wholesale Ops",
  description: "Autonomous wholesale real estate workforce",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
