import "./globals.css";
import "./premium.css";
import "./cinematic-login-v2.css";
import "./premium-ux-v3.css";
import "./public-site.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: {
    default: "SAHJONY Real Estate Operations",
    template: "%s · SAHJONY",
  },
  description:
    "SAHJONY real estate operations for property owners, cash buyers, brokers, and transaction partners.",
  applicationName: "SAHJONY Real Estate Operations",
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
