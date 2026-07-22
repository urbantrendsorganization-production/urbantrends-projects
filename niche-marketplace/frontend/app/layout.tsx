import type { Metadata, Viewport } from "next";

import { SiteHeader } from "@/components/SiteHeader";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

export const metadata: Metadata = {
  title: "Marketplace",
  description: "A general-purpose classifieds marketplace.",
};

// Mobile-first: lock the viewport to device width.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <SiteHeader />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
