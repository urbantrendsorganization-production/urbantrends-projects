import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "BookNasi",
  description: "Appointment booking with M-Pesa deposits, for Kenyan salons and barbershops.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `.bn-root` carries every design token. The standalone app puts it on
    // <html>; the widget (slice 10) puts the same class on its mount container,
    // which is how a host site's overrides reach the same variables.
    <html lang="en-KE" className="bn-root">
      <body>{children}</body>
    </html>
  );
}
