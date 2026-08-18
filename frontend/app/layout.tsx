import "./globals.css";
import "./premium.css";
import "./cinematic-login-v2.css";
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
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#030406",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
