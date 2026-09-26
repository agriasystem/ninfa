import type { Metadata } from "next";

import { SessionProvider } from "@/lib/session/session-context";

import "./globals.css";

export const metadata: Metadata = {
  title: "NINFA",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="it">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
