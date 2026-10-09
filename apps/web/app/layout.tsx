import type { Metadata } from "next";
import localFont from "next/font/local";

import { SessionProvider } from "@/lib/session/session-context";

import "./globals.css";

// Poppins, self-hosted (Home UI V1): the Latin subset files live in `app/fonts` and are served by
// `next/font/local` - no `<link>` to Google Fonts and no font request to a third party at runtime
// or at build time. See `app/fonts/README.md` for the license note.
const poppins = localFont({
  src: [
    { path: "./fonts/Poppins-300.woff2", weight: "300", style: "normal" },
    { path: "./fonts/Poppins-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/Poppins-500.woff2", weight: "500", style: "normal" },
    { path: "./fonts/Poppins-600.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-poppins",
  display: "swap",
  fallback: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
});

export const metadata: Metadata = {
  title: "NINFA",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="it" className={poppins.variable}>
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
