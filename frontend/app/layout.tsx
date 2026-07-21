import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: "SAHJONY | Wholesale Intelligence",
  description: "The autonomous command system for wholesale real estate operations.",
};

export const viewport: Viewport = { themeColor: "#050607" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
