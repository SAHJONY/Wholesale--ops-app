import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: {
    default: "SAHJONY Wholesale Ops",
    template: "%s · SAHJONY Wholesale Ops",
  },
  description:
    "Supervised autonomous residential and commercial wholesale real estate operations.",
  applicationName: "SAHJONY Wholesale Ops",
  formatDetection: { telephone: false, address: false, email: false },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Matches --bg, so mobile browser chrome blends into the console.
  themeColor: "#07090d",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
